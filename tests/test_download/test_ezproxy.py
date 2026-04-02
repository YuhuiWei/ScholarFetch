from __future__ import annotations
import httpx
import pytest
import respx
from nexus_paper_fetcher.download.ezproxy import EZProxySession, EZPROXY_LOGIN_URL
from tests.test_download.constants import FAKE_PDF, FAKE_HTML


@pytest.fixture
def with_credentials(monkeypatch):
    monkeypatch.setenv("OHSU_USERNAME", "testuser")
    monkeypatch.setenv("OHSU_PASSWORD", "testpass")


@respx.mock
async def test_authenticate_success(with_credentials):
    respx.post(EZPROXY_LOGIN_URL).mock(return_value=httpx.Response(302))
    async with httpx.AsyncClient() as client:
        ez = EZProxySession(client)
        assert await ez.authenticate() is True


@respx.mock
async def test_authenticate_failure_401(with_credentials):
    respx.post(EZPROXY_LOGIN_URL).mock(return_value=httpx.Response(401))
    async with httpx.AsyncClient() as client:
        ez = EZProxySession(client)
        assert await ez.authenticate() is False


async def test_authenticate_missing_credentials(monkeypatch):
    monkeypatch.delenv("OHSU_USERNAME", raising=False)
    monkeypatch.delenv("OHSU_PASSWORD", raising=False)
    async with httpx.AsyncClient() as client:
        ez = EZProxySession(client)
        assert await ez.authenticate() is False


@respx.mock
async def test_get_pdf_returns_bytes(with_credentials):
    respx.get("https://login.liboff.ohsu.edu/login?url=https://doi.org/10.1234/test.paper").mock(
        return_value=httpx.Response(200, content=FAKE_PDF)
    )
    async with httpx.AsyncClient() as client:
        ez = EZProxySession(client)
        result = await ez.get_pdf("10.1234/test.paper")
    assert result == FAKE_PDF


@respx.mock
async def test_get_pdf_returns_none_for_html(with_credentials):
    respx.get("https://login.liboff.ohsu.edu/login?url=https://doi.org/10.1234/test.paper").mock(
        return_value=httpx.Response(200, content=FAKE_HTML)
    )
    async with httpx.AsyncClient() as client:
        ez = EZProxySession(client)
        result = await ez.get_pdf("10.1234/test.paper")
    assert result is None


@respx.mock
async def test_get_pdf_request_exception_returns_none(with_credentials):
    respx.get("https://login.liboff.ohsu.edu/login?url=https://doi.org/10.1234/test.paper").mock(
        side_effect=httpx.ConnectError("network error")
    )
    async with httpx.AsyncClient() as client:
        ez = EZProxySession(client)
        result = await ez.get_pdf("10.1234/test.paper")
    assert result is None
