"""
All database queries as async functions.
Every query accepts an asyncpg Connection or Pool as its first argument.
Parameterised queries are used everywhere to prevent SQL injection.
"""

from datetime import datetime, timedelta
from typing import Optional
import asyncpg


# ── Users ─────────────────────────────────────────────────────────────────────

async def create_user(conn, email: str, password_hash: str) -> asyncpg.Record:
    return await conn.fetchrow(
        "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING *",
        email, password_hash,
    )


async def get_user_by_email(conn, email: str) -> Optional[asyncpg.Record]:
    return await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)


async def get_user_by_id(conn, user_id: int) -> Optional[asyncpg.Record]:
    return await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)


# ── Products ──────────────────────────────────────────────────────────────────

async def create_product(
    conn,
    url: str,
    name: Optional[str],
    image_url: Optional[str],
    current_price: Optional[float],
    source: Optional[str],
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO products (url, name, image_url, current_price, source, last_checked)
        VALUES ($1, $2, $3, $4, $5, NOW())
        RETURNING *
        """,
        url, name, image_url, current_price, source,
    )


async def get_product_by_id(conn, product_id: int) -> Optional[asyncpg.Record]:
    return await conn.fetchrow("SELECT * FROM products WHERE id = $1", product_id)


async def get_product_by_url(conn, url: str) -> Optional[asyncpg.Record]:
    return await conn.fetchrow("SELECT * FROM products WHERE url = $1", url)


async def get_all_products(conn) -> list[asyncpg.Record]:
    """Fetch all products — used by the scheduler."""
    return await conn.fetch("SELECT * FROM products ORDER BY created_at DESC")


async def update_product_price(
    conn, product_id: int, price: float
) -> None:
    await conn.execute(
        "UPDATE products SET current_price = $1, last_checked = NOW() WHERE id = $2",
        price, product_id,
    )


async def delete_product(conn, product_id: int) -> None:
    await conn.execute("DELETE FROM products WHERE id = $1", product_id)


async def get_recently_tracked_products(conn, limit: int = 3) -> list[asyncpg.Record]:
    """Return the most recently added products for the landing page."""
    return await conn.fetch(
        "SELECT * FROM products ORDER BY created_at DESC LIMIT $1", limit
    )


# ── Price history ─────────────────────────────────────────────────────────────

async def insert_price_history(conn, product_id: int, price: float) -> None:
    await conn.execute(
        "INSERT INTO price_history (product_id, price) VALUES ($1, $2)",
        product_id, price,
    )


async def get_price_history(
    conn, product_id: int, since: Optional[datetime] = None
) -> list[asyncpg.Record]:
    if since:
        return await conn.fetch(
            """
            SELECT price, checked_at
            FROM price_history
            WHERE product_id = $1 AND checked_at >= $2
            ORDER BY checked_at ASC
            """,
            product_id, since,
        )
    return await conn.fetch(
        """
        SELECT price, checked_at
        FROM price_history
        WHERE product_id = $1
        ORDER BY checked_at ASC
        """,
        product_id,
    )


async def get_price_24h_ago(conn, product_id: int) -> Optional[float]:
    """Return the price closest to 24 hours ago for change calculation."""
    row = await conn.fetchrow(
        """
        SELECT price FROM price_history
        WHERE product_id = $1 AND checked_at >= NOW() - INTERVAL '25 hours'
        ORDER BY checked_at ASC
        LIMIT 1
        """,
        product_id,
    )
    return float(row["price"]) if row else None


# ── Alerts ────────────────────────────────────────────────────────────────────

async def create_alert(
    conn,
    user_id: int,
    product_id: int,
    target_price: float,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO alerts (user_id, product_id, target_price)
        VALUES ($1, $2, $3)
        RETURNING *
        """,
        user_id, product_id, target_price,
    )


async def get_alerts_for_product(conn, product_id: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT * FROM alerts WHERE product_id = $1 AND is_active = TRUE",
        product_id,
    )


async def get_alerts_for_user(conn, user_id: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT * FROM alerts WHERE user_id = $1",
        user_id,
    )


async def deactivate_alert(conn, alert_id: int) -> None:
    await conn.execute(
        "UPDATE alerts SET is_active = FALSE WHERE id = $1", alert_id
    )


async def delete_alert(conn, alert_id: int) -> None:
    await conn.execute("DELETE FROM alerts WHERE id = $1", alert_id)


async def update_alert_target(conn, alert_id: int, target_price: float) -> None:
    await conn.execute(
        "UPDATE alerts SET target_price = $1 WHERE id = $2",
        target_price, alert_id,
    )


# ── Dashboard ─────────────────────────────────────────────────────────────────

async def get_dashboard_data(conn, user_id: int) -> list[asyncpg.Record]:
    """
    Return products the user tracks, joined with their active alert and
    the price from 24 hours ago for change calculation.
    """
    return await conn.fetch(
        """
        SELECT
            p.id,
            p.url,
            p.name,
            p.image_url,
            p.current_price,
            p.source,
            a.id          AS alert_id,
            a.target_price,
            a.is_active   AS alert_active,
            (
                SELECT ph.price
                FROM price_history ph
                WHERE ph.product_id = p.id
                  AND ph.checked_at >= NOW() - INTERVAL '25 hours'
                ORDER BY ph.checked_at ASC
                LIMIT 1
            ) AS price_24h_ago
        FROM alerts a
        JOIN products p ON p.id = a.product_id
        WHERE a.user_id = $1
        ORDER BY a.created_at DESC
        """,
        user_id,
    )


async def count_active_alerts(conn, user_id: int) -> int:
    row = await conn.fetchrow(
        "SELECT COUNT(*) FROM alerts WHERE user_id = $1 AND is_active = TRUE",
        user_id,
    )
    return row["count"]


async def count_triggered_alerts(conn, user_id: int) -> int:
    row = await conn.fetchrow(
        "SELECT COUNT(*) FROM alerts WHERE user_id = $1 AND is_active = FALSE",
        user_id,
    )
    return row["count"]


async def count_product_watchers(conn, product_id: int) -> int:
    row = await conn.fetchrow(
        "SELECT COUNT(*) FROM alerts WHERE product_id = $1 AND is_active = TRUE",
        product_id,
    )
    return row["count"]
