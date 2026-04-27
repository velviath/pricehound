"""
Universal price parser.

Priority order for price extraction:
  1. Open Graph meta tag  (og:price:amount)
  2. Schema.org JSON-LD   (offers.price / offers[].price)
  3. Amazon-specific CSS selectors
  4. Common price CSS class heuristics
  5. Regex scan over all visible text (last resort)

If SCRAPER_API_KEY is set in .env, all requests are routed through ScraperAPI
which handles JavaScript rendering and bypasses bot-protection on Amazon, eBay etc.

Returns a dict:  { name, price, image_url, source }
Raises ValueError with a human-readable message on total failure.
"""

import json
import logging
import re
from collections import Counter
from typing import Optional
from urllib.parse import urlparse, urljoin, urlencode, parse_qs, quote

import httpx
from bs4 import BeautifulSoup

from config import settings
from services.openai_service import check_product_availability

logger = logging.getLogger(__name__)

# Realistic browser headers
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# Amazon product image selectors + high-res data attributes, in priority order
_AMAZON_IMAGE_SELECTORS = [
    ("#landingImage",             ["data-old-hires", "data-a-hires", "src"]),
    ("#imgBlkFront",              ["data-old-hires", "data-a-hires", "src"]),
    ("#ebooksImgBlkFront",        ["data-old-hires", "data-a-hires", "src"]),
    ("#main-image-container img", ["data-old-hires", "src"]),
    ("#imageBlock img",           ["data-old-hires", "src"]),
]

_AMAZON_IMAGE_PLACEHOLDER_PATTERNS = [
    "no-image-available", "grey-video", "transparent-pixel",
    "sprite", "loading", "amazon-logo", "blank.gif",
]


def _is_amazon_placeholder(url: str) -> bool:
    u = url.lower()
    return any(p in u for p in _AMAZON_IMAGE_PLACEHOLDER_PATTERNS)


def _extract_amazon_image(soup: BeautifulSoup) -> Optional[str]:
    """Try Amazon-specific image elements before generic og:image fallback."""
    for selector, attrs in _AMAZON_IMAGE_SELECTORS:
        tag = soup.select_one(selector)
        if not tag:
            continue
        for attr in attrs:
            src = tag.get(attr, "").strip()
            if src and src.startswith("http") and not _is_amazon_placeholder(src):
                return src

    # Broader fallback: any img with a high-res data attribute
    for attr in ("data-old-hires", "data-a-hires"):
        for tag in soup.find_all("img", {attr: True}):
            src = tag.get(attr, "").strip()
            if src and src.startswith("http") and not _is_amazon_placeholder(src):
                return src

    # Modern Amazon pages: data-a-dynamic-image contains a JSON map of url → [w, h]
    for tag in soup.find_all("img", {"data-a-dynamic-image": True}):
        try:
            images: dict = json.loads(tag.get("data-a-dynamic-image", "{}"))
            if images:
                best = max(
                    images.keys(),
                    key=lambda u: (images[u][0] * images[u][1])
                    if isinstance(images[u], list) and len(images[u]) >= 2
                    else 0,
                )
                if best.startswith("http") and not _is_amazon_placeholder(best):
                    return best
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Last resort: scan inline scripts for hiRes image URL
    for script in soup.find_all("script"):
        text = script.string or ""
        m = re.search(r'"hiRes"\s*:\s*"(https://[^"]+)"', text)
        if m:
            url = m.group(1)
            if not _is_amazon_placeholder(url):
                return url

    return None


# Amazon CSS selectors in priority order (covers old and new Amazon layouts)
_AMAZON_PRICE_SELECTORS = [
    "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
    "#apex_desktop .a-price .a-offscreen",
    "#corePrice_feature_div .a-price .a-offscreen",
    "#apex_desktop_newAccordionRow .a-price .a-offscreen",
    "span.a-price > span.a-offscreen",
    "#priceblock_ourprice",
    "#priceblock_dealprice",
    "#priceblock_saleprice",
    "span#price_inside_buybox",
    ".a-price .a-offscreen",
    "span.a-color-price",
]

# CSS class fragments that commonly wrap a price
_GENERIC_PRICE_CLASSES = [
    "price_color",              # books.toscrape.com
    "price",
    "product-price",
    "offer-price",
    "sale-price",
    "current-price",
    "woocommerce-Price-amount", # WooCommerce
    "priceView-customer-price", # Best Buy
    "a-price",                  # Amazon fallback
    "product__price",           # Shopify themes
    "price__current",           # Shopify
    "price__sale",              # Shopify
    "pdp-price",                # common PDP pattern
    "pip-price",                # IKEA
    "special-price",
    "selling-price",
    "now-price",
    "final-price",
]

