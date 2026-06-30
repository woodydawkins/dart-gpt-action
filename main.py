import os
import io
import zipfile
import requests
import xml.etree.ElementTree as ET
from functools import lru_cache
from datetime import datetime, timedelta
from fastapi import FastAPI, Query, HTTPException
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="DART·KRX Disclosure & Market Research API",
    version="1.4.0",
    description=(
        "API server for connecting Custom GPT Actions to OpenDART and KRX Open API. "
        "It supports DART-registered companies, including listed and non-listed disclosure companies, "
        "and KRX market data for KOSPI, KOSDAQ, KONEX, and ETFs."
    )
)

# =========================================================
# Environment variables
# =========================================================

DART_API_KEY = os.getenv("DART_API_KEY")

KRX_API_KEY = os.getenv("KRX_API_KEY")
KRX_AUTH_HEADER_NAME = os.getenv("KRX_AUTH_HEADER_NAME", "AUTH_KEY")

# KRX 종목기본정보 API URL
KRX_KOSPI_STOCK_INFO_API_URL = os.getenv("KRX_KOSPI_STOCK_INFO_API_URL")
KRX_KOSDAQ_STOCK_INFO_API_URL = os.getenv("KRX_KOSDAQ_STOCK_INFO_API_URL")
KRX_KONEX_STOCK_INFO_API_URL = os.getenv("KRX_KONEX_STOCK_INFO_API_URL")

# KRX 일별매매정보 API URL
KRX_KOSPI_DAILY_PRICE_API_URL = os.getenv("KRX_KOSPI_DAILY_PRICE_API_URL")
KRX_KOSDAQ_DAILY_PRICE_API_URL = os.getenv("KRX_KOSDAQ_DAILY_PRICE_API_URL")
KRX_KONEX_DAILY_PRICE_API_URL = os.getenv("KRX_KONEX_DAILY_PRICE_API_URL")
KRX_ETF_DAILY_PRICE_API_URL = os.getenv("KRX_ETF_DAILY_PRICE_API_URL")

# KRX API 요청 파라미터명
# 현재 KRX 일별매매정보는 BAS_DD 기준일자 방식일 가능성이 높으므로,
# 기본적으로 BAS_DD를 사용합니다.
KRX_PARAM_BASE_DATE = os.getenv("KRX_PARAM_BASE_DATE", "BAS_DD")

# 일부 KRX API가 종목코드 파라미터를 지원하는 경우에만 사용
KRX_PARAM_STOCK_CODE = os.getenv("KRX_PARAM_STOCK_CODE", "ISU_CD")

# 기본값 false: KRX 일별매매정보 API에는 종목코드를 보내지 않고,
# 기준일 전체 시장 데이터를 받아온 뒤 서버에서 종목코드로 필터링합니다.
KRX_SEND_STOCK_CODE_PARAM = os.getenv("KRX_SEND_STOCK_CODE_PARAM", "false").lower() == "true"


# =========================================================
# Root / debug
# =========================================================

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "DART·KRX Disclosure & Market Research API is running.",
        "scope": {
            "dart": "DART-registered companies, including listed and non-listed disclosure companies.",
            "krx": "KRX market data for KOSPI, KOSDAQ, KONEX, and ETF if API URLs and key are configured."
        },
        "endpoints": {
            "dart": [
                "/dart/search-company",
                "/dart/disclosures",
                "/dart/financials"
            ],
            "krx": [
                "/krx/search-stock",
                "/krx/daily-price",
                "/krx/raw"
            ]
        }
    }


@app.get("/debug/env")
def debug_env():
    return {
        "has_dart_api_key": bool(DART_API_KEY),
        "dart_api_key_length": len(DART_API_KEY) if DART_API_KEY else 0,

        "has_krx_api_key": bool(KRX_API_KEY),
        "krx_api_key_length": len(KRX_API_KEY) if KRX_API_KEY else 0,
        "krx_auth_header_name": KRX_AUTH_HEADER_NAME,

        "has_krx_kospi_stock_info_api_url": bool(KRX_KOSPI_STOCK_INFO_API_URL),
        "has_krx_kosdaq_stock_info_api_url": bool(KRX_KOSDAQ_STOCK_INFO_API_URL),
        "has_krx_konex_stock_info_api_url": bool(KRX_KONEX_STOCK_INFO_API_URL),

        "has_krx_kospi_daily_price_api_url": bool(KRX_KOSPI_DAILY_PRICE_API_URL),
        "has_krx_kosdaq_daily_price_api_url": bool(KRX_KOSDAQ_DAILY_PRICE_API_URL),
        "has_krx_konex_daily_price_api_url": bool(KRX_KONEX_DAILY_PRICE_API_URL),
        "has_krx_etf_daily_price_api_url": bool(KRX_ETF_DAILY_PRICE_API_URL),

        "krx_param_base_date": KRX_PARAM_BASE_DATE,
        "krx_param_stock_code": KRX_PARAM_STOCK_CODE,
        "krx_send_stock_code_param": KRX_SEND_STOCK_CODE_PARAM,
    }


