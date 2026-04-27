"""
OpenAI integration for AI price insights.
Uses GPT-4o-mini to generate a short analysis of price history and page context.
"""

import time
from typing import Optional
import httpx
from openai import AsyncOpenAI
from config import settings

_client: Optional[AsyncOpenAI] = None
_analysis_cache: dict[int, str] = {}  # product_id → cached market analysis

# Simple in-memory cache for exchange rates (refreshed every hour)
_rates_cache: dict = {}
_rates_fetched_at: float = 0.0


async def _get_rates() -> dict:
    global _rates_cache, _rates_fetched_at
    if _rates_cache and (time.time() - _rates_fetched_at) < 3600:
        return _rates_cache
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get("https://open.er-api.com/v6/latest/USD")
            data = r.json()
            if data.get("result") == "success":
                _rates_cache = data["rates"]
                _rates_fetched_at = time.time()
    except Exception:
        pass
    return _rates_cache


def _convert_price(amount: float, from_cur: str, to_cur: str, rates: dict) -> float:
    """Convert amount from from_cur to to_cur via USD as base."""
    if from_cur == to_cur or not rates:
        return amount
    from_rate = 1.0 if from_cur == "USD" else rates.get(from_cur, 0)
    to_rate   = 1.0 if to_cur   == "USD" else rates.get(to_cur,   0)
    if not from_rate or not to_rate:
        return amount
    return (amount / from_rate) * to_rate


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def get_market_analysis(
    product_name: Optional[str],
    product_id: Optional[int] = None,
    source: Optional[str] = None,
    page_context: Optional[str] = None,
) -> Optional[str]:
    """
    Ask GPT-4o-mini for seasonal/market buying advice.
    Includes marketplace context and page text when available.
    Returns None if the API key is not configured or the call fails.
    """
    if not settings.openai_api_key or not product_name:
        return None

    if product_id and product_id in _analysis_cache:
        return _analysis_cache[product_id]

    marketplace_note = f" sold on {source}" if source else ""
    _secondhand = source and source.lower() in ("ebay", "vinted", "depop", "etsy", "gumtree", "craigslist")
    secondhand_note = (
        "\nIMPORTANT: This is a secondhand/resale marketplace listing. "
        "Do NOT suggest waiting for Black Friday, Prime Day or other retail sales — "
        "those do not apply here. Instead focus on resale market dynamics, "
        "condition, and whether the asking price is reasonable for the secondhand market."
    ) if _secondhand else ""
    context_section = (
        f"\n\nHere is additional context scraped from the product page:\n{page_context[:2000]}"
        if page_context else ""
    )

    prompt = (
        f"You are a smart shopping assistant. A user is considering buying: \"{product_name}\"{marketplace_note}.\n"
        f"Give them 2-3 sentences of actionable buying advice covering:\n"
        f"1. Whether this is a good deal given the marketplace (e.g. eBay secondhand vs official store).\n"
        f"2. When prices for this type of product typically drop (if applicable).\n"
        f"3. Whether it is better to buy now or wait.\n"
        f"Be specific and practical. Do not use bullet points.{secondhand_note}{context_section}"
    )

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.5,
        )
        result = response.choices[0].message.content.strip()
        if product_id:
            _analysis_cache[product_id] = result
        return result
    except Exception:
        return None


async def get_price_insight(
    product_name: Optional[str],
    price_history: list[dict],
    current_price: Optional[float],
    source: Optional[str] = None,
    currency: Optional[str] = None,
    page_context: Optional[str] = None,
    display_currency: Optional[str] = None,
) -> Optional[str]:
    """
    Ask GPT-4o-mini to analyse the price history and return 2-3 sentences.
    If display_currency differs from currency, prices are converted before sending.
    """
    if not settings.openai_api_key:
        return None

    if len(price_history) < 2:
        return (
            "Not enough price history yet to generate an AI insight. "
            "Check back after a few days of tracking."
        )

    native_cur = currency or "USD"
    cur = display_currency or native_cur

    # Convert prices to display currency if needed
    if cur != native_cur:
        rates = await _get_rates()
        def _conv(p): return _convert_price(float(p), native_cur, cur, rates)
    else:
        def _conv(p): return float(p)

    history_lines = "\n".join(
        f"  {p['checked_at'].strftime('%Y-%m-%d %H:%M')} — {cur} {_conv(p['price']):.2f}"
        for p in price_history[-60:]
    )

    name_str = f'"{product_name}"' if product_name else "this product"
    conv_price = _conv(current_price) if current_price else None
    current_str = f"{cur} {conv_price:.2f}" if conv_price else "unknown"
    marketplace_note = f" (listed on {source})" if source else ""
    _secondhand = source and source.lower() in ("ebay", "vinted", "depop", "etsy", "gumtree", "craigslist")
    secondhand_note = (
        "\nIMPORTANT: This is a secondhand/resale listing. "
        "Do NOT mention retail sale events (Black Friday, Prime Day, etc.) — they do not apply. "
        "Focus on resale market trends, condition and whether the price is fair for the secondhand market."
    ) if _secondhand else ""
    context_section = (
        f"\n\nAdditional context from the product page:\n{page_context[:2000]}"
        if page_context else ""
    )

    prompt = (
        f"You are a shopping assistant analysing price trends. "
        f"Below is the price history for {name_str}{marketplace_note} (current price: {current_str}).\n\n"
        f"Price history ({cur}, UTC timestamps):\n{history_lines}\n"
        f"Write exactly 2-3 sentences in English covering:\n"
        f"1. The overall price trend (rising / falling / stable).\n"
        f"2. Whether now is a good time to buy, considering the marketplace and any context below.\n"
        f"3. Any notable observations (e.g. secondhand condition, seller info, or seasonal patterns).\n"
        f"Be direct. Do not use bullet points.{secondhand_note}{context_section}"
    )

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=220,
            temperature=0.4,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return None


async def check_product_availability(page_title: str, page_context: str) -> bool:
    """
    Ask GPT-4o-mini whether the product is still available for purchase.
    Returns True if available, False if unavailable (ended, sold, out of stock, etc.).
    Falls back to True (assume available) if the API key is missing or call fails.
    """
    if not settings.openai_api_key:
        return True

    prompt = (
        "You are analyzing an e-commerce product page to determine if the item is still available for purchase.\n\n"
        f"Page title: {page_title}\n\n"
        f"Page content (first 2000 chars):\n{page_context[:2000]}\n\n"
        "Is this product currently available for purchase? "
        "Consider signals like 'listing ended', 'sold', 'out of stock', 'unavailable', 'item removed', etc.\n"
        "Reply with a single word: AVAILABLE or UNAVAILABLE."
    )

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0,
        )
        answer = response.choices[0].message.content.strip().upper()
        return "UNAVAILABLE" not in answer
    except Exception:
        return True  # safe fallback: assume available