# data-* attributes that sometimes hold the raw numeric price
_PRICE_DATA_ATTRS = [
    "data-price",
    "data-product-price",
    "data-current-price",
    "data-sale-price",
    "data-final-price",
]

# Regex that matches typical price strings: $1,299.99 / €49 / 29.90 etc.
_PRICE_RE = re.compile(
    r'(?:[\$€£¥₹])\s*(\d{1,6}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)'
    r'|(\d{1,6}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)\s*(?:USD|EUR|GBP|CAD|AUD)',
    re.IGNORECASE,
)


def _build_fetch_url(url: str, render_off: bool = False) -> str:
    """
    If SCRAPER_API_KEY is configured, route through ScraperAPI with JavaScript
    rendering enabled. render=true makes ScraperAPI launch a real browser so
    prices loaded via React/Vue/JS are present in the returned HTML.
    Cost: 5 credits per request (vs 1 without render), but essential for
    modern e-commerce sites that render prices client-side.
    """
    key = getattr(settings, "scraper_api_key", "")
    if key:
        host = (urlparse(url).hostname or "").lower()
        _TLD_COUNTRY = {"co.uk": "gb", "de": "de", "fr": "fr", "it": "it", "es": "es", "co.jp": "jp", "com.au": "au", "ca": "ca"}
        country = next((c for tld, c in _TLD_COUNTRY.items() if host.endswith("." + tld) or host == tld), None)
        country_param = f"&country_code={country}" if country else ""
        render = "false" if render_off else "true"
        return f"http://api.scraperapi.com?api_key={key}&render={render}{country_param}&url={quote(url, safe='')}"
    return url


def _clean_price(raw: str) -> Optional[float]:
    """Strip currency symbols/whitespace and return a float, or None."""
    digits = re.sub(r"[^\d.,]", "", raw.strip())
    if not digits:
        return None
    # European format with thousands separator: 1.234,56 → 1234.56
    if re.match(r"^\d{1,3}(\.\d{3})+(,\d{1,2})?$", digits):
        digits = digits.replace(".", "").replace(",", ".")
    # European decimal without thousands separator: 829,00 → 829.00
    elif re.match(r"^\d+,\d{1,2}$", digits):
        digits = digits.replace(",", ".")
    else:
        digits = digits.replace(",", "")
    try:
        value = float(digits)
        if value <= 0 or value > 1_000_000:
            return None
        return value
    except ValueError:
        return None


_DOMAIN_CURRENCY: dict[str, str] = {
    "selfridges.com": "GBP",
}

