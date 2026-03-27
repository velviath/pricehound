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
from typing import Optional
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from config import settings

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
    "price_color",       # books.toscrape.com
    "price",
    "product-price",
    "offer-price",
    "sale-price",
    "current-price",
    "woocommerce-Price-amount",
    "priceView-customer-price",   # Best Buy
    "a-price",                    # Amazon fallback
]

# Regex that matches typical price strings: $1,299.99 / €49 / 29.90 etc.
_PRICE_RE = re.compile(
    r'(?:[\$€£¥₹])\s*(\d{1,6}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)'
    r'|(\d{1,6}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)\s*(?:USD|EUR|GBP|CAD|AUD)',
    re.IGNORECASE,
)


def _build_fetch_url(url: str) -> str:
    """
    If SCRAPER_API_KEY is configured, route through ScraperAPI for proxy rotation
    and bot-protection bypass. render=true is intentionally off — it's slow (30-60s)
    and costs 5x credits. Proxy rotation alone works for most sites incl. Amazon.
    """
    key = getattr(settings, "scraper_api_key", "")
    if key:
        from urllib.parse import quote
        return f"http://api.scraperapi.com?api_key={key}&url={quote(url, safe='')}"
    return url


def _clean_price(raw: str) -> Optional[float]:
    """Strip currency symbols/whitespace and return a float, or None."""
    digits = re.sub(r"[^\d.,]", "", raw.strip())
    if not digits:
        return None
    # European format: 1.234,56 → 1234.56
    if re.match(r"^\d{1,3}(\.\d{3})+(,\d{1,2})?$", digits):
        digits = digits.replace(".", "").replace(",", ".")
    else:
        digits = digits.replace(",", "")
    try:
        value = float(digits)
        if value <= 0 or value > 1_000_000:
            return None
        return value
    except ValueError:
        return None


def _extract_from_og(soup: BeautifulSoup) -> Optional[float]:
    tag = soup.find("meta", property="og:price:amount")
    if tag and tag.get("content"):
        return _clean_price(tag["content"])
    return None


def _extract_from_schema(soup: BeautifulSoup) -> Optional[float]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            if obj.get("@type") == "Offer":
                price = _clean_price(str(obj.get("price", "")))
                if price:
                    return price
            offers = obj.get("offers")
            if isinstance(offers, dict):
                offers = [offers]
            if isinstance(offers, list):
                for offer in offers:
                    price = _clean_price(str(offer.get("price", "")))
                    if price:
                        return price
    return None


def _extract_amazon_price(soup: BeautifulSoup) -> Optional[float]:
    for selector in _AMAZON_PRICE_SELECTORS:
        tag = soup.select_one(selector)
        if tag:
            price = _clean_price(tag.get_text())
            if price:
                return price
    return None


def _extract_generic_price(soup: BeautifulSoup) -> Optional[float]:
    """
    Look for elements whose class contains a known price keyword.
    Uses a default-argument capture to avoid the Python closure bug
    where the loop variable is shared across all lambda calls.
    """
    for class_fragment in _GENERIC_PRICE_CLASSES:
        tag = soup.find(
            # cf=class_fragment captures the current value, not a reference
            lambda t, cf=class_fragment: t.name and any(
                cf in c.lower() for c in (t.get("class") or [])
            )
        )
        if tag:
            price = _clean_price(tag.get_text())
            if price:
                return price
    return None


def _extract_price_regex(soup: BeautifulSoup) -> Optional[float]:
    """
    Last-resort: scan all visible text nodes for anything that looks like a price.
    Returns the most commonly occurring price value to filter out noise.
    """
    candidates: list[float] = []
    # Only search in elements likely to contain a product price
    for tag in soup.find_all(["span", "p", "div", "strong", "b", "td"]):
        text = tag.get_text(strip=True)
        if len(text) > 40:  # skip long text blocks
            continue
        for match in _PRICE_RE.finditer(text):
            raw = match.group(1) or match.group(2)
            price = _clean_price(raw)
            if price:
                candidates.append(price)

    if not candidates:
        return None

    # Return the most frequent candidate (majority vote)
    from collections import Counter
    most_common = Counter(candidates).most_common(1)
    return most_common[0][0] if most_common else None


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


def _detect_source(url: str) -> str:
    host = urlparse(url).hostname or ""
    host = host.removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 2:
        return parts[-2].capitalize()
    return host.capitalize()


async def parse_product(url: str) -> dict:
    """
    Fetch the page at *url* and extract product information.

    Returns:
        { "name": str|None, "price": float|None, "image_url": str|None, "source": str }

    Raises:
        ValueError: with a user-friendly message when parsing fails.
    """
    fetch_url = _build_fetch_url(url)

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=45.0,
        ) as client:
            response = await client.get(fetch_url)
            response.raise_for_status()
    except httpx.TimeoutException:
        raise ValueError("The product page took too long to respond. Please try again.")
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in (403, 503):
            raise ValueError(
                "This website is blocking automated requests. "
                "Try a different store, or add a SCRAPER_API_KEY to your .env to unlock Amazon, eBay and more."
            )
        raise ValueError(f"Could not reach the product page (HTTP {code}).")
    except Exception as exc:
        raise ValueError(f"Failed to fetch the product page: {exc}")

    soup = BeautifulSoup(response.text, "lxml")
    # Use final URL after redirects (handles short links like amzn.eu/d/…)
    final_url = str(response.url)
    source = _detect_source(final_url)
    is_amazon = "amazon" in (urlparse(final_url).hostname or "")

    logger.debug("Page title: %s", soup.title.string if soup.title else "—")
    logger.debug("Response length: %d chars", len(response.text))

    # ── Price extraction (priority order) ─────────────────────────────────────
    price: Optional[float] = None

    if is_amazon:
        price = _extract_amazon_price(soup)

    if price is None:
        price = _extract_from_og(soup)

    if price is None:
        price = _extract_from_schema(soup)

    if price is None:
        price = _extract_generic_price(soup)

    if price is None:
        price = _extract_price_regex(soup)

    name = _extract_name(soup)
    if is_amazon:
        image_url = _extract_amazon_image(soup) or _extract_image(soup, base_url=final_url)
    else:
        image_url = _extract_image(soup, base_url=final_url)

    if price is None:
        raise ValueError(
            "Could not find the price on this page. "
            "The site may block scrapers or render prices with JavaScript. "
            "Add a SCRAPER_API_KEY to your .env to enable support for more sites."
        )

    return {
        "name": name,
        "price": price,
        "image_url": image_url,
        "source": source,
    }
