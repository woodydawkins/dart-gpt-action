import os
import io
import zipfile
import requests
import xml.etree.ElementTree as ET
from functools import lru_cache
from fastapi import FastAPI, Query
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="DART GPT Action API",
    version="1.0.0",
    description="API server for connecting Custom GPT Actions to OpenDART."
)

DART_API_KEY = os.getenv("DART_API_KEY")


@lru_cache(maxsize=1)
def load_corp_codes():
    """
    OpenDART corpCode.xml을 다운로드하여 회사명/종목코드/corp_code 목록을 캐싱합니다.
    """
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    params = {"crtfc_key": DART_API_KEY}

    res = requests.get(url, params=params, timeout=30)
    res.raise_for_status()

    z = zipfile.ZipFile(io.BytesIO(res.content))
    xml_file = z.open(z.namelist()[0])

    tree = ET.parse(xml_file)
    root = tree.getroot()

    companies = []
    for item in root.findall("list"):
        companies.append({
            "corp_code": item.findtext("corp_code"),
            "corp_name": item.findtext("corp_name"),
            "stock_code": item.findtext("stock_code"),
            "modify_date": item.findtext("modify_date"),
        })

    return companies


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

    return {
        "query": query,
        "count": len(results),
        "results": results[:20]
    }


@app.get("/dart/disclosures")
def get_disclosures(
    company_name: str = Query(..., description="회사명. 예: 삼성전자"),
    start_date: str = Query(..., description="조회 시작일 YYYYMMDD"),
    end_date: str = Query(..., description="조회 종료일 YYYYMMDD"),
    page_count: int = Query(30, description="조회 건수")
):
    companies = load_corp_codes()

    matched = [
        c for c in companies
        if c.get("corp_name") == company_name or company_name in c.get("corp_name", "")
    ]

    if not matched:
        return {
            "error": "company_not_found",
            "message": f"{company_name}에 해당하는 회사를 찾지 못했습니다."
        }

    company = matched[0]
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

    res = requests.get(url, params=params, timeout=30)
    data = res.json()

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
    company_name: str = Query(..., description="회사명. 예: 삼성전자"),
    year: str = Query(..., description="사업연도. 예: 2025"),
    report_code: str = Query(..., description="보고서 코드: 11011 사업보고서, 11012 반기, 11013 1분기, 11014 3분기")
):
    companies = load_corp_codes()

    matched = [
        c for c in companies
        if c.get("corp_name") == company_name or company_name in c.get("corp_name", "")
    ]

    if not matched:
        return {
            "error": "company_not_found",
            "message": f"{company_name}에 해당하는 회사를 찾지 못했습니다."
        }

    company = matched[0]
    corp_code = company["corp_code"]

    url = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": year,
        "reprt_code": report_code,
    }

    res = requests.get(url, params=params, timeout=30)
    data = res.json()

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
