import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from mcp_bridge import TOOL_SPECS, install_mcp


@pytest.fixture(scope="module")
def client():
    app = FastAPI()

    @app.get("/")
    def root():
        return {"status": "ok"}

    @app.get("/dart/search-company")
    def search(query: str):
        return {"query": query, "source": "DART"}

    @app.post("/nts/business-status")
    def business_status(payload: dict):
        return {"received": payload}

    @app.get("/tax/laws/article")
    def law_article(law_name: str, article_no: str, response_type: str = "JSON"):
        raise HTTPException(502, detail="upstream?serviceKey=secret&OC=private-user")

    install_mcp(app)
    with TestClient(app, base_url="http://localhost") as http:
        yield http


def rpc(client, method, params=None):
    response = client.post(
        "/mcp",
        headers={"Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_initialize_and_original_rest(client):
    result = rpc(client, "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "kcpas-tests", "version": "1.0.0"},
    })
    assert result["result"]["serverInfo"]["name"] == "gpt-for-k-cpas"
    assert client.get("/").json() == {"status": "ok"}


def test_discovery_is_exactly_the_52_lookup_tools(client):
    tools = rpc(client, "tools/list")["result"]["tools"]
    assert len(tools) == 52
    assert {t["name"] for t in tools} == {s["name"] for s in TOOL_SPECS}
    assert all(t["annotations"]["readOnlyHint"] for t in tools)
    assert all(t["inputSchema"]["additionalProperties"] is False for t in tools)
    assert not any("debug" in s["path"] or "raw" in s["path"] for s in TOOL_SPECS)


def test_query_arguments_and_structured_result(client):
    result = rpc(client, "tools/call", {"name": "searchCompany", "arguments": {"query": "삼성전자"}})["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == {"query": "삼성전자", "source": "DART"}


def test_post_body_is_forwarded_without_changing_shape(client):
    args = {"business_numbers": ["220-81-62517", "1248100998"]}
    result = rpc(client, "tools/call", {"name": "getBusinessRegistrationStatus", "arguments": args})["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["received"] == args


@pytest.mark.parametrize("arguments", [{}, {"query": "삼성전자", "url": "http://other.test"}, {"query": 123}])
def test_invalid_inputs_are_rejected(client, arguments):
    result = rpc(client, "tools/call", {"name": "searchCompany", "arguments": arguments})["result"]
    assert result["isError"] is True


def test_unknown_tool_is_not_dispatched(client):
    result = rpc(client, "tools/call", {"name": "debug_env", "arguments": {}})["result"]
    assert result["isError"] is True


def test_upstream_failure_is_an_error_and_redacts_keys(client):
    result = rpc(client, "tools/call", {
        "name": "getTaxLawArticle", "arguments": {"law_name": "법인세법", "article_no": "18-2"},
    })["result"]
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "502" in text and "[redacted]" in text
    assert "secret" not in text and "private-user" not in text


def test_untrusted_host_is_rejected(client):
    response = client.post("/mcp", headers={"Host": "untrusted.example", "Accept": "application/json, text/event-stream"},
                           json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 421


def test_all_tool_paths_and_parameter_names_match_existing_rest():
    from main import app
    paths = app.openapi()["paths"]
    for item in TOOL_SPECS:
        operation = paths[item["path"]][item["method"].lower()]
        if item["body"]:
            assert "requestBody" in operation
        else:
            names = {p["name"] for p in operation.get("parameters", []) if p["in"] == "query"}
            assert set(item["query_parameters"]) <= names, item["name"]
