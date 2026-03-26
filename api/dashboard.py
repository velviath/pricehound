"""
Dashboard endpoint — returns all tracking data for the authenticated user.
"""

from fastapi import APIRouter, Depends

from auth.utils import get_current_user
from database.connection import get_pool
from database.models import DashboardSummary, DashboardProduct
import database.queries as q

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/", response_model=DashboardSummary)
async def get_dashboard(current_user: dict = Depends(get_current_user)):
    """
    Return a full dashboard payload:
      - Summary counts (total products, active alerts, triggered alerts)
      - Per-product data with 24h price change and alert status
    """
    user_id = int(current_user["sub"])

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await q.get_dashboard_data(conn, user_id)
        active_count = await q.count_active_alerts(conn, user_id)
        triggered_count = await q.count_triggered_alerts(conn, user_id)

    products = []
    for row in rows:
        current = float(row["current_price"]) if row["current_price"] else None
        old = float(row["price_24h_ago"]) if row["price_24h_ago"] else None

        change_abs = None
        change_pct = None
        if current is not None and old is not None and old != 0:
            change_abs = current - old
            change_pct = ((current - old) / old) * 100

        products.append(
            DashboardProduct(
                id=row["id"],
                url=row["url"],
                name=row["name"],
                image_url=row["image_url"],
                current_price=current,
                source=row["source"],
                price_24h_ago=old,
                change_24h=change_abs,
                change_24h_pct=change_pct,
                target_price=float(row["target_price"]) if row["target_price"] else None,
                alert_active=row["alert_active"],
                alert_id=row["alert_id"],
            )
        )

    return DashboardSummary(
        total_products=len(products),
        active_alerts=active_count,
        alerts_triggered=triggered_count,
        products=products,
    )
