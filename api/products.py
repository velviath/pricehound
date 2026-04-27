"""
Product API endpoints.
"""

import logging
from datetime import datetime, timedelta, timezone

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth.utils import get_current_user, get_optional_user
from database.connection import get_pool
from database.models import TrackRequest, ProductResponse, PricePoint
import database.queries as q
from services.parser import parse_product, _detect_source, normalize_amazon_url, normalize_ebay_url
from services.openai_service import get_price_insight, get_market_analysis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/products", tags=["products"])


# ── Demo products ──────────────────────────────────────────────────────────────
# These 3 products are seeded on startup so the landing page always has
# working product-page links. No user account is required.

_DEMO_PRODUCTS = [
    {
        "url": "https://www.amazon.com/dp/B09XS7JWHH",
        "name": "Sony WH-1000XM5 Wireless Noise Canceling Headphones",
        "current_price": 279.99,
        "image_url": "/static/img/sony-wh1000xm5.jpg",
        "source": "Amazon",
        "history": [349.99, 329.99, 299.99, 309.99, 289.99, 279.99],
    },
    {
        "url": "https://www.amazon.com/dp/B0BDHWDR12",
        "name": "Apple AirPods Pro (2nd Generation) — USB‑C",
        "current_price": 189.99,
        "image_url": "/static/img/airpods-pro.jpg",
        "source": "Amazon",
        "history": [229.99, 219.99, 215.00, 209.99, 199.99, 189.99],
    },
    {
        "url": "https://www.amazon.com/dp/B09TMF6742",
        "name": "Kindle Paperwhite (16 GB) — Now with 3 months Kindle Unlimited",
        "current_price": 139.99,
        "image_url": "/static/img/kindle-paperwhite.jpg",
        "source": "Amazon",
        "history": [159.99, 149.99, 145.00, 139.99, 129.99, 139.99],
    },
]


_DEMO_PRICE_EVENTS = {
    "https://www.amazon.com/dp/B09XS7JWHH": [
        {"days_ago": 180, "price": 349.99},
        {"days_ago": 150, "price": 329.99},
        {"days_ago": 90,  "price": 299.99},
        {"days_ago": 75,  "price": 309.99},
        {"days_ago": 55,  "price": 289.99},
        {"days_ago": 14,  "price": 279.99},
    ],
    "https://www.amazon.com/dp/B0BDHWDR12": [
        {"days_ago": 180, "price": 229.99},
        {"days_ago": 120, "price": 215.00},
        {"days_ago": 95,  "price": 219.99},
        {"days_ago": 70,  "price": 209.99},
        {"days_ago": 40,  "price": 199.99},
        {"days_ago": 10,  "price": 189.99},
    ],
    "https://www.amazon.com/dp/B09TMF6742": [
        {"days_ago": 180, "price": 159.99},
        {"days_ago": 140, "price": 149.99},
        {"days_ago": 100, "price": 139.99},
        {"days_ago": 60,  "price": 134.99},
        {"days_ago": 30,  "price": 129.99},
        {"days_ago": 6,   "price": 139.99},
    ],
}


def _generate_price_history(events: list, now: datetime) -> list:
    """
    events: list of dicts {days_ago: int, price: float}, any order.
    Returns list of (timestamp, price) tuples, oldest first.
    """
    sorted_events = sorted(events, key=lambda e: e["days_ago"], reverse=True)  # oldest first
    points = []
    for idx, event in enumerate(sorted_events):
        seg_start = now - timedelta(days=event["days_ago"])
        seg_end = now - timedelta(days=sorted_events[idx + 1]["days_ago"]) if idx + 1 < len(sorted_events) else now
        price = event["price"]
        ts = seg_start
        while ts < seg_end:
            days_from_now = (now - ts).days
            if days_from_now > 30:
                step = timedelta(hours=24)
            elif days_from_now > 7:
                step = timedelta(hours=8)
            else:
                step = timedelta(hours=4)
            points.append((ts, price))
            ts += step
    return points