def _currency_from_url(url: str) -> Optional[str]:
    """Infer currency from the URL's TLD (e.g. amazon.co.uk → GBP)."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host in _DOMAIN_CURRENCY:
        return _DOMAIN_CURRENCY[host]
    # Try progressively shorter suffixes: "co.uk", "uk", etc.
    parts = host.split(".")
    for length in (2, 1):
        if len(parts) >= length:
            suffix = ".".join(parts[-length:])
            if suffix in _TLD_CURRENCY:
                return _TLD_CURRENCY[suffix]
    return None


def _detect_page_currency(soup: BeautifulSoup, url: str = "") -> Optional[str]:
    """
    Try to determine what currency the page prices are in.
    Priority: Schema.org priceCurrency → og:price:currency → domain TLD.
    Returns an ISO-4217 code (e.g. 'GBP', 'EUR') or None.

    NOTE: Schema.org is checked *before* og: because sites like eBay UK set
    og:price:currency to "USD" (for international bots) while the actual
    local currency lives in the JSON-LD offer block.
    """
    # 1. Schema.org priceCurrency (most reliable for non-US sites)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            # Recurse into @graph arrays
            for item in (obj.get("@graph") or [obj]):
                offers = item.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                if isinstance(offers, dict):
                    pc = offers.get("priceCurrency")
                    if pc and len(str(pc).strip()) == 3:
                        return str(pc).strip().upper()
                # Some sites put priceCurrency at top level
                pc = item.get("priceCurrency")
                if pc and len(str(pc).strip()) == 3:
                    return str(pc).strip().upper()

    # 2. og:price:currency
    tag = soup.find("meta", property="og:price:currency")
    if tag and tag.get("content"):
        c = tag["content"].strip().upper()
        if len(c) == 3:
            return c

    # 3. Domain TLD fallback
    if url:
        return _currency_from_url(url)

    return None


def _extract_from_og(soup: BeautifulSoup) -> tuple[Optional[float], Optional[str]]:
    """Returns (price, currency) from og: meta tags, or (None, None)."""
    price_tag = soup.find("meta", property="og:price:amount")
    curr_tag = soup.find("meta", property="og:price:currency")
    price = _clean_price(price_tag["content"]) if price_tag and price_tag.get("content") else None
    curr = (curr_tag["content"].strip().upper()
            if curr_tag and curr_tag.get("content") and len(curr_tag["content"].strip()) == 3
            else None)
    return price, curr


def _extract_from_schema(soup: BeautifulSoup) -> tuple[Optional[float], Optional[str]]:
    """
    Returns (price, currency) sourced from the *same* JSON-LD offer block.
    Two-pass: first look for lowPrice (sale price), then fall back to price.
    """
    all_scripts = soup.find_all("script", type="application/ld+json")
    parsed = []
    for script in all_scripts:
        try:
            parsed.append(json.loads(script.string or ""))
        except (json.JSONDecodeError, TypeError):
            continue

    def _iter_offers(data):
        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            items = obj.get("@graph") or [obj]
            for item in items:
                if item.get("@type") in ("Offer", "AggregateOffer"):
                    yield item
                offers = item.get("offers")
                if isinstance(offers, dict):
                    yield offers
                elif isinstance(offers, list):
                    yield from offers

    # Pass 1: prefer lowPrice (catches sale prices on Zalando etc.)
    for data in parsed:
        for offer in _iter_offers(data):
            raw = offer.get("lowPrice")
            if raw is not None:
                price = _clean_price(str(raw))
                if price:
                    curr = offer.get("priceCurrency")
                    return price, (str(curr).strip().upper() if curr and len(str(curr).strip()) == 3 else None)

    # Pass 2: fall back to price field
    for data in parsed:
        for offer in _iter_offers(data):
            price = _clean_price(str(offer.get("price", "")))
            if price:
                curr = offer.get("priceCurrency")
                return price, (str(curr).strip().upper() if curr and len(str(curr).strip()) == 3 else None)

    return None, None


_ISO_CURRENCY_RE = re.compile(r'\b(USD|EUR|GBP|CAD|AUD|JPY|CHF|SEK|NOK|DKK|PLN|INR|BRL|MXN|SGD|AED|SAR)\b')


def _currency_from_text(text: str) -> Optional[str]:
    """Extract an ISO-4217 currency code embedded in a price string like 'EUR287.00'."""
    m = _ISO_CURRENCY_RE.search(text.upper())
    return m.group(1) if m else None


def _extract_amazon_price(soup: BeautifulSoup) -> tuple[Optional[float], Optional[str]]:
    """Returns (price, currency_or_None) using Amazon-specific CSS selectors."""
    for selector in _AMAZON_PRICE_SELECTORS:
        tag = soup.select_one(selector)
        if tag:
            text = tag.get_text()
            price = _clean_price(text)
            if price:
                currency = _currency_from_text(text)
                return price, currency
    return None, None


def _extract_generic_price(soup: BeautifulSoup) -> Optional[float]:
    """Try Microdata, data-* attributes, then CSS class heuristics."""
    # 1. Microdata itemprop="price" — used by many standard e-commerce sites
    tag = soup.find(attrs={"itemprop": "price"})
    if tag:
        val = tag.get("content") or tag.get_text()
        price = _clean_price(str(val))
        if price:
            return price

    # 2. data-* price attributes
    for attr in _PRICE_DATA_ATTRS:
        tag = soup.find(attrs={attr: True})
        if tag:
            price = _clean_price(str(tag.get(attr, "")))
            if price:
                return price

    # 3. CSS class fragments
    for class_fragment in _GENERIC_PRICE_CLASSES:
        tag = soup.find(
            lambda t, cf=class_fragment: t.name and any(
                cf in c.lower() for c in (t.get("class") or [])
            )
        )
        if tag:
            price = _clean_price(tag.get_text())
            if price:
                return price

    return None


_CURRENCY_SYMBOLS = {"GBP": "£", "EUR": "€", "JPY": "¥", "INR": "₹"}


def _extract_price_regex(
    soup: BeautifulSoup, expected_currency: Optional[str] = None
) -> Optional[float]:
    """
    Last-resort: scan all visible text nodes for anything that looks like a price.

    If expected_currency is set (e.g. 'GBP'), only consider prices that appear
    with the matching symbol (£) to avoid picking up incidental USD/other prices.
    Falls back to all candidates if the filtered set is empty.
    """
    expected_symbol = _CURRENCY_SYMBOLS.get(expected_currency or "", "") if expected_currency else ""

    # Extended regex that also captures the leading symbol
    _PRICE_WITH_SYM = re.compile(
        r'([\$€£¥₹])\s*(\d{1,6}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)'
        r'|(\d{1,6}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)\s*(USD|EUR|GBP|CAD|AUD)',
        re.IGNORECASE,
    )

    matched: list[tuple[float, bool]] = []  # (value, has_expected_symbol)
    for tag in soup.find_all(["span", "p", "div", "strong", "b", "td"]):
        text = tag.get_text(strip=True)
        if len(text) > 60:
            continue
        for m in _PRICE_WITH_SYM.finditer(text):
            sym = m.group(1) or ""
            raw = m.group(2) or m.group(3) or ""
            price = _clean_price(raw)
            if price:
                has_match = bool(expected_symbol and sym == expected_symbol)
                matched.append((price, has_match))

    if not matched:
        return None

    # Prefer candidates whose symbol matches expected currency
    preferred = [v for v, ok in matched if ok]
    pool = preferred if preferred else [v for v, _ in matched]

    most_common = Counter(pool).most_common(1)
    return most_common[0][0] if most_common else None


def _extract_from_next_data(soup: BeautifulSoup) -> tuple[Optional[float], Optional[str]]:
    """
    Extract price from Next.js __NEXT_DATA__ JSON blob.
    Covers Boots, Argos, John Lewis, and many other UK/EU retailers built on Next.js.
    """
    tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if not tag or not tag.string:
        return None, None
    try:
        data = json.loads(tag.string)
    except (json.JSONDecodeError, ValueError):
        return None, None

    def _search(obj, depth=0):
        if depth > 8:
            return None, None
        if isinstance(obj, dict):
            for price_key in ("price", "salePrice", "finalPrice", "currentPrice", "priceValue", "sellPrice", "amount"):
                val = obj.get(price_key)
                if val is not None:
                    p = float(val) if isinstance(val, (int, float)) and val > 0 else _clean_price(str(val))
                    if p and 0 < p < 1_000_000:
                        for curr_key in ("currency", "currencyCode", "priceCurrency"):
                            c = obj.get(curr_key)
                            if c and isinstance(c, str) and len(c.strip()) == 3:
                                return p, c.strip().upper()
                        return p, None
            for key, value in obj.items():
                if key in ("@context", "description", "content", "html", "url", "image"):
                    continue
                p, c = _search(value, depth + 1)
                if p is not None:
                    return p, c
        elif isinstance(obj, list):
            for item in obj[:5]:
                p, c = _search(item, depth + 1)
                if p is not None:
                    return p, c
        return None, None

    price, currency = _search(data)
    if price:
        logger.info("Price found via __NEXT_DATA__: %.2f %s", price, currency)
    return price, currency


def _extract_page_context(soup: BeautifulSoup, max_chars: int = 3000) -> str:
    """
    Extract useful visible text from the page for AI analysis.
    Strips scripts, styles, nav, footer. Returns up to max_chars characters.
    """
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 3]
    return "\n".join(lines[:200])[:max_chars]


def _extract_name(soup: BeautifulSoup) -> Optional[str]:
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()[:300]

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and data.get("name"):
            return str(data["name"]).strip()[:300]

    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)[:300]

    if soup.title and soup.title.string:
        return soup.title.string.strip()[:300]

    return None


def _extract_image(soup: BeautifulSoup, base_url: str = "") -> Optional[str]:
    def _abs(src: str) -> str:
        """Convert relative URL to absolute using the page's base URL."""
        if src.startswith("http"):
            return src
        return urljoin(base_url, src) if base_url else src

    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return _abs(og["content"])

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            img = data.get("image")
            if isinstance(img, list):
                img = img[0]
            if isinstance(img, dict):
                img = img.get("url")
            if img:
                return _abs(str(img))

    # Skip tiny icons and tracking pixels; prefer product images
    for tag in soup.find_all("img", src=True):
        src = tag.get("src", "")
        if not src or "logo" in src.lower() or "icon" in src.lower():
            continue
        w = tag.get("width") or tag.get("data-width")
        h = tag.get("height") or tag.get("data-height")
        # Accept if dimensions look reasonable or unknown
        if w and int(str(w).split(".")[0] or 0) < 50:
            continue
        return _abs(src)

    return None


