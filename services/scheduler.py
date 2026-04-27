"""
APScheduler background job: checks product prices every N hours.

For each product:
  1. Re-parse the current price.
  2. If it changed, record it in price_history.
  3. Check if any active alerts have their target met.
  4. If so, send the user an email and deactivate the alert.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from database.connection import get_pool
import database.queries as q
from services.parser import parse_product, normalize_amazon_url, normalize_ebay_url
from services.email_service import send_alert_email, send_unavailable_email, send_inactive_email
from services.openai_service import get_price_insight

logger = logging.getLogger(__name__)

# Module-level scheduler instance started in main.py lifespan
scheduler = AsyncIOScheduler()


async def _check_all_prices() -> None:
    """Core job: iterate every tracked product and refresh its price."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        products = await q.get_schedulable_products(conn)

    logger.info("Scheduler: checking prices for %d eligible products", len(products))

    for product in products:
        product_id = product["id"]
        old_price = float(product["current_price"]) if product["current_price"] else None
        url = str(product["url"])

        # Normalize Amazon and eBay URLs on-the-fly (fixes stale/tracking URLs)
        normalized = normalize_ebay_url(normalize_amazon_url(url))
        if normalized != url:
            logger.info("Normalizing URL for product %d: %s", product_id, normalized)
            async with pool.acquire() as conn:
                await conn.execute("UPDATE products SET url=$1 WHERE id=$2", normalized, product_id)
            url = normalized


        try:
            data = await parse_product(url)
            new_price = data.get("price")
            availability = data.get("availability", "available")
        except Exception as exc:
            logger.warning("Failed to parse product %d: %s", product_id, exc)
            async with pool.acquire() as conn:
                await q.touch_last_checked(conn, product_id)
            continue

        if new_price is None:
            async with pool.acquire() as conn:
                await q.touch_last_checked(conn, product_id)
                await q.update_product_availability(conn, product_id, availability)
            continue

        price_changed = old_price is None or abs(new_price - old_price) > 0.001

        async with pool.acquire() as conn:
            canonical = data.get("canonical_url")
            if canonical and canonical != url:
                logger.info("Updating canonical URL for product %d: %s", product_id, canonical)
                await conn.execute("UPDATE products SET url=$1 WHERE id=$2", canonical, product_id)

            if availability == "available":
                await q.update_product_price(conn, product_id, new_price, data.get("currency"), data.get("page_context"))
                await q.insert_price_history(conn, product_id, new_price)
            else:
                await q.touch_last_checked(conn, product_id)
            await q.update_product_availability(conn, product_id, availability)

            # Refresh AI price insight after every successful check
            if availability == "available":
                history = await q.get_price_history(conn, product_id)
                history_dicts = [{"price": float(h["price"]), "checked_at": h["checked_at"]} for h in history]
                insight = await get_price_insight(
                    product_name=product.get("name"),
                    price_history=history_dicts,
                    current_price=new_price,
                    source=product.get("source"),
                    currency=product.get("currency") or "USD",
                    page_context=product.get("page_context"),
                )
                if insight:
                    await q.update_product_ai_insight(conn, product_id, insight)

            if price_changed:
                logger.info(
                    "Product %d price changed: %.2f → %.2f",
                    product_id,
                    old_price or 0,
                    new_price,
                )

            old_availability = str(product.get("availability") or "available")
            if availability == "unavailable" and old_availability == "available":
                logger.info("Product %d just became unavailable — notifying users", product_id)
                trackers = await conn.fetch(
                    "SELECT u.email FROM users u JOIN user_products up ON up.user_id = u.id WHERE up.product_id = $1",
                    product_id,
                )
                for row in trackers:
                    try:
                        await send_unavailable_email(
                            recipient=row["email"],
                            product_name=product.get("name") or product["url"],
                            product_id=product_id,
                            product_image=product.get("image_url"),
                        )
                    except Exception as exc:
                        logger.error("Failed to send unavailable email: %s", exc)

            # Check alerts only if product is still available
            if availability == "available":
                alerts = await q.get_alerts_for_product(conn, product_id)
                for alert in alerts:
                    if new_price <= float(alert["target_price"]):
                        await _trigger_alert(conn, alert, product, old_price or new_price, new_price)


async def _trigger_alert(conn, alert, product, old_price: float, current_price: float) -> None:
    """Send alert email then deactivate. Email is attempted first so a send
    failure does not silently consume the alert."""
    alert_id = alert["id"]
    user_id  = alert["user_id"]

    user = await q.get_user_by_id(conn, user_id)
    if not user:
        await q.deactivate_alert(conn, alert_id)
        return

    try:
        await send_alert_email(
            recipient=user["email"],
            product_name=product["name"] or product["url"],
            old_price=old_price,
            current_price=current_price,
            target_price=float(alert["target_price"]),
            product_id=product["id"],
            product_image=product["image_url"],
            currency=product.get("currency") or "USD",
        )
        logger.info("Alert %d triggered — email sent to %s", alert_id, user["email"])
    except Exception as exc:
        logger.error("Failed to send alert email for alert %d: %s", alert_id, exc)
        return  # leave alert active so next scheduler run retries

    await q.deactivate_alert(conn, alert_id)


async def _notify_inactive_users() -> None:
    """Daily job: email users who've been inactive for 14+ days (once per inactivity period)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        users = await q.get_users_to_notify_inactive(conn)

    logger.info("Inactive check: %d user(s) to notify", len(users))
    for user in users:
        try:
            await send_inactive_email(recipient=user["email"])
            async with pool.acquire() as conn:
                await q.set_inactive_notified(conn, user["id"])
            logger.info("Inactive email sent to %s", user["email"])
        except Exception as exc:
            logger.error("Failed to send inactive email to %s: %s", user["email"], exc)


def start_scheduler() -> None:
    """Add the price-check job and start the scheduler."""
    scheduler.add_job(
        _check_all_prices,
        trigger="interval",
        hours=settings.price_check_interval_hours,
        id="price_check",
        replace_existing=True,
    )
    scheduler.add_job(
        _notify_inactive_users,
        trigger="interval",
        hours=24,
        id="inactive_check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started — checking prices every %d hours",
        settings.price_check_interval_hours,
    )


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
