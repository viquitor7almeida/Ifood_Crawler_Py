from __future__ import annotations

import logging
from typing import Optional

import requests

from src.core.models import FetchedPage

logger = logging.getLogger(__name__)


class SimpleHttpClient:
    def __init__(self, timeout_s: int = 60):
        self.timeout_s = timeout_s
        self.circuit_breaker = None  # set by orchestrator
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        })

    @property
    def name(self) -> str:
        return "simple-http"

    def fetch(self, url: str) -> Optional[FetchedPage]:
        try:
            resp = self.session.get(url, timeout=self.timeout_s, allow_redirects=True)
            elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
            page = FetchedPage(url=str(resp.url), html=resp.text, status_code=resp.status_code, source="simple-http")
            if page.success:
                logger.info("SimpleHttp OK %s (%dms, %db)", url, elapsed_ms, len(resp.text))
                return page
            logger.warning("SimpleHttp HTTP %d para %s (%dms)", resp.status_code, url, elapsed_ms)
            return page
        except Exception as e:
            logger.warning("SimpleHttp exception para %s: %s", url, e)
            return None