# =========================================================
# Common helpers
# =========================================================

def normalize_text(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_stock_code(stock_code):
    return normalize_text(stock_code)


def normalize_number(value):
    if value is None:
        return ""
    return str(value).strip()


def yyyymmdd_today_kst():
    """
    서버가 UTC 기준이어도 한국 날짜에 맞추기 위해 UTC+9 기준 오늘 날짜를 반환합니다.
    """
    return (datetime.utcnow() + timedelta(hours=9)).strftime("%Y%m%d")


def parse_yyyymmdd(date_str: str) -> datetime:
    try:
        return datetime.strptime(date_str, "%Y%m%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"날짜 형식이 올바르지 않습니다: {date_str}. YYYYMMDD 형식으로 입력하세요."
        )


def date_range_yyyymmdd(start_date: str, end_date: str):
    """
    start_date~end_date 사이의 모든 날짜를 YYYYMMDD 문자열 리스트로 반환합니다.
    주말/휴일도 포함합니다. KRX에서 데이터가 없으면 빈 결과로 처리합니다.
    """
    start = parse_yyyymmdd(start_date)
    end = parse_yyyymmdd(end_date)

    if start > end:
        raise HTTPException(
            status_code=400,
            detail="start_date는 end_date보다 늦을 수 없습니다."
        )

    # 너무 긴 기간 호출 방지
    if (end - start).days > 370:
        raise HTTPException(
            status_code=400,
            detail="KRX 일별 조회 기간은 370일 이하로 입력하세요."
        )

    dates = []
    cur = start
    while cur <= end:
        dates.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)

    return dates


# =========================================================
# DART helpers
# =========================================================

def is_listed_company(company):
    return bool(normalize_stock_code(company.get("stock_code")))


def add_company_metadata(company):
    stock_code = normalize_stock_code(company.get("stock_code"))
    is_listed = bool(stock_code)

    enriched = dict(company)
    enriched["stock_code"] = stock_code
    enriched["is_listed"] = is_listed
    enriched["company_type"] = "listed_company" if is_listed else "non_listed_disclosure_company"

    return enriched


@lru_cache(maxsize=1)
def load_corp_codes():
    if not DART_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="DART_API_KEY가 설정되어 있지 않습니다. Render 환경변수를 확인하세요."
        )

    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    params = {"crtfc_key": DART_API_KEY}

    try:
        res = requests.get(url, params=params, timeout=30)
    except requests.RequestException as e:
        raise HTTPException(
            status_code=500,
            detail=f"DART corpCode.xml 요청 실패: {str(e)}"
        )

    if res.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail=f"DART API HTTP 오류: {res.status_code}, 응답: {res.text[:500]}"
        )

    if not res.content.startswith(b"PK"):
        raise HTTPException(
            status_code=500,
            detail=(
                "DART corpCode.xml 응답이 ZIP 파일이 아닙니다. "
                "API 키 오류 또는 DART 오류 응답일 수 있습니다. "
                f"응답 앞부분: {res.text[:500]}"
            )
        )

    try:
        z = zipfile.ZipFile(io.BytesIO(res.content))
        xml_file = z.open(z.namelist()[0])

        tree = ET.parse(xml_file)
        root_xml = tree.getroot()

        companies = []
        for item in root_xml.findall("list"):
            stock_code = normalize_stock_code(item.findtext("stock_code"))

            company = {
                "corp_code": item.findtext("corp_code"),
                "corp_name": item.findtext("corp_name"),
                "stock_code": stock_code,
                "is_listed": bool(stock_code),
                "company_type": "listed_company" if stock_code else "non_listed_disclosure_company",
                "modify_date": item.findtext("modify_date"),
            }

            companies.append(company)

        return companies

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"corpCode.xml 파싱 실패: {str(e)}"
        )


