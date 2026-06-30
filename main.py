import os
import io
import zipfile
import requests
import xml.etree.ElementTree as ET
from functools import lru_cache
from fastapi import FastAPI, Query, HTTPException
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="DART GPT Action API",
    version="1.0.0",
    description="API server for connecting Custom GPT Actions to OpenDART."
)

DART_API_KEY = os.getenv("DART_API_KEY")


@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "DART GPT Action API is running."
    }


@app.get("/debug/env")
def debug_env():
    return {
        "has_dart_api_key": bool(DART_API_KEY),
        "api_key_length": len(DART_API_KEY) if DART_API_KEY else 0
    }


@lru_cache(maxsize=1)
def load_corp_codes():
    """
    OpenDART corpCode.xml을 다운로드하여
    회사명, 종목코드, DART 고유번호 목록을 캐싱합니다.
    """

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

    # 정상 응답은 ZIP 파일이어야 함
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
            companies.append({
                "corp_code": item.findtext("corp_code"),
                "corp_name": item.findtext("corp_name"),
                "stock_code": item.findtext("stock_code"),
                "modify_date": item.findtext("modify_date"),
            })

        return companies

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"corpCode.xml 파싱 실패: {str(e)}"
        )


def is_listed_company(company: dict) -> bool:
    """
    종목코드가 있으면 상장사로 간주합니다.
    """
    return bool((company.get("stock_code") or "").strip())


def find_best_company(company_name: str):
    """
    회사명 또는 종목코드 입력값을 기준으로 가장 적합한 회사를 선택합니다.

    우선순위:
    1. 종목코드 정확일치
    2. 회사명 정확일치 + 상장사
    3. 회사명 정확일치
    4. 회사명 부분일치 + 상장사
    5. 회사명 부분일치
    """

    companies = load_corp_codes()
    query = company_name.strip()

    # 1순위: 종목코드 정확일치
    stock_code_match = [
        c for c in companies
        if (c.get("stock_code") or "").strip() == query
    ]
    if stock_code_match:
        return stock_code_match[0]

    # 2순위: 회사명이 정확히 일치하고 종목코드가 있는 회사
    exact_listed = [
        c for c in companies
        if c.get("corp_name") == query and is_listed_company(c)
    ]
    if exact_listed:
        return exact_listed[0]

    # 3순위: 회사명이 정확히 일치하는 회사
    exact = [
        c for c in companies
        if c.get("corp_name") == query
    ]
    if exact:
        return exact[0]

    # 4순위: 회사명에 검색어가 포함되고 종목코드가 있는 회사
    partial_listed = [
        c for c in companies
        if query in (c.get("corp_name") or "") and is_listed_company(c)
    ]
    if partial_listed:
        return partial_listed[0]

    # 5순위: 회사명에 검색어가 포함되는 회사
    partial = [
        c for c in companies
        if query in (c.get("corp_name") or "")
    ]
    if partial:
        return partial[0]

    return None


def sort_company_results(results: list, query: str) -> list:
    """
    검색 결과를 GPT가 헷갈리지 않도록 정렬합니다.

    정렬 우선순위:
    1. 종목코드 정확일치
    2. 회사명 정확일치 + 상장사
    3. 회사명 정확일치
    4. 상장사
    5. 회사명 가나다순
    """

    query_clean = query.strip()

    return sorted(
        results,
        key=lambda c: (
            not ((c.get("stock_code") or "").strip() == query_clean),
            not (c.get("corp_name") == query_clean and is_listed_company(c)),
            not (c.get("corp_name") == query_clean),
            not is_listed_company(c),
            c.get("corp_name") or ""
        )
    )


@app.get("/dart/search-company")
def search_company(
    query: str = Query(..., description="회사명 또는 종목코드. 예: 삼성전자, 005930")
):
    companies = load_corp_codes()
    query_clean = query.strip()

    results = []
    for c in companies:
        corp_name = c.get("corp_name") or ""
        stock_code = c.get("stock_code") or ""

        if query_clean in corp_name or query_clean == stock_code:
            results.append(c)

    sorted_results = sort_company_results(results, query_clean)

    best_company = find_best_company(query_clean)

    return {
        "query": query,
        "count": len(sorted_results),
        "best_company": best_company,
        "results": sorted_results[:20]
    }


@app.get("/dart/disclosures")
def get_disclosures(
    company_name: str = Query(..., description="회사명 또는 종목코드. 예: 삼성전자, 005930"),
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
            "stock_code": item.get("stock_code"),
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
        "disclosures": disclosures
    }


@app.get("/dart/financials")
def get_financials(
    company_name: str = Query(..., description="회사명 또는 종목코드. 예: 삼성전자, 005930"),
    year: str = Query(..., description="사업연도. 예: 2025"),
    report_code: str = Query(..., description="보고서 코드: 11011 사업보고서, 11012 반기, 11013 1분기, 11014 3분기")
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
        "accounts": accounts
    }
