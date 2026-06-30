import os
import io
import zipfile
import requests
import xml.etree.ElementTree as ET
from functools import lru_cache
from datetime import datetime, timedelta
from fastapi import FastAPI, Query, HTTPException
from dotenv import load_dotenv
from typing import Any, Optional

load_dotenv()

app = FastAPI(
    title="DART·KRX Disclosure & Market Research API",
    version="1.7.0",
    description=(
        "API server for connecting Custom GPT Actions to OpenDART, KRX Open API, "
        "and Korea Law Open API. It supports DART-registered companies, including listed and non-listed disclosure companies, "
        "KRX market data for KOSPI, KOSDAQ, KONEX, and ETFs, legal search/article lookup, "
        "treaty search/detail lookup, and tax-law research endpoints for cases, appeals, interpretations, administrative rules, attachments, histories, comparisons, terms, and related laws."
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


LAW_OC = os.getenv("LAW_OC")

LAW_SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
LAW_SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"

# =========================================================
# Root / debug
# =========================================================

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "DART·KRX·LAW Disclosure, Market & Legal Research API is running.",
        "scope": {
            "dart": "DART-registered companies, including listed and non-listed disclosure companies.",
            "krx": "KRX market data for KOSPI, KOSDAQ, KONEX, and ETF if API URLs and key are configured.",
            "law": "Korea Law Open API search, article lookup, and treaty lookup if LAW_OC is configured."
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
            ],
            "law": [
                "/law/search",
                "/law/detail",
                "/law/article",
                "/law/treaties/search",
                "/law/treaties/detail",
                "/law/interpretations/search",
                "/law/interpretations/detail",
                "/law/constitutional-cases/search",
                "/law/constitutional-cases/detail",
                "/law/terms/search",
                "/law/terms/detail",
                "/law/related-laws/search"
            ],
            "tax": [
                "/tax/laws/catalog",
                "/tax/laws/search",
                "/tax/laws/article",
                "/tax/laws/package",
                "/tax/laws/effective-article",
                "/tax/laws/history",
                "/tax/laws/article-history",
                "/tax/laws/compare",
                "/tax/laws/three-way-compare",
                "/tax/cases/search",
                "/tax/cases/detail",
                "/tax/appeals/search",
                "/tax/appeals/detail",
                "/tax/nts-interpretations/search",
                "/tax/admin-rules/search",
                "/tax/admin-rules/detail",
                "/tax/attachments/search",
                "/tax/terms/search",
                "/tax/terms/detail",
                "/tax/related-laws/search"
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

        "has_law_oc": bool(LAW_OC),
        "law_oc_length": len(LAW_OC) if LAW_OC else 0,
        "law_search_url": LAW_SEARCH_URL,
        "law_service_url": LAW_SERVICE_URL,
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
# LAW helpers
# =========================================================

def require_law_oc() -> str:
    """
    국가법령정보 공동활용 API 인증값(OC) 확인.
    .env 또는 Render 환경변수에 LAW_OC를 설정해야 합니다.
    """
    if not LAW_OC:
        raise HTTPException(
            status_code=500,
            detail="LAW_OC가 설정되어 있지 않습니다. Render 환경변수 또는 .env 파일을 확인하세요."
        )
    return LAW_OC


def normalize_law_search_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    국가법령정보 lawSearch JSON 응답을 GPT가 다루기 쉬운 리스트로 정규화합니다.
    보통 data["LawSearch"]["law"] 구조이나, 단건/빈값 케이스를 방어합니다.
    """
    if not isinstance(data, dict):
        return []

    law_search = data.get("LawSearch") or data.get("lawSearch") or data
    if not isinstance(law_search, dict):
        return []

    laws = law_search.get("law", [])
    if isinstance(laws, dict):
        laws = [laws]
    if laws is None:
        laws = []

    result = []
    for item in laws:
        if not isinstance(item, dict):
            continue

        result.append({
            "law_id": item.get("법령ID") or item.get("lawId") or item.get("ID"),
            "mst": item.get("법령일련번호") or item.get("MST"),
            "law_name": item.get("법령명한글") or item.get("법령명") or item.get("lawName"),
            "law_short_name": item.get("법령약칭명") or item.get("법령약칭") or item.get("lawShortName"),
            "law_type": item.get("법령구분명") or item.get("법령구분"),
            "ministry": item.get("소관부처명") or item.get("소관부처"),
            "promulgation_date": item.get("공포일자"),
            "enforcement_date": item.get("시행일자"),
            "revision_type": item.get("제개정구분명"),
            "detail_link": item.get("법령상세링크"),
            "raw": item,
        })

    return result


def format_jo(article_no: str) -> str:
    """
    법제처 JO 형식 변환.
    예:
    - '2'      -> '000200'
    - '10-2'   -> '001002'
    - '18의2'  -> '001802'
    - '제18조의2' -> '001802'
    """
    raw = normalize_text(article_no)
    raw = (
        raw.replace("제", "")
        .replace("조", "")
        .replace(" ", "")
        .replace("의", "-")
    )

    if not raw:
        raise HTTPException(status_code=400, detail="article_no를 입력하세요. 예: 18 또는 18-2")

    if "-" in raw:
        main, sub = raw.split("-", 1)
        sub = sub or "0"
    else:
        main, sub = raw, "0"

    try:
        main_num = int(main)
        sub_num = int(sub)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="article_no 형식이 올바르지 않습니다. 예: 18, 18-2, 제18조의2"
        )

    if main_num <= 0 or sub_num < 0:
        raise HTTPException(
            status_code=400,
            detail="article_no는 양수 조문번호여야 합니다. 예: 18 또는 18-2"
        )

    return f"{main_num:04d}{sub_num:02d}"


def find_first_law(laws: list[dict[str, Any]], query: str) -> Optional[dict[str, Any]]:
    """
    검색 결과에서 법령명을 기준으로 가장 적절한 법령 선택.
    1순위: 법령명 완전일치
    2순위: 약칭 완전일치
    3순위: 법령명 부분일치
    4순위: 첫 번째 결과
    """
    q = normalize_text(query).replace(" ", "")

    for law in laws:
        name = normalize_text(law.get("law_name")).replace(" ", "")
        if name == q:
            return law

    for law in laws:
        short_name = normalize_text(law.get("law_short_name")).replace(" ", "")
        if short_name == q:
            return law

    for law in laws:
        name = normalize_text(law.get("law_name")).replace(" ", "")
        if q and q in name:
            return law

    return laws[0] if laws else None


def call_law_api(url: str, params: dict[str, Any]) -> requests.Response:
    """
    국가법령정보 API 공통 호출 함수.
    """
    clean_params = {
        k: v for k, v in params.items()
        if v is not None and str(v).strip() != ""
    }

    try:
        res = requests.get(url, params=clean_params, timeout=30)
        res.raise_for_status()
        return res
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"국가법령정보 API 요청 실패: {str(e)}"
        )


def parse_law_response(res: requests.Response, response_type: str):
    """
    국가법령정보 API 응답을 response_type에 따라 반환합니다.
    JSON은 dict/list로 반환하고, XML/HTML은 text로 반환합니다.
    """
    if response_type.upper() == "JSON":
        try:
            return res.json()
        except ValueError:
            raise HTTPException(
                status_code=502,
                detail=f"국가법령정보 API 응답이 JSON이 아닙니다. 응답 앞부분: {res.text[:500]}"
            )

    return {
        "content_type": res.headers.get("content-type"),
        "text": res.text,
    }


def pick_first(item: dict[str, Any], *keys: str):
    """
    국가법령정보 API의 한글/영문/버전별 필드명을 유연하게 처리하기 위한 helper.
    """
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def find_first_list(value: Any, preferred_keys: list[str]) -> list[Any]:
    """
    국가법령정보 API 응답 구조가 서비스별로 조금씩 다르기 때문에,
    지정한 후보 key 또는 중첩 dict에서 첫 번째 list를 찾아 반환합니다.
    """
    if isinstance(value, list):
        return value

    if not isinstance(value, dict):
        return []

    for key in preferred_keys:
        candidate = value.get(key)
        if isinstance(candidate, list):
            return candidate
        if isinstance(candidate, dict):
            return [candidate]

    for candidate in value.values():
        if isinstance(candidate, list):
            return candidate
        if isinstance(candidate, dict):
            nested = find_first_list(candidate, preferred_keys)
            if nested:
                return nested

    return []


def normalize_treaty_search_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    국가법령정보 조약 목록(lawSearch.do?target=trty) JSON 응답을 GPT가 다루기 쉬운 리스트로 정규화합니다.
    API 응답 필드명이 한글/영문/서비스 버전에 따라 달라질 수 있어 가능한 필드명을 폭넓게 수용합니다.
    """
    if not isinstance(data, dict):
        return []

    root = (
        data.get("TrtySearch")
        or data.get("trtySearch")
        or data.get("TreatySearch")
        or data.get("treatySearch")
        or data
    )

    treaty_items = find_first_list(
        root,
        preferred_keys=[
            "trty",
            "treaty",
            "조약",
            "Trty",
            "Treaty",
            "items",
            "item",
            "list",
            "data",
            "result",
            "results",
        ],
    )

    result = []
    for item in treaty_items:
        if not isinstance(item, dict):
            continue

        result.append({
            "treaty_id": pick_first(
                item,
                "조약ID", "조약일련번호", "ID", "id", "trtyId", "treatyId", "trty_id", "treaty_id"
            ),
            "mst": pick_first(item, "MST", "mst", "조약일련번호"),
            "treaty_name_ko": pick_first(
                item,
                "조약명한글", "조약명", "한글조약명", "trtyNm", "treatyNameKo", "treaty_name_ko"
            ),
            "treaty_name_en": pick_first(
                item,
                "조약명영문", "영문조약명", "trtyNmEng", "treatyNameEn", "treaty_name_en"
            ),
            "treaty_no": pick_first(item, "조약번호", "trtyNo", "treatyNo", "treaty_no"),
            "country_name": pick_first(item, "국가명", "상대국", "체약국", "natNm", "countryName", "country_name"),
            "country_code": pick_first(item, "국가코드", "natCd", "countryCode", "country_code"),
            "treaty_class": pick_first(item, "조약구분", "조약구분명", "분류", "cls", "className", "treaty_class"),
            "signature_date": pick_first(item, "서명일자", "서명일", "signDate", "signatureDate", "signature_date"),
            "promulgation_date": pick_first(item, "공포일자", "공포일", "promulgationDate", "promulgation_date"),
            "enforcement_date": pick_first(item, "발효일자", "발효일", "시행일자", "effectiveDate", "enforcement_date"),
            "revision_type": pick_first(item, "제개정구분명", "개정구분", "revisionType", "revision_type"),
            "detail_link": pick_first(item, "조약상세링크", "상세링크", "detailLink", "detail_link"),
            "raw": item,
        })

    return result


def find_first_treaty(treaties: list[dict[str, Any]], query: str) -> Optional[dict[str, Any]]:
    """
    검색 결과에서 조약명을 기준으로 가장 적절한 조약 선택.
    1순위: 한글 조약명 완전일치
    2순위: 영문 조약명 완전일치
    3순위: 한글/영문 조약명 부분일치
    4순위: 첫 번째 결과
    """
    q = normalize_text(query).replace(" ", "")

    if not treaties:
        return None

    if not q:
        return treaties[0]

    for treaty in treaties:
        name_ko = normalize_text(treaty.get("treaty_name_ko")).replace(" ", "")
        if name_ko == q:
            return treaty

    for treaty in treaties:
        name_en = normalize_text(treaty.get("treaty_name_en")).replace(" ", "").lower()
        if name_en == q.lower():
            return treaty

    for treaty in treaties:
        name_ko = normalize_text(treaty.get("treaty_name_ko")).replace(" ", "")
        name_en = normalize_text(treaty.get("treaty_name_en")).replace(" ", "").lower()
        if q in name_ko or q.lower() in name_en:
            return treaty

    return treaties[0]


def treaty_language_to_chr_cls_cd(language: str, chr_cls_cd: Optional[str] = None) -> str:
    """
    국가법령정보 조약 본문 언어 코드 변환.
    - ko: 한글 본문(010202)
    - en: 영문 본문(010203)
    chr_cls_cd를 직접 넘기면 해당 값을 우선합니다.
    """
    if chr_cls_cd:
        return chr_cls_cd

    lang = normalize_text(language).lower()

    if lang in ["en", "eng", "english", "영문", "영어"]:
        return "010203"

    return "010202"


# =========================================================
# LAW endpoints
# =========================================================

@app.get("/law/search")
def search_law(
    query: str = Query(..., description="검색할 법령명 또는 키워드. 예: 법인세법"),
    search: int = Query(1, description="검색범위. 1=법령명, 2=본문검색"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    sort: str = Query("lasc", description="정렬옵션. 예: lasc, ldes, dasc, ddes")
):
    """
    국가법령정보 현행법령 목록 검색.
    GPT Action에서는 법령명 확인 및 law_id/MST 확인용으로 사용합니다.
    """
    oc = require_law_oc()

    params = {
        "OC": oc,
        "target": "law",
        "type": "JSON",
        "query": query,
        "search": search,
        "display": display,
        "page": page,
        "sort": sort,
    }

    res = call_law_api(LAW_SEARCH_URL, params=params)
    data = parse_law_response(res, "JSON")
    laws = normalize_law_search_response(data)
    best_law = find_first_law(laws, query)

    return {
        "query": query,
        "search": search,
        "page": page,
        "display": display,
        "count": len(laws),
        "best_law": best_law,
        "laws": laws,
        "note": "법령명으로 특정 조문을 바로 조회하려면 /law/article을 사용하세요."
    }


@app.get("/law/detail")
def get_law_detail(
    law_id: Optional[str] = Query(None, description="법령ID. 예: 009682"),
    mst: Optional[str] = Query(None, description="법령일련번호/MST"),
    article_no: Optional[str] = Query(None, description="조문번호. 예: 18, 18-2, 제18조의2"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    """
    법령ID 또는 MST로 현행법령 본문/특정 조문 조회.
    law_id 또는 mst 중 하나는 필수입니다.
    """
    oc = require_law_oc()
    response_type_upper = response_type.upper()

    if response_type_upper not in ["JSON", "XML", "HTML"]:
        raise HTTPException(status_code=400, detail="response_type은 JSON, XML, HTML 중 하나여야 합니다.")

    if not law_id and not mst:
        raise HTTPException(status_code=400, detail="law_id 또는 mst 중 하나는 필수입니다.")

    params = {
        "OC": oc,
        "target": "law",
        "type": response_type_upper,
    }

    if law_id:
        params["ID"] = law_id
    if mst:
        params["MST"] = mst
    if article_no:
        params["JO"] = format_jo(article_no)

    res = call_law_api(LAW_SERVICE_URL, params=params)
    data = parse_law_response(res, response_type_upper)

    return {
        "law_id": law_id,
        "mst": mst,
        "article_no": article_no,
        "jo": format_jo(article_no) if article_no else None,
        "response_type": response_type_upper,
        "data": data,
    }


@app.get("/law/article")
def get_law_article(
    law_name: str = Query(..., description="법령명. 예: 법인세법, 소득세법, 조세특례제한법"),
    article_no: str = Query(..., description="조문번호. 예: 18, 18-2, 제18조의2"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    """
    법령명 검색 후 가장 적절한 법령을 선택하여 특정 조문을 조회합니다.
    GPT Action에서는 이 엔드포인트를 가장 자주 사용하면 됩니다.
    """
    oc = require_law_oc()
    response_type_upper = response_type.upper()

    if response_type_upper not in ["JSON", "XML", "HTML"]:
        raise HTTPException(status_code=400, detail="response_type은 JSON, XML, HTML 중 하나여야 합니다.")

    # 1. 법령명 검색
    search_params = {
        "OC": oc,
        "target": "law",
        "type": "JSON",
        "query": law_name,
        "search": 1,
        "display": 10,
        "page": 1,
        "sort": "lasc",
    }

    search_res = call_law_api(LAW_SEARCH_URL, params=search_params)
    search_data = parse_law_response(search_res, "JSON")
    laws = normalize_law_search_response(search_data)
    selected_law = find_first_law(laws, law_name)

    if not selected_law:
        raise HTTPException(status_code=404, detail=f"{law_name}에 해당하는 법령을 찾지 못했습니다.")

    law_id = selected_law.get("law_id")
    mst = selected_law.get("mst")

    if not law_id and not mst:
        raise HTTPException(
            status_code=502,
            detail="법령 검색 결과에 law_id 또는 mst가 포함되어 있지 않습니다."
        )

    jo = format_jo(article_no)

    # 2. 특정 조문 조회
    detail_params = {
        "OC": oc,
        "target": "law",
        "type": response_type_upper,
        "JO": jo,
    }

    if law_id:
        detail_params["ID"] = law_id
    else:
        detail_params["MST"] = mst

    detail_res = call_law_api(LAW_SERVICE_URL, params=detail_params)
    detail_data = parse_law_response(detail_res, response_type_upper)

    return {
        "law_name": selected_law.get("law_name"),
        "law_short_name": selected_law.get("law_short_name"),
        "law_id": law_id,
        "mst": mst,
        "law_type": selected_law.get("law_type"),
        "ministry": selected_law.get("ministry"),
        "promulgation_date": selected_law.get("promulgation_date"),
        "enforcement_date": selected_law.get("enforcement_date"),
        "article_no": article_no,
        "jo": jo,
        "response_type": response_type_upper,
        "data": detail_data,
        "note": "과거 시행일 기준 조문 조회는 추후 target=eflaw 방식으로 별도 엔드포인트를 추가하는 것을 권장합니다."
    }


@app.get("/law/treaties/search")
def search_treaties(
    query: str = Query("", description="검색어. 예: 미국, 일본, 이중과세, 소득"),
    search: int = Query(1, ge=1, le=2, description="검색범위. 1=조약명, 2=본문검색"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    cls: Optional[int] = Query(None, description="조약분류. 1=양자조약, 2=다자조약"),
    natCd: Optional[int] = Query(None, description="국가법령정보 API 국가코드"),
    sort: str = Query("lasc", description="정렬옵션. 예: lasc, ldes, dasc, ddes, nasc, ndes, rasc, rdes")
):
    """
    국가법령정보 조약 목록 검색.
    조세조약, 이중과세방지협정, 제한세율 검토의 1차 검색용으로 사용합니다.
    내부적으로 lawSearch.do?target=trty를 호출합니다.
    """
    oc = require_law_oc()

    params = {
        "OC": oc,
        "target": "trty",
        "type": "JSON",
        "query": query,
        "search": search,
        "display": display,
        "page": page,
        "sort": sort,
    }

    if cls is not None:
        params["cls"] = cls

    if natCd is not None:
        params["natCd"] = natCd

    res = call_law_api(LAW_SEARCH_URL, params=params)
    data = parse_law_response(res, "JSON")
    treaties = normalize_treaty_search_response(data)
    best_treaty = find_first_treaty(treaties, query)

    return {
        "query": query,
        "search": search,
        "page": page,
        "display": display,
        "count": len(treaties),
        "best_treaty": best_treaty,
        "treaties": treaties,
        "note": (
            "조약 본문은 /law/treaties/detail에서 treaty_id 또는 query를 사용해 조회하세요. "
            "조세조약 적용 여부와 제한세율은 조약 본문, 국내 세법, 시행령, 예규 및 사실관계 확인이 함께 필요합니다."
        ),
    }


@app.get("/law/treaties/detail")
def get_treaty_detail(
    treaty_id: Optional[str] = Query(None, description="조약ID 또는 조약일련번호. /law/treaties/search 결과의 treaty_id 사용"),
    id: Optional[str] = Query(None, description="조약ID. GPT Action schema에서 id라는 이름으로 넘기는 경우를 위한 호환 파라미터"),
    query: Optional[str] = Query(None, description="treaty_id를 모를 때 사용할 검색어. 예: 미국, 일본, 소득"),
    language: str = Query("ko", description="본문 언어. ko=한글, en=영문"),
    chrClsCd: Optional[str] = Query(None, description="국가법령정보 API 조약 본문 언어 코드. 직접 지정 시 language보다 우선"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    """
    국가법령정보 조약 본문 조회.
    treaty_id가 있으면 바로 lawService.do?target=trty를 호출하고,
    treaty_id가 없고 query가 있으면 조약 목록 검색 후 best_treaty를 선택하여 본문을 조회합니다.
    """
    oc = require_law_oc()
    response_type_upper = response_type.upper()

    if response_type_upper not in ["JSON", "XML", "HTML"]:
        raise HTTPException(status_code=400, detail="response_type은 JSON, XML, HTML 중 하나여야 합니다.")

    selected_treaty = None
    selected_treaty_id = normalize_text(treaty_id or id)

    if not selected_treaty_id and query:
        search_params = {
            "OC": oc,
            "target": "trty",
            "type": "JSON",
            "query": query,
            "search": 1,
            "display": 10,
            "page": 1,
            "sort": "lasc",
        }

        search_res = call_law_api(LAW_SEARCH_URL, params=search_params)
        search_data = parse_law_response(search_res, "JSON")
        treaties = normalize_treaty_search_response(search_data)
        selected_treaty = find_first_treaty(treaties, query)

        if selected_treaty:
            selected_treaty_id = normalize_text(
                selected_treaty.get("treaty_id") or selected_treaty.get("mst")
            )

    if not selected_treaty_id:
        raise HTTPException(
            status_code=400,
            detail="treaty_id 또는 id를 입력하거나, query를 입력해 조약을 검색할 수 있게 하세요."
        )

    params = {
        "OC": oc,
        "target": "trty",
        "type": response_type_upper,
        "ID": selected_treaty_id,
        "chrClsCd": treaty_language_to_chr_cls_cd(language, chrClsCd),
    }

    res = call_law_api(LAW_SERVICE_URL, params=params)
    data = parse_law_response(res, response_type_upper)

    return {
        "treaty_id": selected_treaty_id,
        "selected_treaty": selected_treaty,
        "query": query,
        "language": language,
        "chrClsCd": params["chrClsCd"],
        "response_type": response_type_upper,
        "data": data,
        "note": (
            "국가법령정보 조약 본문 API 결과입니다. 제한세율·원천징수 적용 판단은 "
            "조약상 수익적 소유자 요건, 국내세법상 원천징수 규정, 거주자증명서, 실질귀속자, "
            "LOB 조항 및 관련 예규·판례를 함께 확인해야 합니다."
        ),
    }



# =========================================================
# TAX / CASE / INTERPRETATION helpers
# =========================================================

TAX_LAW_ALIASES = {
    # 법인세
    "법인세": "법인세법",
    "법인세법": "법인세법",
    "법인세법시행령": "법인세법 시행령",
    "법인세법시행규칙": "법인세법 시행규칙",

    # 소득세
    "소득세": "소득세법",
    "소득세법": "소득세법",
    "소득세법시행령": "소득세법 시행령",
    "소득세법시행규칙": "소득세법 시행규칙",

    # 부가가치세
    "부가세": "부가가치세법",
    "부가가치세": "부가가치세법",
    "부가가치세법": "부가가치세법",
    "부가가치세법시행령": "부가가치세법 시행령",
    "부가가치세법시행규칙": "부가가치세법 시행규칙",

    # 상속세 및 증여세
    "상증세": "상속세 및 증여세법",
    "상증세법": "상속세 및 증여세법",
    "상속세및증여세법": "상속세 및 증여세법",
    "상속세 및 증여세법": "상속세 및 증여세법",
    "상증령": "상속세 및 증여세법 시행령",
    "상속세및증여세법시행령": "상속세 및 증여세법 시행령",
    "상속세 및 증여세법 시행령": "상속세 및 증여세법 시행령",
    "상증칙": "상속세 및 증여세법 시행규칙",
    "상속세및증여세법시행규칙": "상속세 및 증여세법 시행규칙",
    "상속세 및 증여세법 시행규칙": "상속세 및 증여세법 시행규칙",

    # 조세특례제한법
    "조특법": "조세특례제한법",
    "조세특례제한법": "조세특례제한법",
    "조특령": "조세특례제한법 시행령",
    "조세특례제한법시행령": "조세특례제한법 시행령",
    "조세특례제한법 시행령": "조세특례제한법 시행령",
    "조특칙": "조세특례제한법 시행규칙",
    "조세특례제한법시행규칙": "조세특례제한법 시행규칙",
    "조세특례제한법 시행규칙": "조세특례제한법 시행규칙",

    # 국세기본법 / 국세징수법
    "국기법": "국세기본법",
    "국세기본법": "국세기본법",
    "국세기본법시행령": "국세기본법 시행령",
    "국세기본법 시행령": "국세기본법 시행령",

    "국징법": "국세징수법",
    "국세징수법": "국세징수법",
    "국세징수법시행령": "국세징수법 시행령",
    "국세징수법 시행령": "국세징수법 시행령",

    # 국제조세
    "국조법": "국제조세조정에 관한 법률",
    "국제조세조정법": "국제조세조정에 관한 법률",
    "국제조세조정에관한법률": "국제조세조정에 관한 법률",
    "국제조세조정에 관한 법률": "국제조세조정에 관한 법률",
    "국조령": "국제조세조정에 관한 법률 시행령",
    "국제조세조정에관한법률시행령": "국제조세조정에 관한 법률 시행령",
    "국제조세조정에 관한 법률 시행령": "국제조세조정에 관한 법률 시행령",

    # 지방세
    "지방세법": "지방세법",
    "지방세법시행령": "지방세법 시행령",
    "지방세법 시행령": "지방세법 시행령",
    "지방세기본법": "지방세기본법",
    "지방세징수법": "지방세징수법",

    # 기타 주요 세법
    "종부세법": "종합부동산세법",
    "종합부동산세법": "종합부동산세법",
    "증권거래세법": "증권거래세법",
    "인지세법": "인지세법",
    "개별소비세법": "개별소비세법",
    "주세법": "주세법",
    "교육세법": "교육세법",
    "농어촌특별세법": "농어촌특별세법",
    "관세법": "관세법",
    "관세법시행령": "관세법 시행령",
    "관세법 시행령": "관세법 시행령",
}


TAX_LAW_KEYWORDS = [
    "세법",
    "조세",
    "국세",
    "지방세",
    "법인세",
    "소득세",
    "부가가치세",
    "상속세",
    "증여세",
    "종합부동산세",
    "증권거래세",
    "인지세",
    "개별소비세",
    "주세",
    "교육세",
    "농어촌특별세",
    "관세",
]


TAX_LAW_TARGETS = {
    # 법령
    "current_law_by_enforcement_date": "eflaw",
    "law": "law",

    # 법령 부가/이력/비교
    # 국가법령정보 OPEN API target은 서비스별로 다르므로, 운영 중 API 응답을 보고 조정할 수 있게
    # 아래 target명을 한 곳에서 관리합니다.
    "law_history": "lsHst",
    "law_article_history_by_date": "lsJoHst",
    "law_article_history_by_article": "lsJoHst",
    "old_and_new": "oldAndNew",
    "three_way_compare": "threeWay",

    # 판례/심판례/해석/행정규칙/별표
    "case": "prec",
    "tax_appeal": "ttSpecialDecc",
    "nts_interpretation": "ntsCgmExpc",
    "customs_interpretation": "kcsCgmExpc",
    "legal_interpretation": "expc",
    "constitutional_case": "detc",
    "admin_rule": "admrul",
    "law_attachment": "licbyl",

    # 법령지식베이스
    "law_term": "lstrm",
    "related_law": "relatedLs",
}


def normalize_tax_law_key(value: str) -> str:
    """
    세법명/약칭 비교용 정규화.
    공백, 가운데점, 일부 특수문자를 제거합니다.
    """
    text = normalize_text(value)
    return (
        text.replace(" ", "")
        .replace("ㆍ", "")
        .replace("·", "")
        .replace(".", "")
        .replace(",", "")
        .replace("(", "")
        .replace(")", "")
    )


def resolve_tax_law_name(law_name: str) -> str:
    """
    사용자가 입력한 세법 약칭을 국가법령정보 법령명으로 변환합니다.
    예: 조특법 -> 조세특례제한법, 상증세법 -> 상속세 및 증여세법
    """
    key = normalize_tax_law_key(law_name)
    if key in TAX_LAW_ALIASES:
        return TAX_LAW_ALIASES[key]
    return normalize_text(law_name)


def is_tax_law_record(law: dict[str, Any]) -> bool:
    """
    국가법령정보 검색 결과 중 조세법령으로 볼 수 있는 항목만 필터링합니다.
    """
    law_name = normalize_text(law.get("law_name"))
    law_short_name = normalize_text(law.get("law_short_name"))
    target = f"{law_name} {law_short_name}"

    if any(keyword in target for keyword in TAX_LAW_KEYWORDS):
        return True

    normalized_target = normalize_tax_law_key(target)
    for alias_key, canonical_name in TAX_LAW_ALIASES.items():
        if alias_key in normalized_target:
            return True
        if normalize_tax_law_key(canonical_name) in normalized_target:
            return True

    return False


def search_law_items(
    query: str,
    search: int = 1,
    display: int = 10,
    page: int = 1,
    sort: str = "lasc",
    target: str = "law",
    extra_params: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """
    국가법령정보 lawSearch.do 호출용 내부 helper.
    기본 target은 law이지만 eflaw 등 법령계열 target도 호출할 수 있습니다.
    """
    oc = require_law_oc()

    params = {
        "OC": oc,
        "target": target,
        "type": "JSON",
        "query": query,
        "search": search,
        "display": display,
        "page": page,
        "sort": sort,
    }

    if extra_params:
        params.update(extra_params)

    res = call_law_api(LAW_SEARCH_URL, params=params)
    data = parse_law_response(res, "JSON")

    if target in ["law", "eflaw"]:
        return normalize_law_search_response(data)

    generic = normalize_generic_legal_search_response(data)
    return generic["items"]


def normalize_generic_legal_search_response(data: Any) -> dict[str, Any]:
    """
    판례, 심판례, 해석례, 행정규칙, 별표서식, 용어 등 목록 응답을
    GPT가 공통적으로 다룰 수 있도록 느슨하게 정규화합니다.
    """
    if not isinstance(data, dict):
        return {"total_count": None, "page": None, "items": [], "raw": data}

    root = data
    # LawSearch, PrecSearch 등 루트가 하나인 케이스를 흡수
    for key in [
        "LawSearch", "lawSearch",
        "PrecSearch", "precSearch",
        "DeccSearch", "deccSearch",
        "ExpcSearch", "expcSearch",
        "DetcSearch", "detcSearch",
        "AdmRulSearch", "admrulSearch",
        "LicBylSearch", "licbylSearch",
        "LsTrmSearch", "lstrmSearch",
        "Search", "search"
    ]:
        if isinstance(data.get(key), dict):
            root = data.get(key)
            break

    total_count = pick_first(root, "totalCnt", "totalCount", "총건수", "검색건수", "검색결과갯수")
    page = pick_first(root, "page", "페이지", "결과페이지번호", "출력페이지")

    items = find_first_list(
        root,
        preferred_keys=[
            "prec", "decc", "expc", "detc", "admrul", "licbyl", "lstrm",
            "law", "item", "items", "list", "data", "result", "results"
        ],
    )

    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue

        normalized.append({
            "id": pick_first(
                item,
                "판례일련번호", "판례정보일련번호",
                "특별행정심판재결례일련번호", "행정심판재결례일련번호",
                "법령해석일련번호", "헌재결정례일련번호",
                "행정규칙일련번호", "행정규칙ID",
                "별표일련번호", "관련법령일련번호",
                "법령용어ID", "용어ID",
                "ID", "id", "MST", "mst"
            ),
            "title": pick_first(
                item,
                "사건명", "안건명", "재결례명", "판례명", "헌재결정례명",
                "법령해석례명", "법령해석명",
                "행정규칙명", "별표명", "법령용어명", "용어명",
                "법령명한글", "법령명", "title", "name"
            ),
            "case_no": pick_first(item, "사건번호", "청구번호", "안건번호", "발령번호", "공포번호", "nb", "itmno"),
            "date": pick_first(
                item,
                "선고일자", "의결일자", "처분일자", "해석일자", "회신일자",
                "종국일자", "발령일자", "시행일자", "공포일자", "등록일자",
                "prncYd", "rslYd", "explYd", "edYd", "date"
            ),
            "court_or_authority": pick_first(
                item,
                "법원명", "처분청", "재결청", "질의기관명", "해석기관명", "회신기관명",
                "소관부처명", "데이터출처명", "authority"
            ),
            "category": pick_first(
                item,
                "사건종류명", "재결구분명", "재결례유형명", "세목",
                "행정규칙종류", "별표종류", "법령종류", "category"
            ),
            "detail_link": pick_first(
                item,
                "판례상세링크", "행정심판재결례상세링크", "법령해석례상세링크", "법령해석상세링크",
                "헌재결정례상세링크", "행정규칙상세링크", "별표법령상세링크", "상세링크",
                "detailLink", "detail_link"
            ),
            "file_link": pick_first(item, "별표서식파일링크", "별표서식PDF파일링크", "파일링크", "PDF파일링크"),
            "raw": item,
        })

    return {
        "total_count": total_count,
        "page": page,
        "count": len(normalized),
        "items": normalized,
        "raw": data,
    }


def call_law_search_target(
    target: str,
    query: str = "",
    search: Optional[int] = 1,
    display: int = 10,
    page: int = 1,
    sort: Optional[str] = None,
    response_type: str = "JSON",
    extra_params: Optional[dict[str, Any]] = None,
):
    """
    국가법령정보 lawSearch.do target별 프록시.
    """
    oc = require_law_oc()
    response_type_upper = response_type.upper()

    if response_type_upper not in ["JSON", "XML", "HTML"]:
        raise HTTPException(status_code=400, detail="response_type은 JSON, XML, HTML 중 하나여야 합니다.")

    params = {
        "OC": oc,
        "target": target,
        "type": response_type_upper,
        "query": query,
        "display": display,
        "page": page,
    }

    if search is not None:
        params["search"] = search
    if sort:
        params["sort"] = sort
    if extra_params:
        params.update(extra_params)

    res = call_law_api(LAW_SEARCH_URL, params=params)
    data = parse_law_response(res, response_type_upper)

    if response_type_upper == "JSON":
        normalized = normalize_generic_legal_search_response(data)
    else:
        normalized = None

    return {
        "target": target,
        "query": query,
        "search": search,
        "page": page,
        "display": display,
        "sort": sort,
        "response_type": response_type_upper,
        "normalized": normalized,
        "data": data,
    }


def call_law_service_target(
    target: str,
    item_id: Optional[str] = None,
    lm: Optional[str] = None,
    response_type: str = "JSON",
    extra_params: Optional[dict[str, Any]] = None,
):
    """
    국가법령정보 lawService.do target별 프록시.
    ID 또는 LM 중 하나를 사용합니다.
    """
    oc = require_law_oc()
    response_type_upper = response_type.upper()

    if response_type_upper not in ["JSON", "XML", "HTML"]:
        raise HTTPException(status_code=400, detail="response_type은 JSON, XML, HTML 중 하나여야 합니다.")

    if not item_id and not lm and not extra_params:
        raise HTTPException(status_code=400, detail="ID, LM 또는 추가 조회 파라미터 중 하나는 필요합니다.")

    params = {
        "OC": oc,
        "target": target,
        "type": response_type_upper,
    }

    if item_id:
        params["ID"] = item_id
    if lm:
        params["LM"] = lm
    if extra_params:
        params.update(extra_params)

    res = call_law_api(LAW_SERVICE_URL, params=params)
    data = parse_law_response(res, response_type_upper)

    return {
        "target": target,
        "id": item_id,
        "lm": lm,
        "response_type": response_type_upper,
        "params_used": {k: v for k, v in params.items() if k != "OC"},
        "data": data,
    }


def find_first_generic_item(normalized: Optional[dict[str, Any]], query: str = "") -> Optional[dict[str, Any]]:
    """
    normalize_generic_legal_search_response 결과에서 첫 번째 또는 제목 일치 항목 선택.
    """
    if not normalized:
        return None

    items = normalized.get("items") or []
    if not items:
        return None

    q = normalize_text(query).replace(" ", "")
    if not q:
        return items[0]

    for item in items:
        title = normalize_text(item.get("title")).replace(" ", "")
        if title == q:
            return item

    for item in items:
        title = normalize_text(item.get("title")).replace(" ", "")
        if q and q in title:
            return item

    return items[0]


# =========================================================
# TAX LAW endpoints
# =========================================================

@app.get("/tax/laws/catalog")
def tax_law_catalog():
    """
    GPT가 자주 쓰는 조세법령명/약칭 목록을 반환합니다.
    국가법령정보 API 호출 없이 서버 내부 alias 기준으로 반환합니다.
    """
    canonical_names = sorted(set(TAX_LAW_ALIASES.values()))

    return {
        "count": len(canonical_names),
        "tax_laws": canonical_names,
        "aliases": TAX_LAW_ALIASES,
        "note": (
            "This catalog is a server-side convenience list. "
            "Use /tax/laws/search or /tax/laws/article to verify current law metadata from the Korea Law Open API."
        )
    }


@app.get("/tax/laws/search")
def search_tax_laws(
    query: str = Query(..., description="검색어. 예: 법인세법, 조특법, 감가상각, 배당, 원천징수"),
    search: int = Query(1, description="검색범위. 1=법령명, 2=본문검색"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    sort: str = Query("lasc", description="정렬옵션. 예: lasc, ldes, dasc, ddes"),
    tax_only: bool = Query(True, description="True이면 조세법령으로 보이는 결과만 필터링")
):
    """
    조세법령 검색 전용 endpoint.
    내부적으로 국가법령정보 lawSearch.do?target=law 를 호출한 뒤,
    세법 관련 결과를 우선 정리합니다.
    """
    resolved_query = resolve_tax_law_name(query)

    laws = search_law_items(
        query=resolved_query,
        search=search,
        display=display,
        page=page,
        sort=sort,
        target="law",
    )

    filtered_laws = [law for law in laws if is_tax_law_record(law)] if tax_only else laws
    best_law = find_first_law(filtered_laws, resolved_query)

    return {
        "query": query,
        "resolved_query": resolved_query,
        "search": search,
        "page": page,
        "display": display,
        "tax_only": tax_only,
        "count": len(filtered_laws),
        "best_law": best_law,
        "laws": filtered_laws,
        "note": (
            "Tax law search uses the general Korea Law Open API target=law, "
            "then applies server-side tax law alias resolution and filtering."
        )
    }


@app.get("/tax/laws/article")
def get_tax_law_article(
    law_name: str = Query(..., description="세법명 또는 약칭. 예: 법인세법, 조특법, 상증세법"),
    article_no: str = Query(..., description="조문번호. 예: 18, 18-2, 제18조의2"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    """
    조세법령 조문 조회 전용 endpoint.
    세법 약칭을 먼저 정식 법령명으로 보정한 뒤 /law/article과 같은 방식으로 조회합니다.
    """
    oc = require_law_oc()
    response_type_upper = response_type.upper()

    if response_type_upper not in ["JSON", "XML", "HTML"]:
        raise HTTPException(status_code=400, detail="response_type은 JSON, XML, HTML 중 하나여야 합니다.")

    resolved_law_name = resolve_tax_law_name(law_name)

    laws = search_law_items(
        query=resolved_law_name,
        search=1,
        display=10,
        page=1,
        sort="lasc",
        target="law",
    )

    selected_law = find_first_law(laws, resolved_law_name)

    if not selected_law:
        raise HTTPException(status_code=404, detail=f"{law_name}에 해당하는 조세법령을 찾지 못했습니다.")

    law_id = selected_law.get("law_id")
    mst = selected_law.get("mst")

    if not law_id and not mst:
        raise HTTPException(status_code=502, detail="법령 검색 결과에 law_id 또는 mst가 포함되어 있지 않습니다.")

    jo = format_jo(article_no)

    params = {
        "OC": oc,
        "target": "law",
        "type": response_type_upper,
        "JO": jo,
    }

    if law_id:
        params["ID"] = law_id
    else:
        params["MST"] = mst

    res = call_law_api(LAW_SERVICE_URL, params=params)
    data = parse_law_response(res, response_type_upper)

    return {
        "input_law_name": law_name,
        "resolved_law_name": resolved_law_name,
        "law_name": selected_law.get("law_name"),
        "law_short_name": selected_law.get("law_short_name"),
        "law_id": law_id,
        "mst": mst,
        "law_type": selected_law.get("law_type"),
        "ministry": selected_law.get("ministry"),
        "promulgation_date": selected_law.get("promulgation_date"),
        "enforcement_date": selected_law.get("enforcement_date"),
        "article_no": article_no,
        "jo": jo,
        "response_type": response_type_upper,
        "data": data,
        "note": (
            "This endpoint resolves common Korean tax law aliases before article lookup. "
            "For related 시행령/시행규칙 provisions, use /tax/laws/package to identify related law IDs first."
        )
    }


@app.get("/tax/laws/package")
def get_tax_law_package(
    law_name: str = Query(..., description="세법명 또는 약칭. 예: 법인세법, 조특법, 상증세법")
):
    """
    특정 세법의 본법, 시행령, 시행규칙 검색 결과를 함께 반환합니다.
    조문번호는 법/시행령/시행규칙 간에 일치하지 않을 수 있으므로 여기서는 법령 메타데이터만 반환합니다.
    """
    resolved_law_name = resolve_tax_law_name(law_name)
    base_name = resolved_law_name.replace(" 시행령", "").replace(" 시행규칙", "")

    candidates = [
        base_name,
        f"{base_name} 시행령",
        f"{base_name} 시행규칙",
    ]

    results = []
    for candidate in candidates:
        laws = search_law_items(
            query=candidate,
            search=1,
            display=10,
            page=1,
            sort="lasc",
            target="law",
        )
        selected = find_first_law(laws, candidate)

        results.append({
            "query": candidate,
            "matched_law": selected,
            "candidate_count": len(laws),
            "candidates": laws[:5],
        })

    return {
        "input_law_name": law_name,
        "resolved_law_name": resolved_law_name,
        "base_law_name": base_name,
        "package": results,
        "note": (
            "This endpoint identifies the main tax law, enforcement decree, and enforcement rule. "
            "Do not assume the same article number applies across law/decree/rule."
        )
    }


@app.get("/tax/laws/effective-article")
def get_tax_law_effective_article(
    law_name: str = Query(..., description="세법명 또는 약칭. 예: 법인세법, 소득세법, 조특법"),
    article_no: str = Query(..., description="조문번호. 예: 18, 18-2, 제18조의2"),
    effective_date: str = Query(..., description="시행일 또는 검토 기준일 YYYYMMDD. 예: 20220101"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    """
    특정 시행일/기준일의 조세법령 조문 조회.
    먼저 target=eflaw 목록에서 해당 시행일 법령을 찾고, lawService.do에 efYd와 JO를 함께 전달합니다.
    """
    resolved_law_name = resolve_tax_law_name(law_name)

    laws = search_law_items(
        query=resolved_law_name,
        search=1,
        display=10,
        page=1,
        sort="lasc",
        target=TAX_LAW_TARGETS["current_law_by_enforcement_date"],
        extra_params={"efYd": effective_date},
    )

    selected_law = find_first_law(laws, resolved_law_name)
    if not selected_law:
        # eflaw에서 못 찾으면 일반 law 검색으로 fallback
        laws = search_law_items(query=resolved_law_name, search=1, display=10, page=1, sort="lasc", target="law")
        selected_law = find_first_law(laws, resolved_law_name)

    if not selected_law:
        raise HTTPException(status_code=404, detail=f"{law_name}에 해당하는 법령을 찾지 못했습니다.")

    law_id = selected_law.get("law_id")
    mst = selected_law.get("mst")
    jo = format_jo(article_no)

    extra_params = {
        "JO": jo,
        "efYd": effective_date,
    }
    if law_id:
        extra_params["ID"] = law_id
    elif mst:
        extra_params["MST"] = mst
    else:
        raise HTTPException(status_code=502, detail="법령 검색 결과에 law_id 또는 mst가 포함되어 있지 않습니다.")

    detail = call_law_service_target(
        target="law",
        response_type=response_type,
        extra_params=extra_params,
    )

    return {
        "input_law_name": law_name,
        "resolved_law_name": resolved_law_name,
        "effective_date": effective_date,
        "article_no": article_no,
        "jo": jo,
        "selected_law": selected_law,
        "detail": detail,
        "note": (
            "시행일 기준 조회는 API의 efYd 지원 여부와 법령별 연혁 데이터 상태에 따라 결과가 달라질 수 있습니다. "
            "세무 판단 시 거래일, 과세기간, 시행일, 부칙 적용 여부를 함께 확인하세요."
        ),
    }


@app.get("/tax/laws/history")
def search_tax_law_history(
    law_name: str = Query(..., description="세법명 또는 약칭. 예: 법인세법, 소득세법, 조특법"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    sort: str = Query("ddes", description="정렬옵션"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML"),
    target: Optional[str] = Query(None, description="필요 시 API target 직접 지정. 기본값은 lsHst")
):
    """
    세법 연혁 목록 조회용 endpoint.
    target명은 서비스 운영 중 법제처 응답에 맞춰 TAX_LAW_TARGETS['law_history']에서 조정할 수 있습니다.
    """
    resolved_law_name = resolve_tax_law_name(law_name)
    target_value = target or TAX_LAW_TARGETS["law_history"]

    return call_law_search_target(
        target=target_value,
        query=resolved_law_name,
        search=None,
        display=display,
        page=page,
        sort=sort,
        response_type=response_type,
    )


@app.get("/tax/laws/article-history")
def search_tax_law_article_history(
    law_name: str = Query(..., description="세법명 또는 약칭. 예: 법인세법, 조특법"),
    article_no: Optional[str] = Query(None, description="조문번호. 예: 18, 18-2"),
    start_date: Optional[str] = Query(None, description="검색 시작일 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="검색 종료일 YYYYMMDD"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    sort: str = Query("ddes", description="정렬옵션"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML"),
    target: Optional[str] = Query(None, description="필요 시 API target 직접 지정. 기본값은 lsJoHst")
):
    """
    조문 개정이력 조회용 endpoint.
    법제처 조문 개정이력 계열 API의 target/필드명이 환경별로 다를 수 있어 target 직접 지정 옵션을 둡니다.
    """
    resolved_law_name = resolve_tax_law_name(law_name)
    target_value = target or TAX_LAW_TARGETS["law_article_history_by_article"]

    extra_params = {}
    if article_no:
        extra_params["JO"] = format_jo(article_no)
    if start_date and end_date:
        extra_params["efYd"] = f"{start_date}~{end_date}"
    elif start_date:
        extra_params["efYd"] = start_date

    return call_law_search_target(
        target=target_value,
        query=resolved_law_name,
        search=None,
        display=display,
        page=page,
        sort=sort,
        response_type=response_type,
        extra_params=extra_params,
    )


@app.get("/tax/laws/compare")
def get_tax_law_old_and_new_compare(
    law_name: str = Query(..., description="세법명 또는 약칭. 예: 법인세법, 조특법"),
    law_id: Optional[str] = Query(None, description="법령ID. 없으면 법령명으로 검색 후 best law 사용"),
    mst: Optional[str] = Query(None, description="법령 마스터 번호"),
    promulgation_date: Optional[str] = Query(None, description="공포일자 LD YYYYMMDD"),
    promulgation_no: Optional[str] = Query(None, description="공포번호 LN"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML"),
    target: Optional[str] = Query(None, description="필요 시 API target 직접 지정. 기본값은 oldAndNew")
):
    """
    세법 신구법 비교 본문 조회.
    law_id 또는 mst가 없으면 현행 법령 검색으로 식별 후 oldAndNew service를 호출합니다.
    """
    resolved_law_name = resolve_tax_law_name(law_name)
    selected_law = None

    if not law_id and not mst:
        laws = search_law_items(query=resolved_law_name, search=1, display=10, page=1, sort="lasc", target="law")
        selected_law = find_first_law(laws, resolved_law_name)
        if selected_law:
            law_id = selected_law.get("law_id")
            mst = selected_law.get("mst")

    extra_params = {}
    if law_id:
        extra_params["ID"] = law_id
    if mst:
        extra_params["MST"] = mst
    if resolved_law_name:
        extra_params["LM"] = resolved_law_name
    if promulgation_date:
        extra_params["LD"] = promulgation_date
    if promulgation_no:
        extra_params["LN"] = promulgation_no

    return {
        "input_law_name": law_name,
        "resolved_law_name": resolved_law_name,
        "selected_law": selected_law,
        "compare": call_law_service_target(
            target=target or TAX_LAW_TARGETS["old_and_new"],
            response_type=response_type,
            extra_params=extra_params,
        ),
    }


@app.get("/tax/laws/three-way-compare")
def get_tax_law_three_way_compare(
    law_name: str = Query(..., description="세법명 또는 약칭. 예: 법인세법, 조특법"),
    law_id: Optional[str] = Query(None, description="법령ID. 없으면 법령명으로 검색 후 best law 사용"),
    mst: Optional[str] = Query(None, description="법령 마스터 번호"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML"),
    target: Optional[str] = Query(None, description="필요 시 API target 직접 지정. 기본값은 threeWay")
):
    """
    세법 3단 비교 본문 조회.
    target명은 서비스 운영 중 법제처 응답에 맞춰 TAX_LAW_TARGETS['three_way_compare']에서 조정할 수 있습니다.
    """
    resolved_law_name = resolve_tax_law_name(law_name)
    selected_law = None

    if not law_id and not mst:
        laws = search_law_items(query=resolved_law_name, search=1, display=10, page=1, sort="lasc", target="law")
        selected_law = find_first_law(laws, resolved_law_name)
        if selected_law:
            law_id = selected_law.get("law_id")
            mst = selected_law.get("mst")

    extra_params = {}
    if law_id:
        extra_params["ID"] = law_id
    if mst:
        extra_params["MST"] = mst
    if resolved_law_name:
        extra_params["LM"] = resolved_law_name

    return {
        "input_law_name": law_name,
        "resolved_law_name": resolved_law_name,
        "selected_law": selected_law,
        "three_way_compare": call_law_service_target(
            target=target or TAX_LAW_TARGETS["three_way_compare"],
            response_type=response_type,
            extra_params=extra_params,
        ),
    }


# =========================================================
# TAX CASE / APPEAL / INTERPRETATION endpoints
# =========================================================

@app.get("/tax/cases/search")
def search_tax_cases(
    query: str = Query("", description="검색어. 예: 명의신탁, 부가가치세, 실질과세"),
    search: int = Query(1, ge=1, le=2, description="검색범위. 1=판례명, 2=본문검색"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    org: Optional[str] = Query(None, description="법원종류. 대법원=400201, 하위법원=400202"),
    curt: Optional[str] = Query(None, description="법원명. 예: 대법원, 서울고등법원"),
    jo: Optional[str] = Query(None, alias="JO", description="참조법령명. 예: 법인세법, 부가가치세법"),
    date: Optional[str] = Query(None, description="선고일자 YYYYMMDD"),
    prncYd: Optional[str] = Query(None, description="선고일자 범위. 예: 20240101~20241231"),
    nb: Optional[str] = Query(None, description="사건번호"),
    datSrcNm: str = Query("국세법령정보시스템", description="데이터출처명. 예: 국세법령정보시스템, 대법원"),
    sort: str = Query("ddes", description="정렬옵션. ddes=선고일자 내림차순"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    extra_params = {
        "org": org,
        "curt": curt,
        "JO": jo,
        "date": date,
        "prncYd": prncYd,
        "nb": nb,
        "datSrcNm": datSrcNm,
    }

    return call_law_search_target(
        target=TAX_LAW_TARGETS["case"],
        query=query,
        search=search,
        display=display,
        page=page,
        sort=sort,
        response_type=response_type,
        extra_params=extra_params,
    )


@app.get("/tax/cases/detail")
def get_tax_case_detail(
    case_id: Optional[str] = Query(None, description="판례일련번호"),
    id: Optional[str] = Query(None, description="판례일련번호 호환 파라미터"),
    lm: Optional[str] = Query(None, description="판례명"),
    query: Optional[str] = Query(None, description="case_id를 모를 때 검색어로 먼저 검색"),
    response_type: str = Query("HTML", description="응답 형식: JSON, XML, HTML. 국세청 판례 본문은 HTML만 가능한 경우가 있습니다.")
):
    selected = None
    selected_id = normalize_text(case_id or id)

    if not selected_id and query:
        search_result = call_law_search_target(
            target=TAX_LAW_TARGETS["case"],
            query=query,
            search=1,
            display=5,
            page=1,
            sort="ddes",
            response_type="JSON",
            extra_params={"datSrcNm": "국세법령정보시스템"},
        )
        selected = find_first_generic_item(search_result.get("normalized"), query)
        if selected:
            selected_id = normalize_text(selected.get("id"))

    if not selected_id and not lm:
        raise HTTPException(status_code=400, detail="case_id/id, lm 또는 query 중 하나가 필요합니다.")

    return {
        "selected_item": selected,
        "detail": call_law_service_target(
            target=TAX_LAW_TARGETS["case"],
            item_id=selected_id,
            lm=lm,
            response_type=response_type,
        ),
        "note": "국세청 판례 본문 조회는 API 정책상 HTML만 가능한 경우가 있으므로 JSON 조회 실패 시 response_type=HTML로 재시도하세요."
    }


@app.get("/tax/appeals/search")
def search_tax_appeals(
    query: str = Query("", description="검색어. 예: 명의신탁, 가공세금계산서, 실질과세"),
    search: int = Query(1, ge=1, le=2, description="검색범위. 1=재결례명, 2=본문검색"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    cls: Optional[str] = Query(None, description="재결례유형 또는 재결구분코드"),
    date: Optional[str] = Query(None, description="의결일자 YYYYMMDD"),
    dpaYd: Optional[str] = Query(None, description="처분일자 범위. 예: 20240101~20241231"),
    rslYd: Optional[str] = Query(None, description="의결일자 범위. 예: 20240101~20241231"),
    sort: str = Query("ddes", description="정렬옵션. ddes=의결일자 내림차순"),
    fields: Optional[str] = Query(None, description="응답항목 옵션"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    extra_params = {
        "cls": cls,
        "date": date,
        "dpaYd": dpaYd,
        "rslYd": rslYd,
        "fields": fields,
    }

    return call_law_search_target(
        target=TAX_LAW_TARGETS["tax_appeal"],
        query=query,
        search=search,
        display=display,
        page=page,
        sort=sort,
        response_type=response_type,
        extra_params=extra_params,
    )


@app.get("/tax/appeals/detail")
def get_tax_appeal_detail(
    appeal_id: Optional[str] = Query(None, description="특별행정심판재결례일련번호"),
    id: Optional[str] = Query(None, description="특별행정심판재결례일련번호 호환 파라미터"),
    lm: Optional[str] = Query(None, description="특별행정심판재결례명"),
    query: Optional[str] = Query(None, description="appeal_id를 모를 때 검색어로 먼저 검색"),
    fields: Optional[str] = Query(None, description="응답항목 옵션"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    selected = None
    selected_id = normalize_text(appeal_id or id)

    if not selected_id and query:
        search_result = call_law_search_target(
            target=TAX_LAW_TARGETS["tax_appeal"],
            query=query,
            search=1,
            display=5,
            page=1,
            sort="ddes",
            response_type="JSON",
        )
        selected = find_first_generic_item(search_result.get("normalized"), query)
        if selected:
            selected_id = normalize_text(selected.get("id"))

    if not selected_id and not lm:
        raise HTTPException(status_code=400, detail="appeal_id/id, lm 또는 query 중 하나가 필요합니다.")

    return {
        "selected_item": selected,
        "detail": call_law_service_target(
            target=TAX_LAW_TARGETS["tax_appeal"],
            item_id=selected_id,
            lm=lm,
            response_type=response_type,
            extra_params={"fields": fields} if fields else None,
        ),
    }


@app.get("/tax/nts-interpretations/search")
def search_nts_interpretations(
    query: str = Query("", description="검색어. 예: 부당행위계산, 업무무관, 가업승계"),
    search: int = Query(1, ge=1, le=2, description="검색범위. 1=법령해석명, 2=본문검색"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    inq: Optional[int] = Query(None, description="질의기관코드"),
    rpl: Optional[int] = Query(None, description="해석기관코드"),
    itmno: Optional[int] = Query(None, description="안건번호. 입력 시 query는 무시될 수 있음"),
    explYd: Optional[str] = Query(None, description="해석일자 범위. 예: 20240101~20241231"),
    sort: str = Query("ddes", description="정렬옵션. ddes=해석일자 내림차순"),
    fields: Optional[str] = Query(None, description="응답항목 옵션"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    extra_params = {
        "inq": inq,
        "rpl": rpl,
        "itmno": itmno,
        "explYd": explYd,
        "fields": fields,
    }

    return {
        **call_law_search_target(
            target=TAX_LAW_TARGETS["nts_interpretation"],
            query=query,
            search=search,
            display=display,
            page=page,
            sort=sort,
            response_type=response_type,
            extra_params=extra_params,
        ),
        "note": "국세청 법령해석은 국가법령정보 API 가이드상 목록 조회 중심으로 제공됩니다. 본문은 결과의 상세링크 또는 국세법령정보시스템 원문 확인이 필요할 수 있습니다."
    }


@app.get("/tax/admin-rules/search")
def search_tax_admin_rules(
    query: str = Query("", description="검색어. 예: 국세청, 법인세, 사무처리규정"),
    search: int = Query(1, ge=1, le=2, description="검색범위. 1=행정규칙명, 2=본문검색"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    nw: int = Query(1, description="1=현행, 2=연혁"),
    org: Optional[str] = Query(None, description="소관부처 코드. 국세청/관세청 등 코드 확인 후 입력"),
    knd: Optional[str] = Query(None, description="1=훈령, 2=예규, 3=고시, 4=공고, 5=지침, 6=기타"),
    date: Optional[str] = Query(None, description="발령일자 YYYYMMDD"),
    prmlYd: Optional[str] = Query(None, description="발령일자 범위. 예: 20240101~20241231"),
    nb: Optional[str] = Query(None, description="발령번호"),
    sort: str = Query("ddes", description="정렬옵션. ddes=발령일자 내림차순"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    extra_params = {
        "nw": nw,
        "org": org,
        "knd": knd,
        "date": date,
        "prmlYd": prmlYd,
        "nb": nb,
    }

    return call_law_search_target(
        target=TAX_LAW_TARGETS["admin_rule"],
        query=query,
        search=search,
        display=display,
        page=page,
        sort=sort,
        response_type=response_type,
        extra_params=extra_params,
    )


@app.get("/tax/admin-rules/detail")
def get_tax_admin_rule_detail(
    rule_id: Optional[str] = Query(None, description="행정규칙 일련번호"),
    lid: Optional[str] = Query(None, description="행정규칙 ID"),
    lm: Optional[str] = Query(None, description="행정규칙명"),
    query: Optional[str] = Query(None, description="rule_id/lid를 모를 때 검색어로 먼저 검색"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    selected = None
    selected_id = normalize_text(rule_id)

    if not selected_id and not lid and query:
        search_result = call_law_search_target(
            target=TAX_LAW_TARGETS["admin_rule"],
            query=query,
            search=1,
            display=5,
            page=1,
            sort="ddes",
            response_type="JSON",
            extra_params={"nw": 1},
        )
        selected = find_first_generic_item(search_result.get("normalized"), query)
        if selected:
            selected_id = normalize_text(selected.get("id"))

    extra_params = {}
    if lid:
        extra_params["LID"] = lid

    if not selected_id and not lm and not extra_params:
        raise HTTPException(status_code=400, detail="rule_id, lid, lm 또는 query 중 하나가 필요합니다.")

    return {
        "selected_item": selected,
        "detail": call_law_service_target(
            target=TAX_LAW_TARGETS["admin_rule"],
            item_id=selected_id,
            lm=lm,
            response_type=response_type,
            extra_params=extra_params or None,
        ),
    }


@app.get("/tax/attachments/search")
def search_tax_attachments(
    query: str = Query("*", description="검색어. 예: 법인세법, 세액공제, 별지"),
    search: int = Query(1, ge=1, le=3, description="1=별표서식명, 2=해당법령검색, 3=별표본문검색"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    org: Optional[str] = Query(None, description="소관부처 코드"),
    mulOrg: Optional[str] = Query(None, description="소관부처 복수검색 조건 OR/AND"),
    knd: Optional[str] = Query(None, description="1=별표, 2=서식, 3=별지, 4=별도, 5=부록"),
    sort: str = Query("lasc", description="정렬옵션"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    extra_params = {
        "org": org,
        "mulOrg": mulOrg,
        "knd": knd,
    }

    return call_law_search_target(
        target=TAX_LAW_TARGETS["law_attachment"],
        query=query,
        search=search,
        display=display,
        page=page,
        sort=sort,
        response_type=response_type,
        extra_params=extra_params,
    )


# =========================================================
# GENERAL LEGAL INTERPRETATION / CONSTITUTIONAL CASE endpoints
# =========================================================

@app.get("/law/interpretations/search")
def search_legal_interpretations(
    query: str = Query("", description="검색어. 예: 과세, 부담금, 인허가"),
    search: int = Query(1, ge=1, le=2, description="검색범위. 1=법령해석례명, 2=본문검색"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    inq: Optional[int] = Query(None, description="질의기관코드"),
    rpl: Optional[int] = Query(None, description="회신기관코드"),
    itmno: Optional[int] = Query(None, description="안건번호"),
    regYd: Optional[str] = Query(None, description="등록일자 범위. 예: 20240101~20241231"),
    explYd: Optional[str] = Query(None, description="해석일자 범위. 예: 20240101~20241231"),
    sort: str = Query("ddes", description="정렬옵션. ddes=해석일자 내림차순"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    extra_params = {
        "inq": inq,
        "rpl": rpl,
        "itmno": itmno,
        "regYd": regYd,
        "explYd": explYd,
    }

    return call_law_search_target(
        target=TAX_LAW_TARGETS["legal_interpretation"],
        query=query,
        search=search,
        display=display,
        page=page,
        sort=sort,
        response_type=response_type,
        extra_params=extra_params,
    )


@app.get("/law/interpretations/detail")
def get_legal_interpretation_detail(
    interpretation_id: Optional[str] = Query(None, description="법령해석례일련번호"),
    id: Optional[str] = Query(None, description="법령해석례일련번호 호환 파라미터"),
    lm: Optional[str] = Query(None, description="법령해석례명"),
    query: Optional[str] = Query(None, description="ID를 모를 때 검색어로 먼저 검색"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML"),
    target: Optional[str] = Query(None, description="필요 시 target 직접 지정. 기본값은 expc")
):
    selected = None
    selected_id = normalize_text(interpretation_id or id)
    target_value = target or TAX_LAW_TARGETS["legal_interpretation"]

    if not selected_id and query:
        search_result = call_law_search_target(
            target=target_value,
            query=query,
            search=1,
            display=5,
            page=1,
            sort="ddes",
            response_type="JSON",
        )
        selected = find_first_generic_item(search_result.get("normalized"), query)
        if selected:
            selected_id = normalize_text(selected.get("id"))

    if not selected_id and not lm:
        raise HTTPException(status_code=400, detail="interpretation_id/id, lm 또는 query 중 하나가 필요합니다.")

    return {
        "selected_item": selected,
        "detail": call_law_service_target(
            target=target_value,
            item_id=selected_id,
            lm=lm,
            response_type=response_type,
        ),
    }


@app.get("/law/constitutional-cases/search")
def search_constitutional_cases(
    query: str = Query("", description="검색어. 예: 조세평등, 소급과세, 재산권"),
    search: int = Query(1, ge=1, le=2, description="검색범위. 1=헌재결정례명, 2=본문검색"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    date: Optional[str] = Query(None, description="종국일자 YYYYMMDD"),
    edYd: Optional[str] = Query(None, description="종국일자 범위. 예: 20240101~20241231"),
    nb: Optional[str] = Query(None, description="사건번호"),
    sort: str = Query("ddes", description="정렬옵션. ddes=선고/종국일자 내림차순"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    extra_params = {
        "date": date,
        "edYd": edYd,
        "nb": nb,
    }

    return call_law_search_target(
        target=TAX_LAW_TARGETS["constitutional_case"],
        query=query,
        search=search,
        display=display,
        page=page,
        sort=sort,
        response_type=response_type,
        extra_params=extra_params,
    )


@app.get("/law/constitutional-cases/detail")
def get_constitutional_case_detail(
    case_id: Optional[str] = Query(None, description="헌재결정례일련번호"),
    id: Optional[str] = Query(None, description="헌재결정례일련번호 호환 파라미터"),
    lm: Optional[str] = Query(None, description="헌재결정례명"),
    query: Optional[str] = Query(None, description="ID를 모를 때 검색어로 먼저 검색"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML"),
    target: Optional[str] = Query(None, description="필요 시 target 직접 지정. 기본값은 detc")
):
    selected = None
    selected_id = normalize_text(case_id or id)
    target_value = target or TAX_LAW_TARGETS["constitutional_case"]

    if not selected_id and query:
        search_result = call_law_search_target(
            target=target_value,
            query=query,
            search=1,
            display=5,
            page=1,
            sort="ddes",
            response_type="JSON",
        )
        selected = find_first_generic_item(search_result.get("normalized"), query)
        if selected:
            selected_id = normalize_text(selected.get("id"))

    if not selected_id and not lm:
        raise HTTPException(status_code=400, detail="case_id/id, lm 또는 query 중 하나가 필요합니다.")

    return {
        "selected_item": selected,
        "detail": call_law_service_target(
            target=target_value,
            item_id=selected_id,
            lm=lm,
            response_type=response_type,
        ),
    }


# =========================================================
# LAW TERM / RELATED LAW endpoints
# =========================================================

@app.get("/law/terms/search")
def search_law_terms(
    query: str = Query(..., description="법령용어 검색어. 예: 특수관계인, 거주자, 실질귀속"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    sort: str = Query("lasc", description="정렬옵션. lasc/ldes/rasc/rdes"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML"),
    target: Optional[str] = Query(None, description="필요 시 target 직접 지정. 기본값은 lstrm")
):
    return call_law_search_target(
        target=target or TAX_LAW_TARGETS["law_term"],
        query=query,
        search=None,
        display=display,
        page=page,
        sort=sort,
        response_type=response_type,
    )


@app.get("/law/terms/detail")
def get_law_term_detail(
    term_id: Optional[str] = Query(None, description="법령용어 ID"),
    id: Optional[str] = Query(None, description="법령용어 ID 호환 파라미터"),
    query: Optional[str] = Query(None, description="ID를 모를 때 용어명으로 먼저 검색"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML"),
    target: Optional[str] = Query(None, description="필요 시 target 직접 지정. 기본값은 lstrm")
):
    selected = None
    selected_id = normalize_text(term_id or id)
    target_value = target or TAX_LAW_TARGETS["law_term"]

    if not selected_id and query:
        search_result = call_law_search_target(
            target=target_value,
            query=query,
            search=None,
            display=5,
            page=1,
            sort="lasc",
            response_type="JSON",
        )
        selected = find_first_generic_item(search_result.get("normalized"), query)
        if selected:
            selected_id = normalize_text(selected.get("id"))

    if not selected_id:
        raise HTTPException(status_code=400, detail="term_id/id 또는 query 중 하나가 필요합니다.")

    return {
        "selected_item": selected,
        "detail": call_law_service_target(
            target=target_value,
            item_id=selected_id,
            response_type=response_type,
        ),
    }


@app.get("/tax/terms/search")
def search_tax_terms(
    query: str = Query(..., description="조세 관련 법령용어 검색어. 예: 특수관계인, 거주자, 실질귀속"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    sort: str = Query("lasc", description="정렬옵션. lasc/ldes/rasc/rdes"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    return call_law_search_target(
        target=TAX_LAW_TARGETS["law_term"],
        query=query,
        search=None,
        display=display,
        page=page,
        sort=sort,
        response_type=response_type,
    )


@app.get("/tax/terms/detail")
def get_tax_term_detail(
    term_id: Optional[str] = Query(None, description="법령용어 ID"),
    id: Optional[str] = Query(None, description="법령용어 ID 호환 파라미터"),
    query: Optional[str] = Query(None, description="ID를 모를 때 용어명으로 먼저 검색"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    selected = None
    selected_id = normalize_text(term_id or id)

    if not selected_id and query:
        search_result = call_law_search_target(
            target=TAX_LAW_TARGETS["law_term"],
            query=query,
            search=None,
            display=5,
            page=1,
            sort="lasc",
            response_type="JSON",
        )
        selected = find_first_generic_item(search_result.get("normalized"), query)
        if selected:
            selected_id = normalize_text(selected.get("id"))

    if not selected_id:
        raise HTTPException(status_code=400, detail="term_id/id 또는 query 중 하나가 필요합니다.")

    return {
        "selected_item": selected,
        "detail": call_law_service_target(
            target=TAX_LAW_TARGETS["law_term"],
            item_id=selected_id,
            response_type=response_type,
        ),
    }


@app.get("/law/related-laws/search")
def search_related_laws(
    law_name: Optional[str] = Query(None, description="법령명. 예: 법인세법"),
    law_id: Optional[str] = Query(None, description="법령ID"),
    mst: Optional[str] = Query(None, description="법령 마스터 번호"),
    query: Optional[str] = Query(None, description="검색어. law_name 대신 사용 가능"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML"),
    target: Optional[str] = Query(None, description="필요 시 target 직접 지정. 기본값은 relatedLs")
):
    """
    법령 간 관련법령 조회.
    법령정보 지식베이스의 관련법령 API target명은 운영 중 응답에 맞춰 TAX_LAW_TARGETS['related_law']에서 조정 가능합니다.
    """
    resolved_name = resolve_tax_law_name(law_name) if law_name else (query or "")

    extra_params = {}
    if law_id:
        extra_params["ID"] = law_id
    if mst:
        extra_params["MST"] = mst
    if resolved_name:
        extra_params["query"] = resolved_name

    return call_law_search_target(
        target=target or TAX_LAW_TARGETS["related_law"],
        query=resolved_name,
        search=None,
        display=display,
        page=page,
        sort=None,
        response_type=response_type,
        extra_params=extra_params,
    )


@app.get("/tax/related-laws/search")
def search_tax_related_laws(
    law_name: str = Query(..., description="세법명 또는 약칭. 예: 법인세법, 조특법, 상증세법"),
    law_id: Optional[str] = Query(None, description="법령ID"),
    mst: Optional[str] = Query(None, description="법령 마스터 번호"),
    display: int = Query(10, ge=1, le=100, description="검색 결과 수"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    response_type: str = Query("JSON", description="응답 형식: JSON, XML, HTML")
):
    resolved_name = resolve_tax_law_name(law_name)
    extra_params = {}
    if law_id:
        extra_params["ID"] = law_id
    if mst:
        extra_params["MST"] = mst
    if resolved_name:
        extra_params["query"] = resolved_name

    return call_law_search_target(
        target=TAX_LAW_TARGETS["related_law"],
        query=resolved_name,
        search=None,
        display=display,
        page=page,
        sort=None,
        response_type=response_type,
        extra_params=extra_params,
    )



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
