from src.core.models import (
    ProductData, CrawlResult, ExecutionSummary, FetchedPage, _format_brl,
)


def test_format_brl():
    assert _format_brl(29.90) == "R$ 29,90"
    assert _format_brl(1234.56) == "R$ 1.234,56"
    assert _format_brl(0.0) == "R$ 0,00"
    assert _format_brl(None) is None


def test_fetched_page_success():
    page = FetchedPage(url="https://test.com", html="<html>OK</html>", status_code=200)
    assert page.success is True
    assert page.cloudflare_blocked is False


def test_fetched_page_cloudflare():
    page = FetchedPage(url="https://test.com", html="cf-browser-verification", status_code=200)
    assert page.success is False
    assert page.cloudflare_blocked is True


def test_fetched_page_empty_html():
    page = FetchedPage(url="https://test.com", html="", status_code=200)
    assert page.success is False


def test_product_data_empty():
    p = ProductData.empty()
    assert p.is_empty
    assert p.title is None


def test_crawl_result_success():
    product = ProductData(title="X-Burger", normal_price=29.90)
    result = CrawlResult.success(url="https://t.com", product=product, attempt=1, duration_ms=100)
    assert result.status == "success"
    assert result.error_message is None


def test_crawl_result_error():
    result = CrawlResult.error(url="https://t.com", error_message="Not found", attempt=3, duration_ms=5000)
    assert result.status == "error"
    assert result.error_message == "Not found"
    assert result.product.is_empty


def test_execution_summary_rate():
    s = ExecutionSummary(
        total_urls=1000, processed=963, success=950, errors=13,
        total_duration_s=600.0, start_time="", end_time="",
    )
    assert round(s.success_rate, 2) == 98.65  # 950/963 * 100


def test_execution_summary_zero_processed():
    s = ExecutionSummary(
        total_urls=0, processed=0, success=0, errors=0,
        total_duration_s=0.0, start_time="", end_time="",
    )
    assert s.success_rate == 0.0


def test_crawl_result_output_dict_complete():
    product = ProductData(
        title="Coca 2L", normal_price=9.90, discount_price=7.90,
        image_url="https://img.com/coca.jpg",
    )
    result = CrawlResult.success(url="https://ifood.com.br/coca", product=product, attempt=1, duration_ms=100)
    d = result.to_output_dict()
    assert d == {
        "title": "Coca 2L",
        "normal_price": "R$ 9,90",
        "discount_price": "R$ 7,90",
        "product_url": "https://ifood.com.br/coca",
        "image_url": "https://img.com/coca.jpg",
        "status": "success",
        "error_message": None,
    }


def test_crawl_result_output_dict_error():
    result = CrawlResult.error(url="https://ifood.com.br/fail", error_message="Timeout", attempt=3, duration_ms=5000)
    d = result.to_output_dict()
    assert d["status"] == "error"
    assert d["error_message"] == "Timeout"
    assert d["title"] is None
    assert d["normal_price"] is None
    assert d["discount_price"] is None