def find_best_company(company_name):
    companies = load_corp_codes()
    query = company_name.strip()

    stock_code_match = [
        c for c in companies
        if normalize_stock_code(c.get("stock_code")) == query
    ]
    if stock_code_match:
        return add_company_metadata(stock_code_match[0])

    exact_listed = [
        c for c in companies
        if c.get("corp_name") == query and is_listed_company(c)
    ]
    if exact_listed:
        return add_company_metadata(exact_listed[0])

    exact = [
        c for c in companies
        if c.get("corp_name") == query
    ]
    if exact:
        return add_company_metadata(exact[0])

    partial_listed = [
        c for c in companies
        if query in (c.get("corp_name") or "") and is_listed_company(c)
    ]
    if partial_listed:
        return add_company_metadata(partial_listed[0])

    partial = [
        c for c in companies
        if query in (c.get("corp_name") or "")
    ]
    if partial:
        return add_company_metadata(partial[0])

    return None


def sort_company_results(results, query):
    query_clean = query.strip()

    sorted_results = sorted(
        results,
        key=lambda c: (
            not (normalize_stock_code(c.get("stock_code")) == query_clean),
            not (c.get("corp_name") == query_clean and is_listed_company(c)),
            not (c.get("corp_name") == query_clean),
            not is_listed_company(c),
            c.get("corp_name") or ""
        )
    )

    return [add_company_metadata(c) for c in sorted_results]


# =========================================================
# DART endpoints
# =========================================================

@app.get("/dart/search-company")
def search_company(
    query: str = Query(
        ...,
        description="회사명 또는 종목코드. 예: 삼성전자, 삼성전자판매, 005930"
    )
):
    companies = load_corp_codes()
    query_clean = query.strip()

    results = []
    for c in companies:
        corp_name = c.get("corp_name") or ""
        stock_code = normalize_stock_code(c.get("stock_code"))

        if query_clean in corp_name or query_clean == stock_code:
            results.append(c)

    sorted_results = sort_company_results(results, query_clean)
    best_company = find_best_company(query_clean)

    return {
        "query": query,
        "count": len(sorted_results),
        "best_company": best_company,
        "results": sorted_results[:20],
        "note": (
            "Search covers DART-registered companies. "
            "If multiple companies match, listed companies and exact matches are prioritized."
        )
    }


@app.get("/dart/disclosures")
def get_disclosures(
    company_name: str = Query(
        ...,
        description="회사명 또는 종목코드. 예: 삼성전자, 삼성전자판매, 005930"
    ),
    start_date: str = Query(..., description="조회 시작일 YYYYMMDD"),
    end_date: str = Query(..., description="조회 종료일 YYYYMMDD"),
    page_count: int = Query(30, description="조회 건수")
):
    company = find_best_company(company_name)

    if not company:
        return {
            "error": "company_not_found",
            "message": f"{company_name}에 해당하는 회사를 찾지 못했습니다."
        }

    corp_code = company["corp_code"]

    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bgn_de": start_date,
        "end_de": end_date,
        "page_no": 1,
        "page_count": page_count,
    }

    try:
        res = requests.get(url, params=params, timeout=30)
        data = res.json()
    except requests.RequestException as e:
        raise HTTPException(
            status_code=500,
            detail=f"DART 공시조회 요청 실패: {str(e)}"
        )
    except ValueError:
        raise HTTPException(
            status_code=500,
            detail=f"DART 공시조회 응답이 JSON이 아닙니다. 응답 앞부분: {res.text[:500]}"
        )

    disclosures = []
    for item in data.get("list", []):
        receipt_no = item.get("rcept_no")
        disclosures.append({
            "corp_name": item.get("corp_name"),
            "stock_code": normalize_stock_code(item.get("stock_code")),
            "report_name": item.get("report_nm"),
            "receipt_no": receipt_no,
            "receipt_date": item.get("rcept_dt"),
            "submitter": item.get("flr_nm"),
            "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}"
        })

    return {
        "company_name": company_name,
        "matched_company": company,
        "start_date": start_date,
        "end_date": end_date,
        "status": data.get("status"),
        "message": data.get("message"),
        "disclosures": disclosures,
        "note": (
            "Disclosure search can cover both listed and non-listed companies "
            "if the company is registered in DART and has disclosure records."
        )
    }