async def seed_demo_products() -> None:
    """Create the 3 demo products on startup with rich price history."""
    try:
        pool = await get_pool()
        now = datetime.utcnow()
        async with pool.acquire() as conn:
            for demo in _DEMO_PRODUCTS:
                existing = await q.get_product_by_url(conn, demo["url"])
                if existing:
                    count = await conn.fetchval(
                        "SELECT COUNT(*) FROM price_history WHERE product_id=$1", existing["id"]
                    )
                    price_current = (
                        existing["current_price"] is not None
                        and abs(float(existing["current_price"]) - demo["current_price"]) < 0.01
                    )
                    if count >= 5 and price_current:
                        continue  # Already has rich history with correct price
                    await conn.execute("DELETE FROM price_history WHERE product_id=$1", existing["id"])
                    product_id = existing["id"]
                else:
                    product = await q.create_product(
                        conn,
                        url=demo["url"],
                        name=demo["name"],
                        image_url=demo["image_url"],
                        current_price=demo["current_price"],
                        source=demo["source"],
                        currency="USD",
                    )
                    product_id = product["id"]

                events = _DEMO_PRICE_EVENTS.get(demo["url"], [])
                history_points = _generate_price_history(events, now)
                for ts, price in history_points:
                    await conn.execute(
                        "INSERT INTO price_history (product_id, price, checked_at) VALUES ($1, $2, $3)",
                        product_id, price, ts,
                    )
                await conn.execute(
                    """UPDATE products
                       SET current_price=$1, currency='USD', source=$2,
                           name=$3, image_url=$4, last_checked=NOW()
                       WHERE id=$5""",
                    demo["current_price"], demo["source"],
                    demo["name"], demo["image_url"], product_id,
                )
        logger.info("Demo products seeded.")
    except Exception as exc:
        logger.warning("Could not seed demo products: %s", exc)


@router.get("/demo")
async def get_demo_products():
    """Return IDs of the 3 demo products for the landing page cards."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = []
        for demo in _DEMO_PRODUCTS:
            p = await q.get_product_by_url(conn, demo["url"])
            if p:
                watchers = await q.count_product_watchers(conn, p["id"])
                result.append({
                    "id": p["id"],
                    "current_price": float(p["current_price"]) if p["current_price"] else None,
                    "last_checked": p["last_checked"].isoformat() if p["last_checked"] else None,
                    "watcher_count": watchers,
                })
        return result


@router.get("/recent")
async def get_recent_products():
    """
    Return the 3 most recently added products for the landing page.
    Public endpoint — no auth required.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        products = await q.get_recently_tracked_products(conn, limit=3)
        result = []
        for p in products:
            history = await q.get_price_history(conn, p["id"])
            result.append({
                "id": p["id"],
                "url": p["url"],
                "name": p["name"],
                "image_url": p["image_url"],
                "current_price": float(p["current_price"]) if p["current_price"] else None,
                "source": p["source"],
                "price_history": [
                    {"price": float(h["price"]), "checked_at": h["checked_at"].isoformat()}
                    for h in history
                ],
            })
    return result


@router.post("/track", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def track_product(body: TrackRequest):
    """
    Parse the given URL and start tracking it.
    If the URL has been tracked before, return the existing record
    (avoids duplicates in the database).
    """
    url = normalize_amazon_url(str(body.url).strip())
    url = normalize_ebay_url(url)

    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await q.get_product_by_url(conn, url)

    if existing:
        # Fix source if stale
        correct_source = _detect_source(url)
        if existing["source"] != correct_source:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE products SET source=$1 WHERE id=$2",
                    correct_source, existing["id"],
                )
        # Do a fresh parse outside the connection (I/O heavy)
        try:
            data = await parse_product(url)
            availability = data.get("availability", "available")
            async with pool.acquire() as conn:
                if data.get("price"):
                    await q.update_product_price(conn, existing["id"], data["price"], data.get("currency"), data.get("page_context"))
                await q.update_product_availability(conn, existing["id"], availability)
        except ValueError:
            pass  # silently skip if parse fails on re-add
        async with pool.acquire() as conn:
            existing = await q.get_product_by_id(conn, existing["id"])
            history = await q.get_price_history(conn, existing["id"])
            watchers = await q.count_product_watchers(conn, existing["id"])
        return _build_response(existing, history, watchers)

    # Parse the page (raises ValueError with user-friendly message on failure)
    try:
        data = await parse_product(url)
    except ValueError as exc:
        err = str(exc)
        detail = err.removeprefix("[URL_ERROR] ")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)

    availability = data.get("availability", "available")
    if availability == "url_error":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This product page no longer exists. The listing may have been removed.",
        )
    if availability == "unavailable":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This product is no longer available and cannot be added for tracking.",
        )

    async with pool.acquire() as conn:
        product = await q.create_product(
            conn,
            url=url,
            name=data.get("name"),
            image_url=data.get("image_url"),
            current_price=data.get("price"),
            source=data.get("source"),
            currency=data.get("currency", "USD"),
            page_context=data.get("page_context"),
        )
        if data.get("price"):
            await q.insert_price_history(conn, product["id"], data["price"])

        history = await q.get_price_history(conn, product["id"])
        watchers = await q.count_product_watchers(conn, product["id"])

    return _build_response(product, history, watchers)


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    period: Optional[str] = Query(default="all", pattern="^(week|month|all)$"),
    display_currency: Optional[str] = Query(default=None, pattern="^[A-Z]{3}$"),
):
    """
    Return product details, price history, AI insight, and watcher count.
    *period* filters the history: 'week' | 'month' | 'all'.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        product = await q.get_product_by_id(conn, product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found.")

        since = _period_to_since(period)
        history = await q.get_price_history(conn, product_id, since=since)
        # Always use full all-time history for AI so analysis isn't limited to the selected period
        ai_history = history if period == "all" else await q.get_price_history(conn, product_id, since=None)
        watchers = await q.count_product_watchers(conn, product_id)

    cached_insight = product["ai_insight"] if "ai_insight" in product else None

    # Lazily generate insight once if it has never been set (e.g. column just added)
    if not cached_insight and ai_history:
        history_dicts = [{"price": float(h["price"]), "checked_at": h["checked_at"]} for h in ai_history]
        cached_insight = await get_price_insight(
            product_name=product["name"],
            current_price=float(product["current_price"]) if product["current_price"] else None,
            currency=product["currency"] or "USD",
            price_history=history_dicts,
            page_context=product["page_context"] if "page_context" in product else None,
        )
        if cached_insight:
            async with pool.acquire() as conn:
                await q.update_product_ai_insight(conn, product_id, cached_insight)

    response = _build_response(product, history, watchers)
    response.ai_insight = cached_insight
    return response


@router.get("/{product_id}/history")
async def get_history(
    product_id: int,
    period: Optional[str] = Query(default="all", pattern="^(week|month|all)$"),
):
    """Return price history as a JSON array for the Chart.js graph."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        product = await q.get_product_by_id(conn, product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found.")
        since = _period_to_since(period)
        history = await q.get_price_history(conn, product_id, since=since)

    return [
        {"price": float(h["price"]), "checked_at": h["checked_at"].isoformat()}
        for h in history
    ]


