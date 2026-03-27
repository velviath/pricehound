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
from services.parser import parse_product
from services.email_service import send_alert_email

logger = logging.getLogger(__name__)

# Module-level scheduler instance started in main.py lifespan
scheduler = AsyncIOScheduler()


async def _check_all_prices() -> None:
    """Core job: iterate every tracked product and refresh its price."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        products = await q.get_all_products(conn)

    logger.info("Scheduler: checking prices for %d products", len(products))

    for product in products:
        product_id = product["id"]
        old_price = float(product["current_price"]) if product["current_price"] else None

        try:
            data = await parse_product(product["url"])
            new_price = data.get("price")
        except Exception as exc:
            logger.warning("Failed to parse product %d: %s", product_id, exc)
            continue

        if new_price is None:
            continue

        # Only record a history entry if the price actually changed
        price_changed = old_price is None or abs(new_price - old_price) > 0.001

        async with pool.acquire() as conn:
            # Always update price + last_checked so "Checked X ago" stays accurate
            await q.update_product_price(conn, product_id, new_price)
            # Always record history so "All checks" chart mode has all data points
            await q.insert_price_history(conn, product_id, new_price)

            if price_changed:
                logger.info(
                    "Product %d price changed: %.2f → %.2f",
                    product_id,
                    old_price or 0,
                    new_price,
                )

            # Check alerts even if price didn't change (first run might satisfy one)
            alerts = await q.get_alerts_for_product(conn, product_id)
            for alert in alerts:
                if new_price <= float(alert["target_price"]):
                    await _trigger_alert(conn, alert, product, new_price)


async def _trigger_alert(conn, alert, product, current_price: float) -> None:
    """Deactivate an alert and notify the user via email."""
    alert_id = alert["id"]
    user_id = alert["user_id"]

    # Deactivate first so a concurrent run doesn't double-send
    await q.deactivate_alert(conn, alert_id)

    user = await q.get_user_by_id(conn, user_id)
    if not user:
        return

    try:
        await send_alert_email(
            recipient=user["email"],
            product_name=product["name"] or product["url"],
            current_price=current_price,
            target_price=float(alert["target_price"]),
            product_url=product["url"],
            product_image=product["image_url"],
        )
        logger.info(
            "Alert %d triggered — email sent to %s", alert_id, user["email"]
        )
    except Exception as exc:
        logger.error("Failed to send alert email for alert %d: %s", alert_id, exc)


def start_scheduler() -> None:
    """Add the price-check job and start the scheduler."""
    scheduler.add_job(
        _check_all_prices,
        trigger="interval",
        hours=settings.price_check_interval_hours,
        id="price_check",
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
