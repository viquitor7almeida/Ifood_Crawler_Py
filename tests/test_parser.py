from src.adapters.parser import ProductParser
from src.core.models import ProductData


def test_parse_jsonld():
    html = """<!DOCTYPE html>
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "X-Burger Completo",
  "offers": {
    "@type": "Offer",
    "price": "29.90",
    "priceCurrency": "BRL"
  },
  "image": "https://images.ifood.com.br/xburger.jpg"
}
</script>
</head><body></body></html>"""
    parser = ProductParser()
    result = parser.parse(html, "https://www.ifood.com.br/produto/xburger")
    assert result.title == "X-Burger Completo"
    assert result.normal_price == 29.90
    assert result.image_url == "https://images.ifood.com.br/xburger.jpg"


def test_parse_jsonld_discount():
    html = """<html><head>
<script type="application/ld+json">{
  "@type": "Product",
  "name": "Coca 2L",
  "offers": [
    {"@type": "Offer", "price": "9.90", "priceType": "https://schema.org/ListPrice"},
    {"@type": "Offer", "price": "7.90", "priceType": "https://schema.org/SalePrice"}
  ]
}</script>
</head></html>"""
    parser = ProductParser()
    result = parser.parse(html, "https://test.com")
    assert result.title == "Coca 2L"
    assert result.normal_price == 9.90
    assert result.discount_price == 7.90


def test_parse_jsonld_with_price_as_string():
    html = """<html><head>
<script type="application/ld+json">{"@type":"Product","name":"Coca 2L","offers":{"price":"9,90"}}</script>
</head></html>"""
    parser = ProductParser()
    result = parser.parse(html, "https://test.com")
    assert result.title == "Coca 2L"
    assert result.normal_price == 9.90


def test_parse_data_testid():
    html = """<html><body>
<h1 data-testid="product-title">Pizza Margherita</h1>
<span data-testid="product-price">R$ 45,00</span>
</body></html>"""
    parser = ProductParser()
    result = parser.parse(html, "https://test.com")
    assert result.title == "Pizza Margherita"
    assert result.normal_price == 45.00


def test_parse_meta_tags():
    html = """<html><head>
<meta property="og:title" content="Sushi Especial"/>
<meta property="product:price:amount" content="89.90"/>
</head><body></body></html>"""
    parser = ProductParser()
    result = parser.parse(html, "https://test.com")
    assert result.title == "Sushi Especial"
    assert result.normal_price == 89.90


def test_parse_css_fallback():
    html = """<html><body>
<h1 class="product-title">Açai 500ml</h1>
<span class="price-tag">R$ 22,50</span>
</body></html>"""
    parser = ProductParser()
    result = parser.parse(html, "https://test.com")
    assert result.title == "Açai 500ml"
    assert result.normal_price == 22.50


def test_parse_no_title():
    parser = ProductParser()
    result = parser.parse("<html></html>", "https://test.com")
    assert result.is_empty


def test_parse_no_price():
    html = """<html><body><h1 data-testid="product-title">Sem Preco</h1></body></html>"""
    parser = ProductParser()
    result = parser.parse(html, "https://test.com")
    assert result.title == "Sem Preco"
    assert result.normal_price is None


def test_parse_bad_jsonld():
    html = """<html><head>
<script type="application/ld+json">invalid json</script>
</head></html>"""
    parser = ProductParser()
    result = parser.parse(html, "https://test.com")
    assert result.is_empty


def test_parse_css_ifood_selectors():
    html = """<html><body>
<div class="product-detail__description">Limpador Veja Limpeza Pesada</div>
<img class="product-detail__image" src="https://static.ifood-static.com.br/img.jpg" />
<span class="product-card__price--discount">R$ 24,23<div class="product-card__price--info-wrapper"><div class="product-card__price--discount-percentage">-5%</div><span class="product-card__price--original">R$ 25,50</span></div></span>
</body></html>"""
    parser = ProductParser()
    result = parser.parse(html, "https://ifood.com.br/produto")
    assert result.title == "Limpador Veja Limpeza Pesada"
    assert result.normal_price == 25.50
    assert result.discount_price == 24.23
    assert result.image_url == "https://static.ifood-static.com.br/img.jpg"


def test_parse_css_ifood_no_discount():
    html = """<html><body>
<div class="product-detail__description">Arroz Camil 5kg</div>
<img class="product-detail__image" src="https://static.ifood-static.com.br/arroz.jpg" />
<span class="product-card__price--original">R$ 32,90</span>
</body></html>"""
    parser = ProductParser()
    result = parser.parse(html, "https://ifood.com.br/arroz")
    assert result.title == "Arroz Camil 5kg"
    assert result.normal_price == 32.90
    assert result.discount_price is None
    assert result.image_url == "https://static.ifood-static.com.br/arroz.jpg"