@router.get("/{product_id}/status")
async def get_product_status(product_id: int):
    """Lightweight endpoint for live polling — returns current price + last_checked only."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        product = await q.get_product_by_id(conn, product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found.")
    return {
        "current_price": float(product["current_price"]) if product["current_price"] else None,
        "last_checked": product["last_checked"].isoformat() if product["last_checked"] else None,
    }


@router.get("/{product_id}/user-status")
async def get_user_status(
    product_id: int,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Return the authenticated user's tracking and alert state for this product."""
    if not current_user:
        return {"tracking": False, "alert": None, "pause_reason": None}

    user_id = int(current_user["sub"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        tracking = await q.get_user_product(conn, user_id, product_id)
        alert = await q.get_user_alert_for_product(conn, user_id, product_id)
        product = await q.get_product_by_id(conn, product_id)
        user = await q.get_user_by_id(conn, user_id)

    # Compute pause_reason BEFORE updating last_visited so we read the real stale timestamp
    pause_reason = None
    if product:
        avail = product["availability"] if "availability" in product else "available"
        if avail in ("unavailable", "url_error"):
            pause_reason = "unavailable"
        elif user and user.get("last_visited_at"):
            last_visit = user["last_visited_at"]
            if last_visit.tzinfo is None:
                last_visit = last_visit.replace(tzinfo=timezone.utc)
            days_inactive = (datetime.now(timezone.utc) - last_visit).days
            if days_inactive >= 14:
                pause_reason = "inactive"

    return {
        "tracking": tracking is not None,
        "alert": {
            "id": alert["id"],
            "target_price": float(alert["target_price"]),
            "is_active": alert["is_active"],
        } if alert else None,
        "pause_reason": pause_reason,
    }


@router.post("/{product_id}/add", status_code=status.HTTP_201_CREATED)
async def add_product_to_tracking(
    product_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Add a product to the authenticated user's tracking list (no alert required)."""
    user_id = int(current_user["sub"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        product = await q.get_product_by_id(conn, product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found.")
        existing = await q.get_user_product(conn, user_id, product_id)
        if not existing:
            count = await q.count_user_products(conn, user_id)
            if count >= 5:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="You've reached the 5-product limit. Remove a product to add a new one.",
                )
        await q.add_user_product(conn, user_id, product_id)
    return {"ok": True}


@router.delete("/{product_id}/add", status_code=status.HTTP_204_NO_CONTENT)
async def remove_product_from_tracking(
    product_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Remove a product from tracking (also deletes any alert for it)."""
    user_id = int(current_user["sub"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        alert = await q.get_user_alert_for_product(conn, user_id, product_id)
        if alert:
            await q.delete_alert(conn, alert["id"])
        await q.remove_user_product(conn, user_id, product_id)


@router.post("/{product_id}/refresh")
async def refresh_product_price(
    product_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Re-parse the product page right now and update the stored price."""
    user_id = int(current_user["sub"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        product = await q.get_product_by_id(conn, product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found.")
        url = str(product["url"])
        await q.update_user_last_visited(conn, user_id)

    try:
        data = await parse_product(url)
    except ValueError as exc:
        # Update last_checked but do NOT change availability — HTTP errors (404, bot-block)
        # are transient and should not permanently mark a product as broken.
        async with pool.acquire() as conn:
            await q.touch_last_checked(conn, product_id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc).removeprefix("[URL_ERROR] "),
        )

    availability = data.get("availability", "available")
    async with pool.acquire() as conn:
        # Persist canonical URL if it differs (e.g. amzn.eu short link → amazon.co.uk/dp/ASIN)
        canonical = data.get("canonical_url")
        if canonical and canonical != url:
            logger.info("Updating canonical URL for product %d: %s → %s", product_id, url, canonical)
            await conn.execute("UPDATE products SET url=$1 WHERE id=$2", canonical, product_id)

        if data.get("price") and availability == "available":
            await q.update_product_price(conn, product_id, data["price"], data.get("currency"), data.get("page_context"))
            await q.insert_price_history(conn, product_id, data["price"])
        else:
            await q.touch_last_checked(conn, product_id)
        await q.update_product_availability(conn, product_id, availability)
        product = await q.get_product_by_id(conn, product_id)

    # Regenerate AI price insight after manual refresh
    if data.get("price") and availability == "available":
        history_rows = []
        async with pool.acquire() as conn:
            history_rows = await q.get_price_history(conn, product_id)
        history_dicts = [{"price": float(h["price"]), "checked_at": h["checked_at"]} for h in history_rows]
        insight = await get_price_insight(
            product_name=product["name"],
            price_history=history_dicts,
            current_price=float(product["current_price"]) if product["current_price"] else None,
            source=product["source"],
            currency=product["currency"] or "USD",
            page_context=product["page_context"] if "page_context" in product else None,
        )
        if insight:
            async with pool.acquire() as conn:
                await q.update_product_ai_insight(conn, product_id, insight)

    return {
        "current_price": float(product["current_price"]) if product["current_price"] else None,
        "currency": product["currency"] or "USD",
        "last_checked": product["last_checked"].isoformat() if product["last_checked"] else None,
        "availability": product["availability"] if "availability" in product else "available",
    }


@router.get("/{product_id}/ai-analysis")
async def get_ai_analysis(product_id: int):
    """Return cached market analysis, generating it on first call."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        product = await q.get_product_by_id(conn, product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found.")

    cached = product["market_analysis"] if "market_analysis" in product else None
    if cached:
        return {"analysis": cached}

    analysis = await get_market_analysis(
        product["name"],
        product_id=product_id,
        source=product["source"],
        page_context=product["page_context"] if "page_context" in product else None,
    )
    if analysis:
        async with pool.acquire() as conn:
            await q.update_product_market_analysis(conn, product_id, analysis)
    return {"analysis": analysis}




# ── Helpers ───────────────────────────────────────────────────────────────────

def _period_to_since(period: Optional[str]) -> Optional[datetime]:
    now = datetime.utcnow()  # naive UTC — matches TIMESTAMP columns in PostgreSQL
    if period == "week":
        return now - timedelta(days=7)
    if period == "month":
        return now - timedelta(days=30)
    return None  # all time


def _build_response(product, history, watchers: int) -> ProductResponse:
    raw_source = product["source"] or ""
    # Normalize stale source values from before the amazon.co.uk fix ("Co", "Amzn", etc.)
    source = raw_source if raw_source.lower() not in ("co", "amzn", "www", "") \
        else _detect_source(str(product["url"]))
    availability = "available"
    if "availability" in product:
        availability = product["availability"] or "available"
    return ProductResponse(
        id=product["id"],
        url=product["url"],
        name=product["name"],
        image_url=product["image_url"],
        current_price=float(product["current_price"]) if product["current_price"] else None,
        currency=product["currency"] or "USD",
        source=source,
        last_checked=product["last_checked"],
        created_at=product["created_at"],
        price_history=[
            PricePoint(price=float(h["price"]), checked_at=h["checked_at"])
            for h in history
        ],
        watcher_count=watchers,
        availability=availability,
    )