# Map from URL TLD suffix → ISO-4217 currency.
# Used as a strong fallback when structured markup doesn't declare a currency.
_TLD_CURRENCY: dict[str, str] = {
    "co.uk": "GBP",
    "de":    "EUR",
    "fr":    "EUR",
    "es":    "EUR",
    "it":    "EUR",
    "nl":    "EUR",
    "be":    "EUR",
    "at":    "EUR",
    "pl":    "PLN",
    "se":    "SEK",
    "no":    "NOK",
    "dk":    "DKK",
    "ch":    "CHF",
    "com.au":"AUD",
    "ca":    "CAD",
    "co.jp": "JPY",
    "jp":    "JPY",
    "in":    "INR",
    "com.br":"BRL",
    "com.mx":"MXN",
    "sg":    "SGD",
    "ae":    "AED",
    "sa":    "SAR",
}

# Symbol → ISO-4217 code (used to validate/override detected currency from text)
_SYMBOL_CURRENCY: dict[str, str] = {
    "£": "GBP",
    "€": "EUR",
    "¥": "JPY",
    "₹": "INR",
    "A$": "AUD",
    "C$": "CAD",
    "CA$": "CAD",
    "AU$": "AUD",
}

_UNAVAILABLE_SCHEMA_SUFFIXES = frozenset({
    "outofstock", "discontinued", "soldout",
})

