import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.adapters.flaresolverr_client import FlaresolverrClient
from src.adapters.simple_http_client import SimpleHttpClient
from src.adapters.url_provider import CsvUrlProvider
from src.core.models import FetchedPage, ProductData, CrawlResult
from src.core.orchestrator import CrawlerOrchestrator, TokenBucketRateLimiter
from src.infra.cookie_store import CookieStore, StoredCookie
from src.infra.metrics import MetricsCollector
from src.infra.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState


def test_token_bucket_acquire():
    limiter = TokenBucketRateLimiter(capacity=10, refill_per_second=100)
    for _ in range(10):
        limiter.acquire()


def test_url_provider_csv(tmp_path):
    csv_file = tmp_path / "urls.csv"
    csv_file.write_text("url\nhttps://a.com\nhttps://b.com\n")
    provider = CsvUrlProvider(csv_file)
    assert provider.total == 2
    urls = list(provider.urls())
    assert urls == ["https://a.com", "https://b.com"]


def test_url_provider_no_header(tmp_path):
    csv_file = tmp_path / "urls.csv"
    csv_file.write_text("https://a.com\nhttps://b.com\n")
    provider = CsvUrlProvider(csv_file)
    urls = list(provider.urls())
    assert len(urls) == 2


def test_simple_http_success():
    client = SimpleHttpClient(timeout_s=5)
    with patch.object(client.session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>OK</body></html>"
        mock_resp.url = "https://test.com"
        mock_resp.elapsed.total_seconds.return_value = 0.5
        mock_get.return_value = mock_resp
        result = client.fetch("https://test.com")
        assert result is not None
        assert result.success


def _empty_store(tmp_path):
    return CookieStore(tmp_path / "cookies.json")


def test_flaresolverr_success(tmp_path):
    store = _empty_store(tmp_path)
    client = FlaresolverrClient("http://localhost:8191", 10, store)
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.elapsed.total_seconds.return_value = 2.0
        mock_resp.json.return_value = {
            "status": "ok",
            "solution": {
                "response": "<html><body>Resolved</body></html>",
                "status": 200,
                "cookies": [{"name": "cf_clearance", "value": "abc", "domain": ".ifood.com.br", "path": "/"}],
            },
        }
        mock_post.return_value = mock_resp
        result = client.fetch("https://ifood.com.br/produto")
        assert result is not None
        assert result.success
        assert "Resolved" in result.html
        assert store.cookies[0].name == "cf_clearance"


def test_flaresolverr_http_error(tmp_path):
    store = _empty_store(tmp_path)
    client = FlaresolverrClient("http://localhost:8191", 10, store)
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_post.return_value = mock_resp
        result = client.fetch("https://ifood.com.br")
        assert result is None


def test_flaresolverr_timeout(tmp_path):
    store = _empty_store(tmp_path)
    client = FlaresolverrClient("http://localhost:8191", 10, store)
    with patch("requests.post") as mock_post:
        mock_post.side_effect = TimeoutError()
        result = client.fetch("https://ifood.com.br")
        assert result is None


def test_crawl_result_output_dict():
    product = ProductData(title="X-Burger", normal_price=29.90, discount_price=19.90, image_url="https://img.com/x.jpg")
    result = CrawlResult.success(url="https://ifood.com.br/x", product=product, attempt=1, duration_ms=100)
    d = result.to_output_dict()
    assert d["title"] == "X-Burger"
    assert d["normal_price"] == "R$ 29,90"
    assert d["discount_price"] == "R$ 19,90"
    assert d["product_url"] == "https://ifood.com.br/x"
    assert d["image_url"] == "https://img.com/x.jpg"
    assert d["status"] == "success"
    assert d["error_message"] is None


def test_crawl_result_error_output_dict():
    result = CrawlResult.error(url="https://ifood.com.br/fail", error_message="Timeout", attempt=3, duration_ms=5000)
    d = result.to_output_dict()
    assert d["title"] is None
    assert d["status"] == "error"
    assert d["error_message"] == "Timeout"


def test_circuit_breaker_tripping():
    cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=1)
    assert cb.state == CircuitState.CLOSED
    for _ in range(3):
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))
        except Exception:
            pass
    assert cb.state == CircuitState.OPEN


def test_circuit_breaker_recovery():
    cb = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout=0.1, half_open_max_calls=1)
    for _ in range(2):
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))
        except Exception:
            pass
    assert cb.state == CircuitState.OPEN
    import time
    time.sleep(0.15)
    cb.call(lambda: "ok")
    assert cb.state == CircuitState.CLOSED


def test_orchestrator_retry_then_success(tmp_path):
    csv_file = tmp_path / "urls.csv"
    csv_file.write_text("url\nhttps://test.com\n")

    cookie_store = CookieStore(tmp_path / "cookies.json")
    provider = CsvUrlProvider(csv_file)
    persistence = MagicMock()
    persistence.is_processed.return_value = False
    persistence.db_path.parent.parent = tmp_path

    parser = MagicMock()
    parser.parse.return_value = ProductData(title="Test", normal_price=10.0)

    mock_crawler = MagicMock()
    mock_crawler.name = "mock"
    mock_crawler.circuit_breaker = None
    mock_crawler.fetch.side_effect = [None, None, None, FetchedPage("https://test.com", "<html>OK</html>", 200, "mock")]

    metrics = MetricsCollector()
    orch = CrawlerOrchestrator(
        url_provider=provider,
        crawlers=[mock_crawler],
        parser=parser,
        persistence=persistence,
        cookie_store=cookie_store,
        metrics=metrics,
        parallelism=1,
        max_retries=5,
        rate_limiter=TokenBucketRateLimiter(100, 1000),
    )
    orch.run()
    assert orch._success == 1
    assert orch._errors == 0


def test_orchestrator_all_fail(tmp_path):
    csv_file = tmp_path / "urls.csv"
    csv_file.write_text("url\nhttps://test.com\n")

    cookie_store = CookieStore(tmp_path / "cookies.json")
    provider = CsvUrlProvider(csv_file)
    persistence = MagicMock()
    persistence.is_processed.return_value = False
    persistence.db_path.parent.parent = tmp_path

    parser = MagicMock()

    mock_crawler = MagicMock()
    mock_crawler.name = "mock"
    mock_crawler.circuit_breaker = None
    mock_crawler.fetch.return_value = None

    metrics = MetricsCollector()
    orch = CrawlerOrchestrator(
        url_provider=provider,
        crawlers=[mock_crawler],
        parser=parser,
        persistence=persistence,
        cookie_store=cookie_store,
        metrics=metrics,
        parallelism=1,
        max_retries=3,
        rate_limiter=TokenBucketRateLimiter(100, 1000),
    )
    orch.run()
    assert orch._success == 0
    assert orch._errors == 1
