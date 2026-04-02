from __future__ import annotations
import logging
import os
import httpx

logger = logging.getLogger(__name__)

EZPROXY_LOGIN_URL = "https://login.liboff.ohsu.edu/login"


class EZProxySession:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def authenticate(self) -> bool:
        username = os.environ.get("OHSU_USERNAME", "")
        password = os.environ.get("OHSU_PASSWORD", "")
        if not username or not password:
            logger.warning("OHSU_USERNAME or OHSU_PASSWORD not set; skipping EZproxy")
            return False
        try:
            response = await self._client.post(
                EZPROXY_LOGIN_URL,
                data={"user": username, "pass": password},
                follow_redirects=False,
            )
            if response.status_code != 302:
                logger.warning(f"EZproxy auth failed: HTTP {response.status_code}")
                return False
            return True
        except Exception as e:
            logger.warning(f"EZproxy auth error: {e}")
            return False

    async def get_pdf(self, doi: str) -> bytes | None:
        url = f"{EZPROXY_LOGIN_URL}?url=https://doi.org/{doi}"
        try:
            response = await self._client.get(url, follow_redirects=True)
            content = response.content
            if not content.startswith(b"%PDF"):
                return None
            return content
        except Exception as e:
            logger.warning(f"EZproxy get_pdf error for doi={doi}: {e}")
            return None