_UNAVAILABLE_TEXT_SIGNALS = (
    # eBay
    "this listing was ended",
    "listing was ended by the seller",
    "sorry, this listing ended",
    "listing ended",
    "this listing has ended",
    "listing has ended",
    # Amazon
    "currently unavailable",
    "this item is no longer available",
    "we don't know when or if this item will be back in stock",
    # Vinted / general
    "this item has been sold",
    "item not found",
    "this product is not available",
    "no longer available",
    "item unavailable",
    "product unavailable",
    "out of stock",
    "sold out",
)


def _detect_unavailability(soup: BeautifulSoup, page_title: str) -> bool:
    """Return True if the page signals the product is no longer available."""
    # 1. Schema.org offers.availability
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            items = obj.get("@graph") or [obj]
            for item in items:
                offers = item.get("offers")
                if isinstance(offers, dict):
                    offers = [offers]
                if isinstance(offers, list):
                    for offer in offers:
                        avail = str(offer.get("availability", "")).lower()
                        if any(s in avail for s in _UNAVAILABLE_SCHEMA_SUFFIXES):
                            return True

    # 2. og:availability meta tag
    og_avail = soup.find("meta", property="og:availability")
    if og_avail:
        val = (og_avail.get("content") or "").lower().replace(" ", "").replace("_", "")
        if any(s in val for s in _UNAVAILABLE_SCHEMA_SUFFIXES) or val in ("oos", "unavailable"):
            return True

    # 3. Title + body text (scan first 15000 chars — JS-rendered pages can be large)
    body_text = " ".join(t.strip() for t in soup.stripped_strings)[:15000].lower()
    combined = page_title.lower() + " " + body_text
    return any(signal in combined for signal in _UNAVAILABLE_TEXT_SIGNALS)


_AMAZON_DOMAINS = {"amazon", "amzn"}
_EBAY_DOMAINS   = {"ebay"}


_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "rec", "cm_sp", "cm_re", "icid", "ref", "ref_", "tag", "linkcode",
    "linkid", "camp", "creative", "creativeASIN", "th", "psc",
    "Item", "Tpk", "gclid", "fbclid", "msclkid", "igshid",
}

def strip_tracking_params(url: str) -> str:
    """Remove known tracking/session query parameters from a URL."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {k: v for k, v in qs.items() if k not in _TRACKING_PARAMS}
    new_query = urlencode(cleaned, doseq=True)
    return parsed._replace(query=new_query).geturl()


def normalize_ebay_url(url: str) -> str:
    """
    Collapse eBay listing URLs to the canonical /itm/{ITEM_ID} form.
    eBay tracking/session query parameters expire and cause 404s from
    non-browser IPs (e.g. ScraperAPI). The bare item URL is always stable.
    Non-eBay URLs are returned unchanged.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").removeprefix("www.")
    parts = host.split(".")
    domain_name = parts[-3] if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL_DOMAINS else (parts[-2] if len(parts) >= 2 else host)
    if domain_name not in _EBAY_DOMAINS:
        return url

    item_match = re.search(r"/itm/(?:[^/]+/)?(\d{10,})", parsed.path)
    if not item_match:
        return url

    item_id = item_match.group(1)
    tld = ".".join(parts[-3:]) if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL_DOMAINS else ".".join(parts[-2:])
    return f"https://www.{tld}/itm/{item_id}"


