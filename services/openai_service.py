"""
OpenAI integration for AI price insights.
Uses GPT-4o-mini to generate a short analysis of price history.
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


async def get_market_analysis(product_name: Optional[str], product_id: Optional[int] = None) -> Optional[str]:
    """
    Ask GPT-4o-mini for seasonal/market buying advice based only on the product
    name. Works immediately — no price history required.
    Returns None if the API key is not configured or the call fails.
    """
    if not settings.openai_api_key or not product_name:
        return None

    if product_id and product_id in _analysis_cache:
        return _analysis_cache[product_id]

    prompt = (
        f"You are a smart shopping assistant. A user is considering buying: \"{product_name}\".\n\n"
        f"Give them 2-3 sentences of actionable buying advice covering:\n"
        f"1. When prices for this type of product typically drop "
        f"(seasonal sales, Prime Day, Black Friday, back-to-school, etc.).\n"
        f"2. Whether it is generally better to buy now or wait for a specific upcoming sale period.\n"
        f"Be specific, practical, and direct. Do not use bullet points."
    )

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=180,
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
    price_history: list[dict],  # list of {"price": float, "checked_at": datetime}
    current_price: Optional[float],
) -> Optional[str]:
    """
    Ask GPT-4o-mini to analyse the price history and return 2-3 sentences
    covering: trend, when price usually drops, and a buy recommendation.

    Returns None if the API key is not configured or the call fails.
    """
    if not settings.openai_api_key:
        return None

    if len(price_history) < 2:
        return (
            "Not enough price history yet to generate an AI insight. "
            "Check back after a few days of tracking."
        )

    # Build a compact text representation of the history
    history_lines = "\n".join(
        f"  {p['checked_at'].strftime('%Y-%m-%d %H:%M')} — ${float(p['price']):.2f}"
        for p in price_history[-60:]  # cap at last 60 data points
    )

    name_str = f'"{product_name}"' if product_name else "this product"
    current_str = f"${current_price:.2f}" if current_price else "unknown"

    prompt = (
        f"You are a shopping assistant analysing price trends. "
        f"Below is the price history for {name_str} (current price: {current_str}).\n\n"
        f"Price history (UTC timestamps):\n{history_lines}\n\n"
        f"Write exactly 2-3 sentences in English covering:\n"
        f"1. The overall price trend (rising / falling / stable).\n"
        f"2. When the price tends to be lowest (if determinable).\n"
        f"3. Whether now is a good time to buy.\n"
        f"Be direct and actionable. Do not use bullet points."
    )

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.4,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        # Fail gracefully — insight is a nice-to-have, not critical
        return f"AI insight temporarily unavailable: {exc}"
