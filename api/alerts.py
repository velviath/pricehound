"""
Alert management endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from auth.utils import get_current_user
from database.connection import get_pool
from database.models import AlertCreate, AlertResponse
import database.queries as q

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.post("/", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(
    body: AlertCreate,
    current_user: dict = Depends(get_current_user),
):
    """
    Create a price alert for the authenticated user.
    The user will receive an email when product price ≤ target_price.
    """
    user_id = int(current_user["sub"])

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Ensure the product exists
        product = await q.get_product_by_id(conn, body.product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found.")

        # Prevent duplicate alerts for the same product
        existing = await q.get_user_alert_for_product(conn, user_id, body.product_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already have an alert for this product. Edit or delete it first.",
            )

        # Ensure the product is in the user's tracking list
        await q.add_user_product(conn, user_id, body.product_id)

        alert = await q.create_alert(conn, user_id, body.product_id, body.target_price)

    return AlertResponse(
        id=alert["id"],
        product_id=alert["product_id"],
        target_price=float(alert["target_price"]),
        is_active=alert["is_active"],
        created_at=alert["created_at"],
    )


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Delete an alert owned by the authenticated user."""
    user_id = int(current_user["sub"])

    pool = await get_pool()
    async with pool.acquire() as conn:
        alerts = await q.get_alerts_for_user(conn, user_id)
        alert = next((a for a in alerts if a["id"] == alert_id), None)
        if not alert:
            raise HTTPException(
                status_code=404,
                detail="Alert not found or does not belong to you.",
            )
        await q.delete_alert(conn, alert_id)


@router.patch("/{alert_id}/target", response_model=AlertResponse)
async def update_alert_target(
    alert_id: int,
    target_price: float,
    current_user: dict = Depends(get_current_user),
):
    """Update the target price of an existing alert."""
    user_id = int(current_user["sub"])

    if target_price <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Target price must be greater than 0.",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        alerts = await q.get_alerts_for_user(conn, user_id)
        alert = next((a for a in alerts if a["id"] == alert_id), None)
        if not alert:
            raise HTTPException(
                status_code=404,
                detail="Alert not found or does not belong to you.",
            )
        await q.update_alert_target(conn, alert_id, target_price)
        updated = await conn.fetchrow("SELECT * FROM alerts WHERE id = $1", alert_id)

    return AlertResponse(
        id=updated["id"],
        product_id=updated["product_id"],
        target_price=float(updated["target_price"]),
        is_active=updated["is_active"],
        created_at=updated["created_at"],
    )
