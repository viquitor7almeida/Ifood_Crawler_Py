from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CrawlerMetrics:
    url: str
    crawler: str
    success: bool
    duration_ms: float
    attempt: int
    recovered: bool
    timestamp: float = field(default_factory=time.monotonic)


class MetricsCollector:
    def __init__(self, report_path: Optional[Path] = None):
        self._lock = threading.Lock()
        self._records: list[CrawlerMetrics] = []
        self._start_time = time.monotonic()
        self._wall_start = datetime.now(timezone.utc)
        self._crawler_counts: dict[str, dict[str, int]] = {}
        self._report_path = report_path

    def record(self, metric: CrawlerMetrics):
        with self._lock:
            self._records.append(metric)
            crawler = metric.crawler
            if crawler not in self._crawler_counts:
                self._crawler_counts[crawler] = {"success": 0, "error": 0, "total": 0}
            self._crawler_counts[crawler]["total"] += 1
            if metric.success:
                self._crawler_counts[crawler]["success"] += 1
            else:
                self._crawler_counts[crawler]["error"] += 1

    @property
    def total(self) -> int:
        return len(self._records)

    @property
    def successes(self) -> int:
        return sum(1 for r in self._records if r.success)

    @property
    def errors(self) -> int:
        return sum(1 for r in self._records if not r.success)

    @property
    def recovered_count(self) -> int:
        return sum(1 for r in self._records if r.recovered)

    @property
    def success_rate(self) -> float:
        return (self.successes / self.total * 100) if self.total > 0 else 0.0

    @property
    def avg_duration_ms(self) -> float:
        if not self._records:
            return 0.0
        return statistics.mean(r.duration_ms for r in self._records)

    @property
    def median_duration_ms(self) -> float:
        if not self._records:
            return 0.0
        return statistics.median(r.duration_ms for r in self._records)

    @property
    def p95_duration_ms(self) -> float:
        if not self._records:
            return 0.0
        durations = sorted(r.duration_ms for r in self._records)
        idx = int(len(durations) * 0.95)
        return durations[min(idx, len(durations) - 1)]

    @property
    def min_duration_ms(self) -> float:
        if not self._records:
            return 0.0
        return min(r.duration_ms for r in self._records)

    @property
    def max_duration_ms(self) -> float:
        if not self._records:
            return 0.0
        return max(r.duration_ms for r in self._records)

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self._start_time

    @property
    def crawler_stats(self) -> dict:
        return dict(self._crawler_counts)

    def summary(self) -> dict:
        return {
            "total_urls": self.total,
            "success": self.successes,
            "errors": self.errors,
            "success_rate": round(self.success_rate, 1),
            "recovered": self.recovered_count,
            "avg_duration_ms": round(self.avg_duration_ms, 1),
            "median_duration_ms": round(self.median_duration_ms, 1),
            "p95_duration_ms": round(self.p95_duration_ms, 1),
            "min_duration_ms": round(self.min_duration_ms, 1),
            "max_duration_ms": round(self.max_duration_ms, 1),
            "total_duration_s": round(self.elapsed_s, 1),
            "start_time": self._wall_start.isoformat(),
            "crawler_stats": self.crawler_stats,
        }

    def generate_report(self, path: Optional[Path] = None) -> str:
        output_path = path or self._report_path
        report = self.summary()
        text = (
            f"\n{'='*60}\n"
            f"  RELATORIO DE EXECUCAO\n"
            f"{'='*60}\n"
            f"  Total URLs:       {report['total_urls']}\n"
            f"  Sucesso:          {report['success']}\n"
            f"  Erros:            {report['errors']}\n"
            f"  Taxa sucesso:     {report['success_rate']}%\n"
            f"  Recuperadas:      {report['recovered']}\n"
            f"  Duracao total:    {report['total_duration_s']}s\n"
            f"  Media/URL:        {report['avg_duration_ms']}ms\n"
            f"  Mediana:          {report['median_duration_ms']}ms\n"
            f"  P95:              {report['p95_duration_ms']}ms\n"
            f"  Mais rapida:      {report['min_duration_ms']}ms\n"
            f"  Mais lenta:       {report['max_duration_ms']}ms\n"
        )
        if report["crawler_stats"]:
            text += f"  {'─'*58}\n  Crawlers:\n"
            for name, stats in report["crawler_stats"].items():
                rate = (stats["success"] / stats["total"] * 100) if stats["total"] else 0
                text += f"    {name:20s}  {stats['total']:4d} calls  "
                text += f"{stats['success']:4d} OK  {stats['error']:4d} fail  {rate:5.1f}%\n"
        text += f"{'='*60}\n"

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(text)
            logger.info("Report saved to %s", output_path)

        return text