@app.get("/dart/financials")
def get_financials(
    company_name: str = Query(
        ...,
        description="회사명 또는 종목코드. 예: 삼성전자, 삼성전자판매, 005930"
    ),
    year: str = Query(..., description="사업연도. 예: 2025"),
    report_code: str = Query(
        ...,
        description="보고서 코드: 11011 사업보고서, 11012 반기, 11013 1분기, 11014 3분기"
    )
):
    company = find_best_company(company_name)

    if not company:
        return {
            "error": "company_not_found",
            "message": f"{company_name}에 해당하는 회사를 찾지 못했습니다."
        }

    corp_code = company["corp_code"]

    url = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": year,
        "reprt_code": report_code,
    }

    try:
        res = requests.get(url, params=params, timeout=30)
        data = res.json()
    except requests.RequestException as e:
        raise HTTPException(
            status_code=500,
            detail=f"DART 재무제표 요청 실패: {str(e)}"
        )
    except ValueError:
        raise HTTPException(
            status_code=500,
            detail=f"DART 재무제표 응답이 JSON이 아닙니다. 응답 앞부분: {res.text[:500]}"
        )

    accounts = []
    for item in data.get("list", []):
        accounts.append({
            "fs_div": item.get("fs_div"),
            "fs_nm": item.get("fs_nm"),
            "sj_div": item.get("sj_div"),
            "sj_nm": item.get("sj_nm"),
            "account_nm": item.get("account_nm"),
            "thstrm_nm": item.get("thstrm_nm"),
            "thstrm_amount": item.get("thstrm_amount"),
            "frmtrm_nm": item.get("frmtrm_nm"),
            "frmtrm_amount": item.get("frmtrm_amount"),
            "bfefrmtrm_nm": item.get("bfefrmtrm_nm"),
            "bfefrmtrm_amount": item.get("bfefrmtrm_amount"),
        })

    return {
        "company_name": company_name,
        "matched_company": company,
        "year": year,
        "report_code": report_code,
        "status": data.get("status"),
        "message": data.get("message"),
        "accounts": accounts,
        "note": (
            "Financial statement API results may be limited for non-listed companies "
            "or companies not covered by the DART financial statement API."
        )
    }


# =========================================================
# KRX helpers
# =========================================================

def call_krx_api(api_url, params):
    """
    KRX Open API 공통 호출 함수.
    인증키는 Header의 AUTH_KEY로 전달합니다.
    """
    if not KRX_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="KRX_API_KEY가 설정되어 있지 않습니다. Render 환경변수를 확인하세요."
        )

    if not api_url:
        raise HTTPException(
            status_code=500,
            detail="KRX API URL이 설정되어 있지 않습니다. Render 환경변수를 확인하세요."
        )

    headers = {
        KRX_AUTH_HEADER_NAME: KRX_API_KEY
    }

    clean_params = {
        k: v for k, v in params.items()
        if v is not None and str(v).strip() != ""
    }

    try:
        res = requests.get(api_url, params=clean_params, headers=headers, timeout=30)
        res.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(
            status_code=500,
            detail=f"KRX API 요청 실패: {str(e)}"
        )

    try:
        return res.json()
    except ValueError:
        raise HTTPException(
            status_code=500,
            detail=f"KRX API 응답이 JSON이 아닙니다. 응답 앞부분: {res.text[:500]}"
        )


def extract_krx_items(data):
    """
    KRX API 응답에서 목록성 데이터를 최대한 유연하게 추출합니다.
    """
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    possible_keys = [
        "OutBlock_1",
        "OutBlock",
        "output",
        "items",
        "item",
        "list",
        "data",
        "result",
        "results",
    ]

    for key in possible_keys:
        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            for nested_key in possible_keys:
                nested_value = value.get(nested_key)
                if isinstance(nested_value, list):
                    return nested_value

    response = data.get("response")
    if isinstance(response, dict):
        body = response.get("body")
        if isinstance(body, dict):
            items = body.get("items")
            if isinstance(items, dict):
                item = items.get("item")
                if isinstance(item, list):
                    return item
                if isinstance(item, dict):
                    return [item]

    return []


