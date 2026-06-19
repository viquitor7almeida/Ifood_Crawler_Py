from __future__ import annotations

import logging
import random
import signal
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from src.core.models import CrawlResult, ExecutionSummary, FetchedPage, ProductData
from src.infra.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from src.infra.metrics import CrawlerMetrics, MetricsCollector
from src.infra.cookie_store import CookieStore

logger = logging.getLogger(__name__)


class TokenBucketRateLimiter:
    def __init__(self, capacity: int, refill_per_second: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_per_second
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now
            if self.tokens < 1:
                sleep_time = (1 - self.tokens) / self.refill_rate
                time.sleep(sleep_time)
                self.tokens = 0
            else:
                self.tokens -= 1


class CrawlerOrchestrator:
    def __init__(
        self,
        url_provider,
        crawlers: list,
        parser,
        persistence,
        cookie_store: CookieStore,
        metrics: MetricsCollector,
        parallelism: int = 5,
        max_retries: int = 3,
        rate_limiter: Optional[TokenBucketRateLimiter] = None,
        checkpoint_interval: int = 50,
    ):
        self.url_provider = url_provider
        self.crawlers = crawlers
        self.parser = parser
        self.persistence = persistence
        self.cookie_store = cookie_store
        self.metrics = metrics
        self.parallelism = parallelism
        self.max_retries = max_retries
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter(parallelism * 2, parallelism * 2)
        self.checkpoint_interval = checkpoint_interval

        self._lock = threading.Lock()
        self._success = 0
        self._errors = 0
        self._processed = 0
        self._processed_since_checkpoint = 0
        self._shutdown = False
        self._recording = False

        for c in self.crawlers:
            if not hasattr(c, 'circuit_breaker') or c.circuit_breaker is None:
                c.circuit_breaker = CircuitBreaker(
                    name=c.name,
                    failure_threshold=10,
                    recovery_timeout=120.0,
                    half_open_max_calls=2,
                )

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        sig_name = signal.Signals(signum).name
        logger.warning("Received %s — initiating graceful shutdown...", sig_name)
        self.shutdown()

    def run(self) -> ExecutionSummary:
        start = datetime.now(timezone.utc)
        total = self.url_provider.total
        logger.info(
            "Starting crawler: %d URLs, %d workers, %d retries, crawlers: %s",
            total, self.parallelism, self.max_retries,
            [c.name for c in self.crawlers],
        )

        skipped = self._count_skipped()
        if skipped:
            logger.info("Checkpoint: %d URLs already processed, skipping", skipped)

        threads = []
        url_iter = iter(self.url_provider.urls())

        for _ in range(self.parallelism):
            t = threading.Thread(target=self._worker_loop, args=(url_iter,), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        end = datetime.now(timezone.utc)
        duration_s = (end - start).total_seconds()

        with self._lock:
            succ, err, recovered = self._success, self._errors, self._recording

        self._export_results()

        summary = ExecutionSummary(
            total_urls=total,
            processed=succ + err + skipped,
            success=succ,
            errors=err,
            total_duration_s=duration_s,
            start_time=start.isoformat(),
            end_time=end.isoformat(),
            avg_duration_ms=self.metrics.avg_duration_ms,
            min_duration_ms=self.metrics.min_duration_ms,
            max_duration_ms=self.metrics.max_duration_ms,
            recovered_count=self.metrics.recovered_count,
            crawler_stats=self.metrics.crawler_stats,
        )
        logger.info(summary.formatted())
        return summary

    def _count_skipped(self) -> int:
        count = 0
        for url in self.url_provider.urls():
            if self.persistence.is_processed(url):
                count += 1
        return count

    def _export_results(self):
        base = self.persistence.db_path.parent.parent / "output"
        try:
            self.persistence.export_csv(base / "results.csv")
            self.persistence.export_json(base / "results.json")
            report_path = base / "execution_report.txt"
            self.metrics.generate_report(report_path)
        except Exception as e:
            logger.error("Export failed: %s", e)

    def _worker_loop(self, url_iter):
        for url in url_iter:
            if self._shutdown:
                break
            with self._lock:
                if self.persistence.is_processed(url):
                    self._processed += 1
                    continue
            self._process_url(url)

    def _process_url(self, url: str):
        start_ms = time.monotonic() * 1000
        last_error: Optional[str] = None

        for attempt in range(1, self.max_retries + 1):
            if self._shutdown:
                return

            self.rate_limiter.acquire()
            page = self._fetch_with_fallback(url, attempt)

            if page and page.success:
                product = self.parser.parse(page.html, url)
                # retry if parser couldn't extract product data
                if product.is_empty:
                    last_error = f"Attempt {attempt}: parse returned empty (page={len(page.html)}b)"
                    if attempt < self.max_retries:
                        logger.warning("Empty parse on %s, retrying (%d/%d)", url, attempt, self.max_retries)
                        continue
                elapsed_ms = int(time.monotonic() * 1000 - start_ms)
                result = CrawlResult.success(
                    url=url, product=product,
                    attempt=attempt, duration_ms=elapsed_ms,
                    recovered=(attempt > 1),
                )
                self.persistence.save(result)
                crawler_name = page.source
                self.metrics.record(CrawlerMetrics(
                    url=url, crawler=crawler_name,
                    success=True, duration_ms=elapsed_ms,
                    attempt=attempt, recovered=(attempt > 1),
                ))
                with self._lock:
                    self._success += 1
                    self._processed += 1
                    if attempt > 1:
                        self._recording = True
                    self._checkpoint_if_needed()
                return

            last_error = f"Attempt {attempt} failed"
            if page:
                last_error = f"HTTP {page.status_code} | CF blocked={page.cloudflare_blocked}"

            if page and page.cloudflare_blocked and attempt < self.max_retries:
                backoff = min(1000 * (2 ** (attempt - 1)) + random.randint(0, 500), 30000)
                logger.warning("Cloudflare on %s, backoff %dms (attempt %d)", url, backoff, attempt)
                time.sleep(backoff / 1000)

        elapsed_ms = int(time.monotonic() * 1000 - start_ms)
        result = CrawlResult.error(
            url=url, error_message=last_error or "Unknown error",
            attempt=self.max_retries, duration_ms=elapsed_ms,
        )
        self.persistence.save(result)
        self.metrics.record(CrawlerMetrics(
            url=url, crawler="all_failed",
            success=False, duration_ms=elapsed_ms,
            attempt=self.max_retries, recovered=False,
        ))
        with self._lock:
            self._errors += 1
            self._processed += 1
            self._checkpoint_if_needed()
        logger.error("URL FAILED: %s (%d attempts, %dms)", url, self.max_retries, elapsed_ms)

    def _fetch_with_fallback(self, url: str, attempt: int) -> Optional[FetchedPage]:
        for crawler in self.crawlers:
            if self._shutdown:
                return None
            cb: CircuitBreaker = getattr(crawler, 'circuit_breaker', None)
            if cb and cb.state.name == "OPEN":
                logger.debug("Skipping '%s' (circuit open) for %s", crawler.name, url)
                continue
            try:
                if cb:
                    result = cb.call(crawler.fetch, url)
                else:
                    result = crawler.fetch(url)
                if result and result.success:
                    return result
                if result:
                    logger.warning(
                        "'%s' HTTP %d for %s", crawler.name, result.status_code, url,
                    )
                else:
                    logger.warning("'%s' returned None for %s", crawler.name, url)
            except CircuitBreakerOpenError:
                logger.debug("Circuit open for '%s', skipping", crawler.name)
            except Exception as e:
                logger.warning("'%s' exception for %s: %s", crawler.name, url, e)
        logger.warning("All crawlers failed for %s", url)
        return None

    def _checkpoint_if_needed(self):
        self._processed_since_checkpoint += 1
        if self._processed_since_checkpoint >= self.checkpoint_interval:
            self._processed_since_checkpoint = 0
            total = self._success + self._errors
            rate = (self._success / total * 100) if total else 0
            logger.info(
                "CHECKPOINT: %d processed, %d ok, %d fail (%.1f%%)",
                self._processed, self._success, self._errors, rate,
            )

    def shutdown(self):
        self._shutdown = True
        logger.info("Shutdown requested — finishing current URLs...")
