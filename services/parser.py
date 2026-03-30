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
    If SCRAPER_API_KEY is configured, route through ScraperAPI with JavaScript
    rendering enabled. render=true makes ScraperAPI launch a real browser so
    prices loaded via React/Vue/JS are present in the returned HTML.
    Cost: 5 credits per request (vs 1 without render), but essential for
    modern e-commerce sites that render prices client-side.
    """
    key = getattr(settings, "scraper_api_key", "")
    if key:
        from urllib.parse import quote
        return f"http://api.scraperapi.com?api_key={key}&render=true&url={quote(url, safe='')}"
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


def _currency_from_url(url: str) -> Optional[str]:
    """Infer currency from the URL's TLD (e.g. amazon.co.uk → GBP)."""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
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
    Keeping them paired prevents the eBay-UK bug where og: has USD price and
    Schema.org has the correct GBP price.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            # Recurse into @graph
            items = obj.get("@graph") or [obj]
            for item in items:
                if item.get("@type") == "Offer":
                    price = _clean_price(str(item.get("price", "")))
                    if price:
                        curr = item.get("priceCurrency")
                        return price, (str(curr).strip().upper() if curr and len(str(curr).strip()) == 3 else None)

                offers = item.get("offers")
                if isinstance(offers, dict):
                    offers = [offers]
                if isinstance(offers, list):
                    for offer in offers:
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
    from collections import Counter

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

_AMAZON_DOMAINS = {"amazon", "amzn"}


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
    Follow redirects on the *original* URL (without ScraperAPI) to get the
    canonical destination. Needed for short links like amzn.eu/d/... that
    ScraperAPI cannot resolve itself.
    Returns the final URL, or the original if resolution fails.
    """
    short_hosts = {"amzn.eu", "amzn.to", "a.co", "amzn.in", "amzn.asia"}
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host not in short_hosts:
        return url
    try:
        async with httpx.AsyncClient(
            headers=_HEADERS, follow_redirects=True, timeout=15.0
        ) as client:
            resp = await client.head(url)
            final = str(resp.url)
            # Normalize the resolved Amazon URL to clean /dp/{ASIN} form
            return normalize_amazon_url(final)
    except Exception as exc:
        logger.warning("Could not resolve short URL %s: %s", url, exc)
        return url


async def parse_product(url: str) -> dict:
    """
    Fetch the page at *url* and extract product information.

    Returns:
        { "name": str|None, "price": float|None, "image_url": str|None, "source": str }

    Raises:
        ValueError: with a user-friendly message when parsing fails.
    """
    url = await _resolve_url(url)
    fetch_url = _build_fetch_url(url)

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=90.0,
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
    is_stub_title = _title_lower in _stub_titles or _title_lower == ""
    if any(s in _title_lower for s in _block_signals) or len(response.text) < 15000 or is_stub_title:
        raise ValueError(
            "Please use the link from your browser, not the app. "
            "It should look like: amazon.co.uk/dp/XXXXXXXXXX"
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

    # Domain-based currency baseline — use canonical/effective URL so that
    # amzn.eu short links resolved to amazon.de give EUR, amazon.co.uk gives GBP
    domain_currency = _currency_from_url(effective_url)

    if is_amazon:
        price, amazon_text_currency = _extract_amazon_price(soup)
        if price is not None:
            # Prefer currency extracted from the price text (e.g. "EUR287.00" → EUR),
            # then fall back to domain TLD (amazon.co.uk → GBP)
            price_currency = amazon_text_currency or domain_currency

    # Schema.org — try next (before og:) because sites like eBay UK set og: to USD
    # while Schema.org carries the correct local currency
    if price is None:
        price, price_currency = _extract_from_schema(soup)

    # Open Graph — only use if Schema.org didn't provide a price
    if price is None:
        og_price, og_currency = _extract_from_og(soup)
        if og_price is not None:
            price = og_price
            # Accept og: currency only when it agrees with domain OR Schema.org didn't
            # give us a currency hint.  If domain says GBP but og: says USD, trust domain.
            if og_currency and (domain_currency is None or og_currency == domain_currency):
                price_currency = og_currency
            else:
                price_currency = price_currency or domain_currency

    if price is None:
        price = _extract_generic_price(soup)

    # Best-effort currency: prefer what the price extraction provided, then domain TLD
    resolved_currency = price_currency or domain_currency

    if price is None:
        price = _extract_price_regex(soup, expected_currency=resolved_currency)

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

    # Final currency resolution: structured extraction → domain TLD → fallback USD
    page_currency = resolved_currency or _detect_page_currency(soup, effective_url) or "USD"

    logger.info(
        "Parsed %s → price=%.2f %s (price_source_currency=%s, domain_currency=%s)",
        url, price, page_currency, price_currency, domain_currency,
    )

    page_context = _extract_page_context(soup)

    return {
        "name": name,
        "price": price,
        "currency": page_currency,
        "image_url": image_url,
        "source": source,
        "page_context": page_context,
    }