def normalize_krx_stock_item(item, market_hint=""):
    """
    KRX 종목정보 필드명을 표준화합니다.
    """
    stock_code = (
        item.get("ISU_SRT_CD")
        or item.get("ISU_CD")
        or item.get("isu_srt_cd")
        or item.get("isu_cd")
        or item.get("short_code")
        or item.get("stock_code")
        or item.get("srtn_cd")
        or item.get("SRTN_CD")
        or item.get("ISU_CD_NM")
        or ""
    )

    stock_name = (
        item.get("ISU_ABBRV")
        or item.get("ISU_NM")
        or item.get("isu_abbrv")
        or item.get("isu_nm")
        or item.get("stock_name")
        or item.get("itms_nm")
        or item.get("ITMS_NM")
        or item.get("name")
        or ""
    )

    market = (
        item.get("MKT_NM")
        or item.get("mkt_nm")
        or item.get("market")
        or market_hint
        or ""
    )

    return {
        "stock_code": normalize_text(stock_code),
        "stock_name": normalize_text(stock_name),
        "market": normalize_text(market),
        "raw": item
    }


def normalize_krx_daily_item(item, market_hint=""):
    """
    KRX 일별매매정보 필드명을 표준화합니다.
    """
    base_date = (
        item.get("BAS_DD")
        or item.get("bas_dd")
        or item.get("TRD_DD")
        or item.get("trd_dd")
        or item.get("date")
        or ""
    )

    stock_code = (
        item.get("ISU_SRT_CD")
        or item.get("ISU_CD")
        or item.get("isu_srt_cd")
        or item.get("isu_cd")
        or item.get("stock_code")
        or item.get("SRTN_CD")
        or item.get("srtn_cd")
        or ""
    )

    stock_name = (
        item.get("ISU_ABBRV")
        or item.get("ISU_NM")
        or item.get("isu_abbrv")
        or item.get("isu_nm")
        or item.get("stock_name")
        or item.get("ITMS_NM")
        or item.get("itms_nm")
        or ""
    )

    close_price = (
        item.get("TDD_CLSPRC")
        or item.get("CLSPRC")
        or item.get("close_price")
        or item.get("clpr")
        or ""
    )

    open_price = (
        item.get("TDD_OPNPRC")
        or item.get("OPNPRC")
        or item.get("open_price")
        or item.get("mkp")
        or ""
    )

    high_price = (
        item.get("TDD_HGPRC")
        or item.get("HGPRC")
        or item.get("high_price")
        or item.get("hipr")
        or ""
    )

    low_price = (
        item.get("TDD_LWPRC")
        or item.get("LWPRC")
        or item.get("low_price")
        or item.get("lopr")
        or ""
    )

    volume = (
        item.get("ACC_TRDVOL")
        or item.get("TRDVOL")
        or item.get("volume")
        or item.get("trqu")
        or ""
    )

    trading_value = (
        item.get("ACC_TRDVAL")
        or item.get("TRDVAL")
        or item.get("trading_value")
        or ""
    )

    market_cap = (
        item.get("MKTCAP")
        or item.get("market_cap")
        or item.get("mrkt_tot_amt")
        or ""
    )

    return {
        "base_date": normalize_text(base_date),
        "stock_code": normalize_text(stock_code),
        "stock_name": normalize_text(stock_name),
        "market": normalize_text(market_hint),
        "open_price": normalize_number(open_price),
        "high_price": normalize_number(high_price),
        "low_price": normalize_number(low_price),
        "close_price": normalize_number(close_price),
        "volume": normalize_number(volume),
        "trading_value": normalize_number(trading_value),
        "market_cap": normalize_number(market_cap),
        "raw": item
    }


def get_stock_info_api_urls_by_market(market):
    market_upper = market.upper()

    urls = []

    if market_upper in ["ALL", "KOSPI"]:
        urls.append(("KOSPI", KRX_KOSPI_STOCK_INFO_API_URL))

    if market_upper in ["ALL", "KOSDAQ"]:
        urls.append(("KOSDAQ", KRX_KOSDAQ_STOCK_INFO_API_URL))

    if market_upper in ["ALL", "KONEX"]:
        urls.append(("KONEX", KRX_KONEX_STOCK_INFO_API_URL))

    return urls


