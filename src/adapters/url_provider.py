from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


class CsvUrlProvider:
    def __init__(self, path: Path):
        self.path = path
        self._total = 0
        self._count()

    def _count(self):
        try:
            with self.path.open() as f:
                self._total = sum(1 for _ in f) - 1
        except Exception:
            self._total = 0

    @property
    def total(self) -> int:
        return self._total

    def urls(self) -> Iterator[str]:
        with self.path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            first = next(reader, None)
            if first is None:
                return
            has_header = any("url" in c.lower() for c in first)
            col = 0
            if has_header:
                for i, h in enumerate(first):
                    if "url" in h.lower():
                        col = i
                        break
            else:
                yield first[col].strip() if first[col].strip() else ""
            for row in reader:
                if row and len(row) > col and row[col].strip():
                    yield row[col].strip()
