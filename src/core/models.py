from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


def _format_brl(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    int_part, frac_part = f"{value:.2f}".split(".")
    int_part = "{:,}".format(int(int_part)).replace(",", ".")
    return f"R$ {int_part},{frac_part}"


@dataclass
class FetchedPage:
    url: str
    html: str
    status_code: int = 200
    source: str = "unknown"

    @property
    def success(self) -> bool:
        return self.status_code == 200 and len(self.html) > 0 and not self._cloudflare_blocked

    @property
    def _cloudflare_blocked(self) -> bool:
        return (
            "cf-browser-verification" in self.html
            or "challenge-platform" in self.html
            or "__cf_chl_f_tk" in self.html
            or "Attention Required" in self.html
            or "Just a moment" in self.html
        )

    @property
    def cloudflare_blocked(self) -> bool:
        return self._cloudflare_blocked


@dataclass
class ProductData:
    title: Optional[str] = None
    normal_price: Optional[float] = None
    discount_price: Optional[float] = None
    image_url: Optional[str] = None

    @classmethod
    def empty(cls) -> ProductData:
        return cls()

    @property
    def is_empty(self) -> bool:
        return self.title is None


@dataclass
class CrawlResult:
    url: str
    product: ProductData
    status: str = "success"
    error_message: Optional[str] = None
    attempt: int = 1
    duration_ms: int = 0
    recovered: bool = False
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @classmethod
    def success(
        cls, url: str, product: ProductData, attempt: int,
        duration_ms: int, recovered: bool = False,
    ) -> CrawlResult:
        return cls(
            url=url, product=product, status="success",
            attempt=attempt, duration_ms=duration_ms, recovered=recovered,
        )

    @classmethod
    def error(
        cls, url: str, error_message: str, attempt: int,
        duration_ms: int, recovered: bool = False,
    ) -> CrawlResult:
        return cls(
            url=url, product=ProductData.empty(), status="error",
            error_message=error_message,
            attempt=attempt, duration_ms=duration_ms, recovered=recovered,
        )

    def to_output_dict(self) -> dict:
        return {
            "title": self.product.title,
            "normal_price": _format_brl(self.product.normal_price),
            "discount_price": _format_brl(self.product.discount_price),
            "product_url": self.url,
            "image_url": self.product.image_url,
            "status": self.status,
            "error_message": self.error_message,
        }


@dataclass
class ExecutionSummary:
    total_urls: int
    processed: int
    success: int
    errors: int
    total_duration_s: float
    start_time: str
    end_time: str
    avg_duration_ms: float = 0.0
    min_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    recovered_count: int = 0
    crawler_stats: dict = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        return (self.success / self.processed * 100) if self.processed > 0 else 0.0

    def formatted(self) -> str:
        return (
            f"\n{'='*60}\n"
            f"  RESUMO DA EXECUCAO\n"
            f"{'='*60}\n"
            f"  Total URLs:       {self.total_urls}\n"
            f"  Processadas:      {self.processed}\n"
            f"  Sucesso:          {self.success}\n"
            f"  Erros:            {self.errors}\n"
            f"  Taxa sucesso:     {self.success_rate:.1f}%\n"
            f"  Recuperadas:      {self.recovered_count}\n"
            f"  Duracao total:    {self._fmt_duration(self.total_duration_s)}\n"
            f"  Media/URL:        {self.avg_duration_ms:.0f}ms\n"
            f"  Mais rapida:      {self.min_duration_ms:.0f}ms\n"
            f"  Mais lenta:       {self.max_duration_ms:.0f}ms\n"
            f"  Inicio:           {self.start_time}\n"
            f"  Fim:              {self.end_time}\n"
            f"{'='*60}"
        )

    def to_dict(self) -> dict:
        return asdict(self) | {"success_rate": self.success_rate}

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h{m:02d}m{s:02d}s"
        if m:
            return f"{m}m{s:02d}s"
        return f"{s}s"
