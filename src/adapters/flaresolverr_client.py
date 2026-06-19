from __future__ import annotations

import json
import logging
from typing import Optional

import requests

from src.core.models import FetchedPage
from src.infra.cookie_store import CookieStore

logger = logging.getLogger(__name__)


class FlaresolverrClient:
    def __init__(self, base_url: str, timeout_s: int = 180, cookie_store: Optional[CookieStore] = None):
        self.api_url = base_url.rstrip("/") + "/v1"
        self.timeout_s = timeout_s
        self.cookie_store = cookie_store or CookieStore.__new__(CookieStore)
        self.circuit_breaker = None  # set by orchestrator

    @property
    def name(self) -> str:
        return "flaresolverr"

    def prime(self) -> None:
        """warm up the Flaresolverr browser with a throwaway request (non-iFood)."""
        try:
            payload = {"cmd": "request.get", "url": "https://example.com", "maxTimeout": 30000}
            requests.post(self.api_url, json=payload, timeout=40)
        except Exception:
            pass

    def fetch(self, url: str) -> Optional[FetchedPage]:
        return self._request(url)

    def _request(self, url: str) -> Optional[FetchedPage]:
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": self.timeout_s * 1000,
        }

        try:
            resp = requests.post(
                self.api_url,
                json=payload,
                timeout=self.timeout_s + 10,
            )
            elapsed_ms = int(resp.elapsed.total_seconds() * 1000)

            if resp.status_code != 200:
                logger.warning("Flaresolverr HTTP %d para %s (%dms)", resp.status_code, url, elapsed_ms)
                return None

            data = resp.json()
            if data.get("status") != "ok":
                msg = data.get("message", "")
                logger.warning("Flaresolverr erro: %s para %s (%dms)", msg, url, elapsed_ms)
                return None

            solution = data.get("solution", {})
            html = solution.get("response", "")
            status = solution.get("status", 200)

            if not html or not html.strip():
                logger.warning("Flaresolverr HTML vazio para %s (%dms)", url, elapsed_ms)
                return None

            cookies_raw = solution.get("cookies")
            if cookies_raw:
                from src.infra.cookie_store import StoredCookie
                parsed = []
                for c in cookies_raw:
                    name = c.get("name", "")
                    value = c.get("value", "")
                    domain = c.get("domain", "")
                    path = c.get("path", "/")
                    if name and value:
                        parsed.append(StoredCookie(name=name, value=value, domain=domain, path=path))
                self.cookie_store.update(parsed)

            logger.info("Flaresolverr OK %s (%dms, %db)", url, elapsed_ms, len(html))
            return FetchedPage(url=url, html=html, status_code=status, source="flaresolverr")

        except requests.Timeout:
            logger.warning("Flaresolverr timeout %ds para %s", self.timeout_s, url)
            return None
        except Exception as e:
            logger.warning("Flaresolverr exception para %s: %s", url, e)
            return None
