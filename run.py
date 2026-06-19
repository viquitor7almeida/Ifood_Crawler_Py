from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from src.adapters.flaresolverr_client import FlaresolverrClient
from src.adapters.parser import ProductParser
from src.adapters.persistence import SqlitePersistence
from src.adapters.simple_http_client import SimpleHttpClient
from src.adapters.url_provider import CsvUrlProvider
from src.core.orchestrator import CrawlerOrchestrator, TokenBucketRateLimiter
from src.infra.cookie_store import CookieStore
from src.infra.logging_config import configure_logging
from src.infra.metrics import MetricsCollector

try:
    from rich.console import Console
    from rich.progress import (
        BarColumn, Progress, SpinnerColumn, TextColumn,
        TimeElapsedColumn, TimeRemainingColumn,
    )
    from rich.panel import Panel
    from rich.table import Table
    from rich.layout import Layout
    from rich.live import Live
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


logger = logging.getLogger(__name__)


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def warmup(cookie_store: CookieStore, flaresolverr: FlaresolverrClient, first_url: str) -> bool:
    if cookie_store.cookies:
        logger.info("CookieStore has %d cookies — skipping warmup", len(cookie_store.cookies))
        return True
    logger.info("Warmup: getting cookies via Flaresolverr for %s ...", first_url)
    for i in range(1, 11):
        logger.info("Warmup attempt %d/10", i)
        result = flaresolverr.fetch(first_url)
        if result and result.success:
            logger.info("Warmup OK on attempt %d! Cookies: %d", i, len(cookie_store.cookies))
            return True
        if cookie_store.cookies:
            logger.info("Warmup: cookies obtained on attempt %d", i)
            return True
        if i < 10:
            logger.warning("Warmup attempt %d failed — waiting 10s...", i)
            import time
            time.sleep(10)
    logger.warning("Warmup exhausted 10 attempts without cookies")
    return False


def main():
    configure_logging()

    parallelism = _env_int("CRAWLER_PARALLELISM", 5)
    max_retries = _env_int("CRAWLER_MAX_RETRIES", 5)
    flaresolverr_url = _env("CRAWLER_FLARESOLVERR_URL", "http://flaresolverr:8191")
    flaresolverr_timeout = _env_int("CRAWLER_FLARESOLVERR_TIMEOUT", 180)
    input_file = Path(_env("CRAWLER_INPUT_FILE", "/app/data/ifood_urls_padrao_item_1000.csv"))
    output_dir = Path(_env("CRAWLER_OUTPUT_DIR", "/app/output"))
    checkpoint_db = Path(_env("CRAWLER_CHECKPOINT_DB_PATH", "/app/checkpoints/checkpoint.db"))
    cookie_path = Path(_env("CRAWLER_COOKIE_STORE_PATH", "/app/cookies/cookies.json"))

    logger.info("=" * 50)
    logger.info("  iFood Crawler Python")
    logger.info("  parallelism=%d  maxRetries=%d  flaresolverr=%s",
                parallelism, max_retries, flaresolverr_url)
    logger.info("=" * 50)

    cookie_store = CookieStore(cookie_path)
    url_provider = CsvUrlProvider(input_file)
    persistence = SqlitePersistence(checkpoint_db)
    parser = ProductParser()
    metrics = MetricsCollector(report_path=output_dir / "execution_report.txt")

    flaresolverr = FlaresolverrClient(flaresolverr_url, flaresolverr_timeout, cookie_store)
    simple_http = SimpleHttpClient()
    crawlers = [flaresolverr, simple_http]

    logger.info("Priming Flaresolverr browser...")
    flaresolverr.prime()
    logger.info("Prime complete")

    url_provider = CsvUrlProvider(input_file)

    rate_limiter = TokenBucketRateLimiter(capacity=parallelism * 2, refill_per_second=parallelism * 2)
    orchestrator = CrawlerOrchestrator(
        url_provider=url_provider,
        crawlers=crawlers,
        parser=parser,
        persistence=persistence,
        cookie_store=cookie_store,
        metrics=metrics,
        parallelism=parallelism,
        max_retries=max_retries,
        rate_limiter=rate_limiter,
        checkpoint_interval=50,
    )

    # ── Rich Live Progress ─────────────────────────────────
    if HAS_RICH:
        console = Console()
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("<"),
            TimeRemainingColumn(),
            console=console,
            expand=True,
        )

        task_id = progress.add_task(
            "[cyan]Crawling iFood products...", total=url_provider.total,
        )

        class ProgressUpdater:
            def __init__(self, progress, task_id):
                self.progress = progress
                self.task_id = task_id
                self.last_ok = 0
                self.last_fail = 0

            def update(self):
                ok = orchestrator._success
                fail = orchestrator._errors
                done = ok + fail
                if done > self.progress.tasks[self.task_id].completed:
                    self.progress.update(self.task_id, completed=done)
                    if ok > self.last_ok:
                        self.progress.console.log(
                            f"[green]OK[/green] {url or ''}  "
                            f"[dim]({ok}+{fail})[/dim]"
                        )
                    self.last_ok, self.last_fail = ok, fail

        updater = ProgressUpdater(progress, task_id)

        def monitoring_thread():
            while not orchestrator._shutdown and (
                progress.tasks[task_id].completed < progress.tasks[task_id].total
            ):
                updater.update()
                import time
                time.sleep(0.5)

        import threading as _threading
        monitor = _threading.Thread(target=monitoring_thread, daemon=True)
        progress.start()
        monitor.start()

        summary = orchestrator.run()

        progress.stop()

        total = url_provider.total
        table = Table(title="Execution Summary", show_header=False, border_style="cyan")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")
        table.add_row("Total URLs", str(total))
        table.add_row("Processed", str(summary.processed))
        table.add_row("Success", f"[green]{summary.success}[/green]")
        table.add_row("Errors", f"[red]{summary.errors}[/red]")
        table.add_row("Success Rate", f"[bold]{summary.success_rate:.1f}%[/bold]")
        table.add_row("Duration", summary._fmt_duration(summary.total_duration_s))
        table.add_row("Avg/URL", f"{summary.avg_duration_ms:.0f}ms")
        table.add_row("P95", f"{metrics.p95_duration_ms:.0f}ms")
        if metrics.crawler_stats:
            for name, stats in metrics.crawler_stats.items():
                rate = (stats["success"] / stats["total"] * 100) if stats["total"] else 0
                table.add_row(f"Crawler: {name}", f"{stats['total']} calls, {stats['success']} OK, {stats['error']} fail ({rate:.1f}%)")

        console.print(Panel(table, title="[bold]iFood Crawler Results[/bold]", border_style="green"))

        print()
        print(metrics.generate_report())

    else:
        summary = orchestrator.run()
        print(summary.formatted())

    print(metrics.generate_report())


if __name__ == "__main__":
    main()