def get_daily_price_api_urls_by_market(market):
    market_upper = market.upper()

    urls = []

    if market_upper in ["AUTO", "ALL", "KOSPI"]:
        urls.append(("KOSPI", KRX_KOSPI_DAILY_PRICE_API_URL))

    if market_upper in ["AUTO", "ALL", "KOSDAQ"]:
        urls.append(("KOSDAQ", KRX_KOSDAQ_DAILY_PRICE_API_URL))

    if market_upper in ["AUTO", "ALL", "KONEX"]:
        urls.append(("KONEX", KRX_KONEX_DAILY_PRICE_API_URL))

    if market_upper in ["AUTO", "ALL", "ETF"]:
        urls.append(("ETF", KRX_ETF_DAILY_PRICE_API_URL))

    return urls


# =========================================================
# KRX endpoints
# =========================================================

@app.get("/krx/search-stock")
def krx_search_stock(
    query: str = Query(..., description="회사명 또는 종목코드. 예: 삼성전자, 005930"),
    market: str = Query(
        "ALL",
        description="시장구분: ALL, KOSPI, KOSDAQ, KONEX"
    ),
    base_date: str = Query(
        None,
        description="기준일 YYYYMMDD. 미입력 시 한국시간 기준 오늘 날짜 사용"
    )
):
    """
    KRX 종목기본정보를 회사명 또는 종목코드로 검색합니다.

    KRX 종목기본정보 API가 BAS_DD 기준일을 요구할 수 있으므로,
    기본적으로 기준일 파라미터를 함께 보냅니다.
    """
    query_clean = query.strip()
    base_date_value = base_date or yyyymmdd_today_kst()

    urls = get_stock_info_api_urls_by_market(market)

    if not urls:
        raise HTTPException(
            status_code=400,
            detail="market은 ALL, KOSPI, KOSDAQ, KONEX 중 하나여야 합니다."
        )

    all_results = []
    api_status = []

    for market_name, api_url in urls:
        if not api_url:
            api_status.append({
                "market": market_name,
                "status": "skipped",
                "reason": "API URL is not configured"
            })
            continue

        params = {
            KRX_PARAM_BASE_DATE: base_date_value
        }

        data = call_krx_api(api_url, params=params)
        items = extract_krx_items(data)

        api_status.append({
            "market": market_name,
            "status": "ok",
            "base_date": base_date_value,
            "item_count": len(items)
        })

        for item in items:
            normalized = normalize_krx_stock_item(item, market_hint=market_name)
            stock_code = normalized["stock_code"]
            stock_name = normalized["stock_name"]

            if query_clean == stock_code or query_clean in stock_name:
                all_results.append(normalized)

    all_results = sorted(
        all_results,
        key=lambda x: (
            not (x["stock_code"] == query_clean),
            not (x["stock_name"] == query_clean),
            x["market"],
            x["stock_name"]
        )
    )

    best_stock = all_results[0] if all_results else None

    return {
        "query": query,
        "market": market,
        "base_date": base_date_value,
        "count": len(all_results),
        "best_stock": best_stock,
        "results": all_results[:20],
        "api_status": api_status,
        "note": (
            "KRX stock search uses BAS_DD-style base date parameter. "
            "If no results are returned, check approved API URLs, AUTH_KEY, base_date, and response field mapping."
        )
    }