def normalize_amazon_url(url: str) -> str:
    """
    Collapse Amazon product URLs to the canonical /dp/{ASIN} form.

    Amazon URLs often contain session tokens, referral tags and other
    query-string parameters that can expire or change over time, causing
    future fetches to fail.  The canonical form is stable and always works:
        https://www.amazon.{tld}/dp/{ASIN}

    Non-Amazon URLs are returned unchanged.
    """
    host = (urlparse(url).hostname or "").removeprefix("www.")
    parts = host.split(".")
    domain_name = parts[-2] if len(parts) >= 2 else host
    if domain_name not in _AMAZON_DOMAINS:
        return url

    asin_match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url)
    if not asin_match:
        return url

    asin = asin_match.group(1)
    tld = ".".join(parts[-2:])   # e.g. "amazon.com" or "amazon.co.uk"
    return f"https://www.{tld}/dp/{asin}"


_SECOND_LEVEL_DOMAINS = {"co", "com", "org", "net", "edu", "gov", "ac", "me", "ne"}


def _detect_source(url: str) -> str:
    host = urlparse(url).hostname or ""
    host = host.removeprefix("www.")
    parts = host.split(".")
    if any(p in _AMAZON_DOMAINS for p in parts):
        return "Amazon"
    # Handle multi-part TLDs: ebay.co.uk → ["ebay","co","uk"] → take parts[-3]
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL_DOMAINS:
        name = parts[-3]
    elif len(parts) >= 2:
        name = parts[-2]
    else:
        name = host
    return name.capitalize()


async def _resolve_url(url: str) -> str:
    """
    Follow redirects on the *original* URL to get the canonical destination.
    Needed for short links like amzn.eu/d/... or amzn.to/...
    Tries a direct HEAD request first; if that fails (some short links require
    a browser UA or return 404 to bots), falls back to ScraperAPI to resolve.
    Returns the final normalized URL, or the original if resolution fails.
    """
    short_hosts = {"amzn.eu", "amzn.to", "a.co", "amzn.in", "amzn.asia"}
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host not in short_hosts:
        return url

    # Try direct HEAD first (fast, no cost)
    try:
        async with httpx.AsyncClient(
            headers=_HEADERS, follow_redirects=True, timeout=15.0
        ) as client:
            resp = await client.head(url)
            final = str(resp.url)
            if "amazon." in final:
                return normalize_amazon_url(final)
    except Exception:
        pass

    # Fall back: fetch via ScraperAPI and read canonical tag from page
    try:
        fallback_url = _build_fetch_url(url)
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            resp = await client.get(fallback_url)
            soup_tmp = BeautifulSoup(resp.text, "lxml")
            canonical = soup_tmp.find("link", rel="canonical")
            if canonical and canonical.get("href"):
                final = canonical["href"].strip()
                if "amazon." in final:
                    return normalize_amazon_url(final)
            # Try to get ASIN from the redirected URL
            final = str(resp.url)
            if "amazon." in final:
                return normalize_amazon_url(final)
    except Exception as exc:
        logger.warning("Could not resolve short URL %s: %s", url, exc)

    return url


_BOT_PROTECTED_DOMAINS = {"amazon", "amzn", "ebay", "argos", "newegg", "bhphotovideo", "target", "spacenk"}


