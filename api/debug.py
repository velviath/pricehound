"""
Debug endpoint — parse a URL and return a full extraction trace.
Usage: GET /api/debug/parse?url=https://...

Returns a JSON object with every intermediate step so you can see exactly
what ScraperAPI returned and why a particular price was (or wasn't) found.
"""

import json
import re
from typing import Optional
from urllib.parse import urlparse, quote

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import settings
from services.parser import (
    _HEADERS,
    _clean_price,
    _detect_page_currency,
    _currency_from_url,
    _extract_from_og,
    _extract_from_schema,
    _extract_amazon_price,
    _extract_generic_price,
    _extract_price_regex,
    _AMAZON_DOMAINS,
    _AMAZON_PRICE_SELECTORS,
    _resolve_url,
)

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/parse")
async def debug_parse(url: str):
    """Full extraction trace for a given URL."""
    trace: dict = {"url": url, "steps": []}

    # 0. Resolve short URLs (amzn.eu etc.)
    resolved = await _resolve_url(url)
    trace["resolved_url"] = resolved
    url = resolved

    # 1. Build fetch URL
    key = getattr(settings, "scraper_api_key", "")
    using_scraper = bool(key)
    fetch_url = (
        f"http://api.scraperapi.com?api_key={key}&render=true&url={quote(url, safe='')}"
        if key else url
    )
    trace["using_scraperapi"] = using_scraper
    trace["render_true"] = using_scraper

    # 2. Fetch
    try:
        async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True, timeout=90.0) as client:
            resp = await client.get(fetch_url)
            resp.raise_for_status()
    except Exception as exc:
        trace["fetch_error"] = str(exc)
        return JSONResponse(trace)

    html = resp.text
    trace["http_status"] = resp.status_code
    trace["response_length"] = len(html)
    trace["response_first_500_chars"] = html[:500]

    soup = BeautifulSoup(html, "lxml")
    page_title = (soup.title.string or "").strip() if soup.title else ""
    trace["page_title"] = page_title

    # 3. Domain currency
    domain_currency = _currency_from_url(url)
    trace["domain_currency"] = domain_currency

    # 4. og: tags
    og_price_tag = soup.find("meta", property="og:price:amount")
    og_curr_tag = soup.find("meta", property="og:price:currency")
    trace["og_price_amount"] = og_price_tag.get("content") if og_price_tag else None
    trace["og_price_currency"] = og_curr_tag.get("content") if og_curr_tag else None

    # 5. Schema.org blocks (summarised)
    schema_blocks = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        schema_blocks.append(data)
    trace["schema_org_blocks_count"] = len(schema_blocks)
    trace["schema_org_blocks"] = schema_blocks[:5]  # first 5

    # 6. Run extractors
    _host = (urlparse(url).hostname or "").removeprefix("www.")
    is_amazon = any(d in _host.split(".") for d in _AMAZON_DOMAINS)
    trace["is_amazon"] = is_amazon

    amazon_price, amazon_currency = _extract_amazon_price(soup) if is_amazon else (None, None)
    trace["amazon_price"] = amazon_price
    trace["amazon_currency_from_text"] = amazon_currency

    schema_price, schema_curr = _extract_from_schema(soup)
    trace["schema_price"] = schema_price
    trace["schema_currency"] = schema_curr

    og_price, og_curr = _extract_from_og(soup)
    trace["og_price_parsed"] = og_price
    trace["og_currency_parsed"] = og_curr

    generic_price = _extract_generic_price(soup)
    trace["generic_css_price"] = generic_price

    # Resolved currency (same logic as parser)
    price_currency = (schema_curr if schema_price else None) or domain_currency
    regex_price = _extract_price_regex(soup, expected_currency=price_currency)
    trace["regex_price"] = regex_price
    trace["regex_expected_currency"] = price_currency

    # 7. Final decision (mirrors parse_product logic)
    price = None
    source = "none"
    if is_amazon and amazon_price:
        price, source = amazon_price, "amazon_css"
    if price is None and schema_price:
        price, source = schema_price, "schema_org"
    if price is None and og_price:
        price, source = og_price, "og_meta"
    if price is None and generic_price:
        price, source = generic_price, "generic_css"
    if price is None and regex_price:
        price, source = regex_price, "regex"

    final_currency = price_currency or _detect_page_currency(soup, url) or "USD"
    trace["final_price"] = price
    trace["final_currency"] = final_currency
    trace["winning_extractor"] = source

    # 8. Search for £/$ symbols anywhere in raw HTML
    pound_positions = [m.start() for m in re.finditer(r'£', html)]
    trace["pound_sign_count_in_html"] = len(pound_positions)
    # Show snippets around first few £ occurrences
    trace["pound_sign_snippets"] = [
        html[max(0, p-30):p+60] for p in pound_positions[:10]
    ]

    # 9. All elements whose class contains "price" — show class + inner HTML
    price_class_elements = []
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class") or [])
        if "price" in classes.lower():
            price_class_elements.append({
                "tag": tag.name,
                "class": classes[:120],
                "text": tag.get_text(strip=True)[:80],
                "html": str(tag)[:200],
            })
    trace["price_class_elements"] = price_class_elements[:30]

    # 10. Amazon-specific selector probe — show whether each selector matched
    amazon_selector_probe = []
    for sel in _AMAZON_PRICE_SELECTORS:
        tag = soup.select_one(sel)
        amazon_selector_probe.append({
            "selector": sel,
            "found": tag is not None,
            "text": tag.get_text(strip=True)[:80] if tag else None,
        })
    trace["amazon_selector_probe"] = amazon_selector_probe

    # 11. All price-like text on the page (broad regex, no length limit)
    _PRICE_RE = re.compile(
        r'([\$€£¥₹])\s*(\d{1,6}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)'
        r'|(\d{1,6}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)\s*(USD|EUR|GBP|CAD|AUD)',
        re.IGNORECASE,
    )
    all_prices_found = []
    for tag in soup.find_all(["span", "p", "div", "strong", "b", "td"]):
        text = tag.get_text(strip=True)
        if len(text) > 120:
            continue
        for m in _PRICE_RE.finditer(text):
            sym = m.group(1) or ""
            raw = m.group(2) or m.group(3) or ""
            val = _clean_price(raw)
            if val:
                all_prices_found.append({"symbol": sym, "value": val, "text": text[:100]})
    trace["all_price_candidates"] = all_prices_found[:50]

    return JSONResponse(trace)
