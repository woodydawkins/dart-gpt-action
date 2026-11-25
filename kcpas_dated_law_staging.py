"""Isolated Render entry point. Exposes no application or provider data."""
from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, HTTPException
from starlette.concurrency import run_in_threadpool

from main import get_tax_law_effective_article


def check_provider():
    results = {}
    for case, article, date, expected in (
        ("baseline", "55", "20230101", "247467"),
        ("historical", "55", "20221231", "237497"),
        ("phased", "163-3", "20230701", "247467"),
    ):
        results[case] = {}
        for fmt in ("JSON", "XML", "HTML"):
            try:
                result = get_tax_law_effective_article("소득세법", article, date, fmt)
                actual = str(result.get("selected_law", {}).get("mst", ""))
                outcome = "verified" if actual == expected else "unexpected_version"
            except HTTPException as exc:
                outcome = f"rejected_{exc.status_code}"
            except Exception:
                outcome = "unexpected_error"
            results[case][fmt] = outcome
    return results


@asynccontextmanager
async def lifespan(app):
    if not os.getenv("LAW_OC", "").strip():
        app.state.checks = {"status": "awaiting_test_provider_configuration"}
    else:
        app.state.checks = {"status": "complete", "cases": await run_in_threadpool(check_provider)}
    yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/checks")
def checks():
    return app.state.checks