async def parse_product(url: str) -> dict:
    """
    Fetch the page at *url* and extract product information.

    Returns:
        { "name": str|None, "price": float|None, "image_url": str|None, "source": str }

    Raises:
        ValueError: with a user-friendly message when parsing fails.
    """
    url = await _resolve_url(url)
    url = normalize_ebay_url(url)
    url = strip_tracking_params(url)

    scraper_key = getattr(settings, "scraper_api_key", "")
    _host = (urlparse(url).hostname or "").removeprefix("www.")
    _parts = _host.split(".")
    _domain = (_parts[-3] if len(_parts) >= 3 and _parts[-2] in _SECOND_LEVEL_DOMAINS
               else (_parts[-2] if len(_parts) >= 2 else _host)).lower()
    _needs_scraper = _domain in _BOT_PROTECTED_DOMAINS

    async def _fetch(fetch_url: str, timeout: float = 90.0):
        async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True, timeout=timeout) as client:
            return await client.get(fetch_url)

    response = None

    # For non-bot-protected sites: try a direct fetch first to save ScraperAPI credits
    if scraper_key and not _needs_scraper:
        try:
            direct = await _fetch(url, timeout=20.0)
            if direct.status_code == 200 and len(direct.text) > 15000:
                logger.info("Direct fetch succeeded for %s — skipping ScraperAPI", url)
                response = direct
        except Exception:
            pass

    if response is None:
        try:
            response = await _fetch(_build_fetch_url(url, render_off=False))
            # On 404: retry without JS rendering, then fall back to direct fetch
            if response.status_code == 404 and scraper_key:
                logger.info("Got 404 with render=true, retrying without JS rendering: %s", url)
                response = await _fetch(_build_fetch_url(url, render_off=True))
            if response.status_code == 404:
                logger.info("ScraperAPI 404, attempting direct fetch: %s", url)
                response = await _fetch(url, timeout=30.0)
        except Exception:
            response = None

    if response is None:
        raise ValueError("Failed to fetch the product page. Please try again.")

    try:
        # If all fetches returned 404, check the body for "listing ended" signals.
        # eBay (and similar) returns 404 with a full HTML page when a listing has been removed.
        # We parse the content to distinguish a genuine removal from a transient bot-block.
        if response.status_code == 404:
            try:
                _404_soup = BeautifulSoup(response.text, "lxml")
                _404_text = _404_soup.get_text()[:3000].lower()
                _404_title = (_404_soup.title.string or "").strip().lower() if _404_soup.title else ""
                _ENDED_SIGNALS = (
                    "page is missing", "listing has ended", "listing was ended",
                    "no longer available", "item not found", "page doesn't exist",
                    "page not found",
                )
                if any(s in _404_text for s in _ENDED_SIGNALS) or "error page" in _404_title:
                    logger.info("Detected removed/ended listing from 404 content: %s", url)
                    return {
                        "name": None, "price": None, "image_url": None,
                        "source": _detect_source(url),
                        "availability": "url_error",
                        "canonical_url": None, "currency": None, "page_context": None,
                    }
            except Exception:
                pass
        response.raise_for_status()
    except httpx.TimeoutException:
        raise ValueError("The product page took too long to respond. Please try again.")
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in (403, 503):
            raise ValueError(
                "This website is blocking automated access. "
                "Try a direct link from your browser, or use a supported store like Amazon or eBay."
            )
        if code in (404, 410):
            raise ValueError(
                "[URL_ERROR] This product page no longer exists. "
                "The listing may have been removed — try re-adding it with a fresh link."
            )
        raise ValueError("Could not reach the product page. Please check the link and try again.")
    except Exception:
        raise ValueError("Something went wrong while loading this page. Please try again.")

    soup = BeautifulSoup(response.text, "lxml")

    # Try to resolve the canonical URL from the page itself.
    # This is important for short links (amzn.eu) where ScraperAPI may redirect
    # to a different regional store — the canonical tag tells us the real URL.
    canonical_tag = soup.find("link", rel="canonical")
    canonical_url = canonical_tag["href"].strip() if canonical_tag and canonical_tag.get("href") else None
    effective_url = canonical_url or url

    source = _detect_source(effective_url)
    _host = (urlparse(effective_url).hostname or "").removeprefix("www.")
    is_amazon = any(d in _host.split(".") for d in _AMAZON_DOMAINS)
    # Also re-run amazon normalization on the resolved URL
    if is_amazon:
        url = normalize_amazon_url(effective_url)
    final_url = effective_url

    page_title = (soup.title.string or "").strip() if soup.title else ""
    logger.info("Page title: %s | Response length: %d chars", page_title or "—", len(response.text))

    # Detect bot-block / CAPTCHA / redirect-stub pages early
    _block_signals = (
        "robot check", "captcha", "access denied", "enable javascript",
        "are you a human", "unusual traffic", "verify you are human",
        "please verify", "security check", "pardon our interruption",
        "ddos-guard", "cloudflare",
    )
    _title_lower = page_title.lower()
    # Generic store homepages used as redirect stubs (e.g. "Amazon.co.uk", "eBay")
    _stub_titles = ("amazon.co.uk", "amazon.com", "ebay", "amazon")
    is_stub_title = _title_lower in _stub_titles
    if any(s in _title_lower for s in _block_signals):
        raise ValueError(
            "This store is blocking automated access. Try a supported store like Amazon or eBay."
        )
    if is_stub_title:
        raise ValueError(
            "This link leads to a homepage, not a product page. "
            "If you copied it from an app, try opening the product in your browser and copying the link from the address bar."
        )
    if len(response.text) < 15000:
        raise ValueError(
            "Could not load this page properly. The store may be temporarily blocking access — please try again later."
        )

    # ── Price + currency extraction ────────────────────────────────────────────
    # We try to extract price and currency from the *same* structured source so
    # they always correspond.  The priority order is:
    #   1. Amazon-specific CSS (currency inferred from domain TLD)
    #   2. Schema.org JSON-LD  (price + priceCurrency from same offer block)
    #   3. Open Graph meta     (og:price:amount + og:price:currency)
    #   4. Generic CSS classes (price only; currency from domain/structured data)
    #   5. Regex scan          (filtered by expected currency symbol)
    #
    # The domain TLD provides a strong currency baseline (e.g. amazon.co.uk → GBP)
    # that overrides the USD default when no structured currency data is found.

    price: Optional[float] = None
    price_currency: Optional[str] = None  # currency paired with the price source
    price_method: Optional[str] = None    # for logging

    # Domain-based currency baseline — use canonical/effective URL so that
    # amzn.eu short links resolved to amazon.de give EUR, amazon.co.uk gives GBP
    domain_currency = _currency_from_url(effective_url)

    if is_amazon:
        amazon_css_price, amazon_text_currency = _extract_amazon_price(soup)
        schema_price, schema_currency = _extract_from_schema(soup)

        if amazon_css_price and schema_price:
            diff_pct = abs(amazon_css_price - schema_price) / max(amazon_css_price, schema_price)
            if diff_pct > 0.05:
                # Disagree by >5% — schema.org is more reliable structured data
                logger.warning(
                    "amazon-css (%.2f) disagrees with schema.org (%.2f) by %.0f%% — using schema.org",
                    amazon_css_price, schema_price, diff_pct * 100,
                )
                price = schema_price
                price_currency = schema_currency or amazon_text_currency or domain_currency
                price_method = "schema.org (overrides amazon-css)"
            else:
                price = amazon_css_price
                price_currency = amazon_text_currency or domain_currency
                price_method = "amazon-css"
        elif amazon_css_price:
            price = amazon_css_price
            price_currency = amazon_text_currency or domain_currency
            price_method = "amazon-css"
        elif schema_price:
            price = schema_price
            price_currency = schema_currency or domain_currency
            price_method = "schema.org"

    # Schema.org for non-Amazon (before og:)
    if price is None:
        price, price_currency = _extract_from_schema(soup)
        if price is not None:
            price_method = "schema.org"

    # Open Graph — only use if Schema.org didn't provide a price
    if price is None:
        og_price, og_currency = _extract_from_og(soup)
        if og_price is not None:
            price = og_price
            price_method = "og:price"
            if og_currency and (domain_currency is None or og_currency == domain_currency):
                price_currency = og_currency
            else:
                price_currency = price_currency or domain_currency

    # Best-effort currency: prefer what the price extraction provided, then domain TLD
    resolved_currency = price_currency or domain_currency

    # Next.js __NEXT_DATA__ — covers Boots, Argos, John Lewis, etc.
    if price is None and not is_amazon:
        next_price, next_currency = _extract_from_next_data(soup)
        if next_price is not None:
            price = next_price
            price_currency = next_currency or resolved_currency
            price_method = "next-data"
            resolved_currency = price_currency or resolved_currency

    # Generic CSS / Microdata / data-* — skipped for Amazon (too many false prices)
    if price is None and not is_amazon:
        price = _extract_generic_price(soup)
        if price is not None:
            price_method = "generic-css"

    if price is None and not is_amazon:
        price = _extract_price_regex(soup, expected_currency=resolved_currency)
        if price is not None:
            price_method = "regex"

    name = _extract_name(soup)
    if is_amazon:
        image_url = _extract_amazon_image(soup) or _extract_image(soup, base_url=final_url)
    else:
        image_url = _extract_image(soup, base_url=final_url)

    if price is None:
        raise ValueError(
            "Could not find the price on this page. "
            "Try copying the link directly from your browser, or use a supported store like Amazon or eBay."
        )

    # Final currency resolution: structured extraction → domain TLD → fallback USD
    page_currency = resolved_currency or _detect_page_currency(soup, effective_url) or "USD"

    logger.info(
        "Parsed %s → price=%.2f %s via %s (price_source_currency=%s, domain_currency=%s)",
        url, price, page_currency, price_method, price_currency, domain_currency,
    )

    page_context = _extract_page_context(soup)

    # Keyword pre-check first (no API call needed)
    if _detect_unavailability(soup, page_title):
        availability = "unavailable"
    else:
        # AI check only for secondhand/marketplace platforms where listings commonly end.
        # Major retailers (Amazon, BestBuy, etc.) don't end listings the same way.
        _SECONDHAND = {"ebay", "vinted", "depop", "etsy", "gumtree", "craigslist", "mercari", "poshmark"}
        if source.lower() in _SECONDHAND:
            is_available = await check_product_availability(page_title, page_context)
            availability = "available" if is_available else "unavailable"
        else:
            availability = "available"

    if availability == "unavailable":
        logger.info("Product marked unavailable: %s", url)

    return {
        "name": name,
        "price": price,
        "currency": page_currency,
        "image_url": image_url,
        "source": source,
        "page_context": page_context,
        "availability": availability,
        "canonical_url": url,  # resolved canonical URL — may differ from original (short links)
    }