@app.get("/krx/daily-price")
def krx_daily_price(
    stock_code: str = Query(..., description="종목코드. 예: 005930"),
    start_date: str = Query(..., description="조회 시작일 YYYYMMDD"),
    end_date: str = Query(..., description="조회 종료일 YYYYMMDD"),
    market: str = Query(
        "AUTO",
        description="시장구분: AUTO, ALL, KOSPI, KOSDAQ, KONEX, ETF"
    )
):
    """
    KRX 일별매매정보를 조회합니다.

    KRX 일별매매정보 API가 기간조회가 아니라 BAS_DD 기준일 조회 방식일 수 있으므로,
    start_date~end_date 기간의 각 날짜별로 API를 반복 호출합니다.

    기본 market=AUTO는 KOSPI, KOSDAQ, KONEX, ETF 순서로 조회하여,
    해당 종목코드가 포함된 시장의 데이터를 우선 반환합니다.
    """
    market_upper = market.upper()
    urls = get_daily_price_api_urls_by_market(market_upper)

    if not urls:
        raise HTTPException(
            status_code=400,
            detail="market은 AUTO, ALL, KOSPI, KOSDAQ, KONEX, ETF 중 하나여야 합니다."
        )

    target_dates = date_range_yyyymmdd(start_date, end_date)

    all_results = []
    api_status = []

    for market_name, api_url in urls:
        if not api_url:
            api_status.append({
                "market": market_name,
                "status": "skipped",
                "reason": "API URL is not configured"
            })
            continue

        market_results = []

        for target_date in target_dates:
            params = {
                KRX_PARAM_BASE_DATE: target_date
            }

            # 기본값은 false입니다.
            # KRX API가 종목코드 파라미터를 요구하는 경우에만 Render 환경변수
            # KRX_SEND_STOCK_CODE_PARAM=true로 바꿔 사용합니다.
            if KRX_SEND_STOCK_CODE_PARAM:
                params[KRX_PARAM_STOCK_CODE] = stock_code

            try:
                data = call_krx_api(api_url, params=params)
            except HTTPException as e:
                api_status.append({
                    "market": market_name,
                    "date": target_date,
                    "status": "error",
                    "detail": e.detail
                })
                continue

            items = extract_krx_items(data)

            matched_items = []
            for item in items:
                normalized = normalize_krx_daily_item(item, market_hint=market_name)
                item_stock_code = normalized.get("stock_code") or ""

                # 일부 API가 요청한 단일 종목 데이터만 반환하고 종목코드 필드를 생략할 수 있음
                if not item_stock_code and KRX_SEND_STOCK_CODE_PARAM:
                    normalized["stock_code"] = stock_code
                    item_stock_code = stock_code

                if item_stock_code == stock_code:
                    # 응답에 기준일이 없으면 요청 기준일로 보완
                    if not normalized.get("base_date"):
                        normalized["base_date"] = target_date

                    matched_items.append(normalized)

            api_status.append({
                "market": market_name,
                "date": target_date,
                "status": "ok",
                "item_count": len(items),
                "matched_count": len(matched_items)
            })

            market_results.extend(matched_items)

        all_results.extend(market_results)

        # AUTO 모드에서는 처음으로 결과가 나온 시장만 사용
        if market_upper == "AUTO" and market_results:
            break

    all_results = sorted(
        all_results,
        key=lambda x: x.get("base_date") or ""
    )

    return {
        "stock_code": stock_code,
        "start_date": start_date,
        "end_date": end_date,
        "market": market,
        "count": len(all_results),
        "prices": all_results,
        "api_status": api_status,
        "note": (
            "KRX daily trading data is requested by BAS_DD for each date and filtered by stock_code on the server. "
            "If results are empty, check whether the API URL returns all market rows for BAS_DD, "
            "or whether KRX_SEND_STOCK_CODE_PARAM should be set to true."
        )
    }


@app.get("/krx/raw")
def krx_raw(
    api_type: str = Query(
        ...,
        description=(
            "API 유형: KOSPI_STOCK_INFO, KOSDAQ_STOCK_INFO, KONEX_STOCK_INFO, "
            "KOSPI_DAILY, KOSDAQ_DAILY, KONEX_DAILY, ETF_DAILY"
        )
    ),
    base_date: str = Query(
        None,
        description="기준일 YYYYMMDD. 미입력 시 한국시간 기준 오늘 날짜 사용"
    )
):
    """
    KRX 응답 구조 확인용 원시 응답 엔드포인트입니다.
    GPT 스키마에는 넣지 않아도 됩니다.
    """
    base_date_value = base_date or yyyymmdd_today_kst()

    api_type_upper = api_type.upper()

    api_map = {
        "KOSPI_STOCK_INFO": KRX_KOSPI_STOCK_INFO_API_URL,
        "KOSDAQ_STOCK_INFO": KRX_KOSDAQ_STOCK_INFO_API_URL,
        "KONEX_STOCK_INFO": KRX_KONEX_STOCK_INFO_API_URL,
        "KOSPI_DAILY": KRX_KOSPI_DAILY_PRICE_API_URL,
        "KOSDAQ_DAILY": KRX_KOSDAQ_DAILY_PRICE_API_URL,
        "KONEX_DAILY": KRX_KONEX_DAILY_PRICE_API_URL,
        "ETF_DAILY": KRX_ETF_DAILY_PRICE_API_URL,
    }

    api_url = api_map.get(api_type_upper)

    if not api_url:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 api_type입니다: {api_type}"
        )

    params = {
        KRX_PARAM_BASE_DATE: base_date_value
    }

    data = call_krx_api(api_url, params=params)
    items = extract_krx_items(data)

    return {
        "api_type": api_type_upper,
        "base_date": base_date_value,
        "item_count": len(items),
        "sample_items": items[:5],
        "raw": data
    }
