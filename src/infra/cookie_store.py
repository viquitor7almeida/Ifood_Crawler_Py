from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class StoredCookie:
    name: str
    value: str
    domain: str
    path: str = "/"


class CookieStore:
    def __init__(self, path: Path):
        self.path = path
        self._cookies: list[StoredCookie] = []
        self._load()

    @property
    def cookies(self) -> list[StoredCookie]:
        return list(self._cookies)

    def update(self, new_cookies: list[StoredCookie]):
        if not new_cookies:
            return
        for c in new_cookies:
            self._cookies = [x for x in self._cookies if not (x.name == c.name and x.domain == c.domain)]
            self._cookies.append(c)
        self._save()
        logger.info("CookieStore: %d cookies salvos em %s", len(self._cookies), self.path)

    def clear(self):
        self._cookies.clear()
        self._save()

    def to_dict_list(self) -> list[dict]:
        return [asdict(c) for c in self._cookies]

    def _load(self):
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
            self._cookies = [StoredCookie(**c) for c in raw]
            logger.info("CookieStore: %d cookies carregados de %s", len(self._cookies), self.path)
        except Exception as e:
            logger.warning("CookieStore: erro ao carregar %s: %s", self.path, e)

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps([asdict(c) for c in self._cookies], indent=2))
        except Exception as e:
            logger.warning("CookieStore: erro ao salvar %s: %s", self.path, e)
