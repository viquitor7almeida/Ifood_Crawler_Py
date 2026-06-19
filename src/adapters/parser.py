from __future__ import annotations

import json
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from src.core.models import ProductData

logger = logging.getLogger(__name__)


class ProductParser:

    def parse(self, html: str, url: str) -> ProductData:
        product = self._from_jsonld(html)
        if product and product.title and product.normal_price is not None:
            logger.info("JSON-LD: parsed %s", url)
            return product

        product = self._from_data_testid(html)
        if product and product.title and product.normal_price is not None:
            logger.info("data-testid: parsed %s", url)
            return product

        product = self._from_meta(html)
        if product and product.title and product.normal_price is not None:
            logger.info("meta: parsed %s", url)
            return product

        product = self._from_css(html)
        if product and product.title:
            logger.info("CSS: parsed %s", url)
            return product

        logger.warning("Parse failed for %s", url)
        return ProductData()

    # ── JSON-LD ──────────────────────────────────────────────

    def _from_jsonld(self, html: str) -> Optional[ProductData]:
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and data.get("@type") in ("Product", "ItemPage"):
                return self._extract_jsonld_product(data)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") in ("Product", "ItemPage"):
                        return self._extract_jsonld_product(item)
        return None

    def _extract_jsonld_product(self, data: dict) -> Optional[ProductData]:
        title = data.get("name") or data.get("headline")
        if not title:
            return None

        normal_price: Optional[float] = None
        discount_price: Optional[float] = None

        offers = data.get("offers") or {}
        if isinstance(offers, dict):
            offers = [offers]

        if isinstance(offers, list):
            for offer in offers:
                price_type = offer.get("priceType", "")
                price_val = self._parse_price(offer.get("price"))
                if price_type == "https://schema.org/SalePrice" or "sale" in price_type.lower():
                    discount_price = price_val
                elif price_type == "https://schema.org/ListPrice" or "list" in price_type.lower():
                    normal_price = price_val
                else:
                    if normal_price is None:
                        normal_price = price_val

        if normal_price is None:
            normal_price = self._parse_price(data.get("price"))

        image = data.get("image")
        if isinstance(image, list) and image:
            image = image[0]
        if isinstance(image, dict):
            image = image.get("url") or image.get("contentUrl")

        return ProductData(
            title=str(title),
            normal_price=normal_price,
            discount_price=discount_price,
            image_url=str(image) if image else None,
        )

    # ── data-testid ──────────────────────────────────────────

    def _from_data_testid(self, html: str) -> Optional[ProductData]:
        soup = BeautifulSoup(html, "html.parser")
        title_el = (
            soup.select_one("[data-testid='product-title']")
            or soup.select_one("[data-testid='item-name']")
            or soup.select_one("[data-testid='dish-name']")
            or soup.select_one("h1")
        )
        if not title_el:
            return None
        title = title_el.get_text(strip=True)

        normal_price: Optional[float] = None
        discount_price: Optional[float] = None
        price_el = (
            soup.select_one("[data-testid='product-price']")
            or soup.select_one("[data-testid='price-value']")
            or soup.select_one("[data-testid='price']")
        )
        if price_el:
            normal_price = self._parse_price(price_el.get_text(strip=True))

        discount_el = (
            soup.select_one("[data-testid='discount-price']")
            or soup.select_one("[data-testid='price-discount']")
            or soup.select_one("[data-testid='promo-price']")
            or soup.select_one("[class*=discount] [data-testid*=price]")
        )
        if discount_el:
            discount_price = self._parse_price(discount_el.get_text(strip=True))

        return self._build(title, normal_price, discount_price, soup)

    # ── meta tags ────────────────────────────────────────────

    def _from_meta(self, html: str) -> Optional[ProductData]:
        soup = BeautifulSoup(html, "html.parser")
        title = None
        for prop in ("og:title", "twitter:title", "product:name"):
            el = soup.select_one(f'meta[property="{prop}"]') or soup.select_one(f'meta[name="{prop}"]')
            if el and el.get("content"):
                title = el["content"]
                break
        if not title:
            el = soup.select_one("title")
            if el:
                title = el.get_text(strip=True)

        normal_price: Optional[float] = None
        for prop in ("product:price:amount", "og:price:amount"):
            el = soup.select_one(f'meta[property="{prop}"]')
            if el and el.get("content"):
                normal_price = self._parse_price(el["content"])
                break

        discount_price: Optional[float] = None
        for prop in ("product:sale_price:amount", "og:sale_price:amount"):
            el = soup.select_one(f'meta[property="{prop}"]')
            if el and el.get("content"):
                discount_price = self._parse_price(el["content"])
                break

        return self._build(title, normal_price, discount_price, soup)

    # ── CSS fallback (iFood-specific selectors) ──────────────

    def _from_css(self, html: str) -> Optional[ProductData]:
        soup = BeautifulSoup(html, "html.parser")
        title_el = (
            soup.select_one(".product-detail__description")
            or soup.select_one(".product-title")
            or soup.select_one(".item-title")
            or soup.select_one(".name")
            or soup.select_one("h1")
        )
        if not title_el:
            return None
        title = title_el.get_text(strip=True)

        normal_price: Optional[float] = None
        discount_price: Optional[float] = None

        # original price (always present, even when discounted)
        original_el = (
            soup.select_one(".product-card__price--original")
            or soup.select_one(".price-tag")
            or soup.select_one(".product-price")
            or soup.select_one(".price")
            or soup.select_one("[class*=price]")
        )
        if original_el:
            normal_price = self._parse_price(original_el.get_text(strip=True))

        # discount price element — the direct text is the sale price,
        # it also contains .product-card__price--original as a child.
        # Use .contents to get only the direct text node, not children.
        discount_el = soup.select_one(".product-card__price--discount")
        if discount_el:
            direct_text = ""
            for child in discount_el.contents:
                if isinstance(child, str) and child.strip():
                    direct_text += child.strip()
            if direct_text:
                discount_price = self._parse_price(direct_text)
            else:
                discount_price = self._parse_price(discount_el.get_text(strip=True))
        else:
            discount_el = (
                soup.select_one(".discount-price")
                or soup.select_one(".promo-price")
                or soup.select_one(".sale-price")
                or soup.select_one("[class*=discount]")
            )
            if discount_el:
                discount_price = self._parse_price(discount_el.get_text(strip=True))

        return self._build(title, normal_price, discount_price, soup)

    # ── shared ───────────────────────────────────────────────

    def _build(
        self, title: Optional[str],
        normal_price: Optional[float],
        discount_price: Optional[float],
        soup: BeautifulSoup,
    ) -> Optional[ProductData]:
        if not title:
            return None
        image_url = None
        img = (
            soup.select_one("img.product-detail__image")
            or soup.select_one("meta[property='og:image']")
            or soup.select_one("meta[name='twitter:image']")
            or soup.select_one("img[class*=product], img[class*=item]")
        )
        if img:
            image_url = img.get("content") or img.get("src")
        return ProductData(
            title=title,
            normal_price=normal_price,
            discount_price=discount_price,
            image_url=image_url,
        )

    # ── price parsing ────────────────────────────────────────

    @staticmethod
    def _parse_price(text) -> Optional[float]:
        if not text:
            return None
        text = str(text).strip().replace("R$", "").replace(" ", "")
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        elif "," in text:
            text = text.replace(",", ".")
        match = re.search(r"(\d+\.?\d*)", text)
        if match:
            return float(match.group(1))
        return None
