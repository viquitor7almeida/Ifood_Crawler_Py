from __future__ import annotations

import csv
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.core.models import CrawlResult, ProductData

logger = logging.getLogger(__name__)


class SqlitePersistence:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crawl_results (
                    url TEXT PRIMARY KEY,
                    title TEXT,
                    normal_price REAL,
                    discount_price REAL,
                    image_url TEXT,
                    status TEXT DEFAULT 'success',
                    error_message TEXT,
                    attempt INTEGER,
                    duration_ms INTEGER,
                    recovered INTEGER,
                    timestamp TEXT
                )
            """)
            conn.commit()

    def is_processed(self, url: str) -> bool:
        with self._lock, sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT 1 FROM crawl_results WHERE url = ? AND status = 'success'",
                (url,),
            ).fetchone()
            return row is not None

    def is_any_record(self, url: str) -> bool:
        with self._lock, sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT 1 FROM crawl_results WHERE url = ?", (url,),
            ).fetchone()
            return row is not None

    def save(self, result: CrawlResult):
        with self._lock, sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO crawl_results
                (url, title, normal_price, discount_price, image_url,
                 status, error_message, attempt, duration_ms, recovered, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result.url,
                result.product.title,
                result.product.normal_price,
                result.product.discount_price,
                result.product.image_url,
                result.status,
                result.error_message,
                result.attempt,
                result.duration_ms,
                1 if result.recovered else 0,
                result.timestamp,
            ))
            conn.commit()

    def get_all(self) -> list[CrawlResult]:
        with self._lock, sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT * FROM crawl_results").fetchall()
            results = []
            for r in rows:
                product = ProductData(
                    title=r[1], normal_price=r[2],
                    discount_price=r[3], image_url=r[4],
                )
                results.append(CrawlResult(
                    url=r[0],
                    product=product,
                    status=r[5],
                    error_message=r[6],
                    attempt=r[7],
                    duration_ms=r[8],
                    recovered=bool(r[9]),
                    timestamp=r[10],
                ))
            return results

    def get_stats(self) -> dict:
        with self._lock, sqlite3.connect(str(self.db_path)) as conn:
            total = conn.execute("SELECT COUNT(*) FROM crawl_results").fetchone()[0]
            success = conn.execute(
                "SELECT COUNT(*) FROM crawl_results WHERE status = 'success'",
            ).fetchone()[0]
            errors = conn.execute(
                "SELECT COUNT(*) FROM crawl_results WHERE status = 'error'",
            ).fetchone()[0]
            durations = conn.execute(
                "SELECT duration_ms FROM crawl_results",
            ).fetchall()
            avg_dur = sum(d[0] for d in durations) / len(durations) if durations else 0
            min_dur = min(d[0] for d in durations) if durations else 0
            max_dur = max(d[0] for d in durations) if durations else 0
            return {
                "total": total,
                "success": success,
                "errors": errors,
                "avg_duration_ms": avg_dur,
                "min_duration_ms": min_dur,
                "max_duration_ms": max_dur,
            }

    def export_csv(self, path: Path):
        results = self.get_all()
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "title", "normal_price", "discount_price",
            "product_url", "image_url", "status", "error_message",
        ]
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for r in results:
                writer.writerow(r.to_output_dict())
        logger.info("Exported %d records to %s", len(results), path)

    def export_json(self, path: Path):
        results = self.get_all()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [r.to_output_dict() for r in results]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info("Exported %d records to %s", len(results), path)
