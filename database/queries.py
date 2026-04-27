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


async def update_user_last_visited(conn, user_id: int) -> None:
    await conn.execute(
        "UPDATE users SET last_visited_at = NOW(), inactive_notified_at = NULL WHERE id = $1",
        user_id,
    )


async def get_users_to_notify_inactive(conn) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT id, email FROM users
           WHERE last_visited_at < NOW() - INTERVAL '14 days'
             AND inactive_notified_at IS NULL""",
    )


async def set_inactive_notified(conn, user_id: int) -> None:
    await conn.execute(
        "UPDATE users SET inactive_notified_at = NOW() WHERE id = $1", user_id
    )


# ── Products ──────────────────────────────────────────────────────────────────

async def create_product(
    conn,
    url: str,
    name: Optional[str],
    image_url: Optional[str],
    current_price: Optional[float],
    source: Optional[str],
    currency: str = "USD",
    page_context: Optional[str] = None,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO products (url, name, image_url, current_price, source, currency, page_context, last_checked)
        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
        RETURNING *
        """,
        url, name, image_url, current_price, source, currency, page_context,
    )


async def get_product_by_id(conn, product_id: int) -> Optional[asyncpg.Record]:
    return await conn.fetchrow("SELECT * FROM products WHERE id = $1", product_id)


async def get_product_by_url(conn, url: str) -> Optional[asyncpg.Record]:
    return await conn.fetchrow("SELECT * FROM products WHERE url = $1", url)


async def get_all_products(conn) -> list[asyncpg.Record]:
    """Fetch all products — used by the scheduler."""
    return await conn.fetch("SELECT * FROM products ORDER BY created_at DESC")


async def get_schedulable_products(conn) -> list[asyncpg.Record]:
    """
    Products eligible for auto-tracking:
    - available/unknown (not unavailable/url_error)
    - at least one watcher visited in the last 14 days,
      OR no watchers (demo/unowned products)
    """
    return await conn.fetch(
        """
        SELECT DISTINCT p.*
        FROM products p
        WHERE p.availability NOT IN ('unavailable', 'url_error')
          AND (
            NOT EXISTS (SELECT 1 FROM user_products up WHERE up.product_id = p.id)
            OR EXISTS (
                SELECT 1 FROM user_products up
                JOIN users u ON u.id = up.user_id
                WHERE up.product_id = p.id
                  AND u.last_visited_at >= NOW() - INTERVAL '14 days'
            )
          )
        ORDER BY p.created_at DESC
        """
    )


async def count_user_products(conn, user_id: int) -> int:
    row = await conn.fetchrow(
        "SELECT COUNT(*) FROM user_products WHERE user_id = $1", user_id
    )
    return row["count"]


async def update_product_ai_insight(conn, product_id: int, insight: str) -> None:
    await conn.execute(
        "UPDATE products SET ai_insight = $1 WHERE id = $2", insight, product_id
    )


async def update_product_market_analysis(conn, product_id: int, analysis: str) -> None:
    await conn.execute(
        "UPDATE products SET market_analysis = $1 WHERE id = $2", analysis, product_id
    )


async def update_product_price(
    conn, product_id: int, price: float, currency: Optional[str] = None,
    page_context: Optional[str] = None,
) -> None:
    if currency and page_context:
        await conn.execute(
            "UPDATE products SET current_price=$1, currency=$2, page_context=$3, last_checked=NOW() WHERE id=$4",
            price, currency, page_context, product_id,
        )
    elif currency:
        await conn.execute(
            "UPDATE products SET current_price=$1, currency=$2, last_checked=NOW() WHERE id=$3",
            price, currency, product_id,
        )
    elif page_context:
        await conn.execute(
            "UPDATE products SET current_price=$1, page_context=$2, last_checked=NOW() WHERE id=$3",
            price, page_context, product_id,
        )
    else:
        await conn.execute(
            "UPDATE products SET current_price=$1, last_checked=NOW() WHERE id=$2",
            price, product_id,
        )


async def touch_last_checked(conn, product_id: int) -> None:
    await conn.execute(
        "UPDATE products SET last_checked = NOW() WHERE id = $1",
        product_id,
    )


async def update_product_availability(conn, product_id: int, availability: str) -> None:
    await conn.execute(
        "UPDATE products SET availability = $1 WHERE id = $2",
        availability, product_id,
    )


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
    Return all products the user tracks (via user_products), with their
    optional alert and the price from 24 hours ago for change calculation.
    """
    return await conn.fetch(
        """
        SELECT
            p.id,
            p.url,
            p.name,
            p.image_url,
            p.current_price,
            p.currency,
            p.source,
            p.availability,
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
        FROM user_products up
        JOIN products p ON p.id = up.product_id
        LEFT JOIN alerts a ON a.product_id = p.id AND a.user_id = up.user_id
        WHERE up.user_id = $1
        ORDER BY up.created_at DESC
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
        "SELECT COUNT(*) FROM user_products WHERE product_id = $1",
        product_id,
    )
    return row["count"]


# ── User products (tracking without alert) ────────────────────────────────────

async def add_user_product(conn, user_id: int, product_id: int) -> None:
    await conn.execute(
        "INSERT INTO user_products (user_id, product_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        user_id, product_id,
    )


async def remove_user_product(conn, user_id: int, product_id: int) -> None:
    await conn.execute(
        "DELETE FROM user_products WHERE user_id = $1 AND product_id = $2",
        user_id, product_id,
    )


# ── Password reset ────────────────────────────────────────────────────────────

async def create_reset_token(conn, user_id: int, code: str) -> None:
    await conn.execute("DELETE FROM password_reset_tokens WHERE user_id = $1", user_id)
    await conn.execute(
        """INSERT INTO password_reset_tokens (user_id, code, expires_at)
           VALUES ($1, $2, NOW() + INTERVAL '15 minutes')""",
        user_id, code,
    )


async def get_valid_reset_token(conn, user_id: int, code: str):
    return await conn.fetchrow(
        """SELECT * FROM password_reset_tokens
           WHERE user_id = $1 AND code = $2
             AND expires_at > NOW() AND used = FALSE""",
        user_id, code,
    )


async def mark_reset_token_used(conn, user_id: int) -> None:
    await conn.execute(
        "UPDATE password_reset_tokens SET used = TRUE WHERE user_id = $1", user_id
    )


async def update_user_password(conn, user_id: int, password_hash: str) -> None:
    await conn.execute(
        "UPDATE users SET password_hash = $1 WHERE id = $2", password_hash, user_id
    )


async def get_user_product(conn, user_id: int, product_id: int) -> Optional[asyncpg.Record]:
    return await conn.fetchrow(
        "SELECT * FROM user_products WHERE user_id = $1 AND product_id = $2",
        user_id, product_id,
    )


async def get_user_alert_for_product(conn, user_id: int, product_id: int) -> Optional[asyncpg.Record]:
    return await conn.fetchrow(
        "SELECT * FROM alerts WHERE user_id = $1 AND product_id = $2",
        user_id, product_id,
    )
