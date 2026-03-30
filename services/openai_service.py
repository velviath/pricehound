"""
OpenAI integration for AI price insights.
Uses GPT-4o-mini to generate a short analysis of price history and page context.
"""

from typing import Optional
from openai import AsyncOpenAI
from config import settings

_client: Optional[AsyncOpenAI] = None
_analysis_cache: dict[int, str] = {}  # product_id → cached market analysis


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
) -> Optional[str]:
    """
    Ask GPT-4o-mini to analyse the price history and return 2-3 sentences
    covering: trend, when price usually drops, and a buy recommendation.
    Now includes marketplace, currency and full page context for accuracy.
    """
    if not settings.openai_api_key:
        return None

    if len(price_history) < 2:
        return (
            "Not enough price history yet to generate an AI insight. "
            "Check back after a few days of tracking."
        )

    cur = currency or "USD"
    history_lines = "\n".join(
        f"  {p['checked_at'].strftime('%Y-%m-%d %H:%M')} — {cur} {float(p['price']):.2f}"
        for p in price_history[-60:]
    )

    name_str = f'"{product_name}"' if product_name else "this product"
    current_str = f"{cur} {current_price:.2f}" if current_price else "unknown"
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
    except Exception as exc:
        return f"AI insight temporarily unavailable: {exc}"
