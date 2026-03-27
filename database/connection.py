"""
Async database connection pool using asyncpg.
Creates all tables on first startup if they do not exist.
"""

import asyncpg
from config import settings

# Module-level pool — initialized once in main.py lifespan
_pool: asyncpg.Pool | None = None


async def create_pool() -> asyncpg.Pool:
    """Create and return the asyncpg connection pool."""
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=2,
        max_size=10,
        command_timeout=60,
    )
    return _pool


async def get_pool() -> asyncpg.Pool:
    """Return the existing pool (must be initialised first)."""
    if _pool is None:
        raise RuntimeError("Database pool has not been initialised.")
    return _pool


async def close_pool() -> None:
    """Gracefully close the pool on shutdown."""
    if _pool:
        await _pool.close()


# ── Schema DDL ───────────────────────────────────────────────────────────────

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    email       TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products (
    id            SERIAL PRIMARY KEY,
    url           TEXT NOT NULL,
    name          TEXT,
    image_url     TEXT,
    current_price DECIMAL,
    source        TEXT,
    last_checked  TIMESTAMP,
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alerts (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
    product_id   INTEGER REFERENCES products(id) ON DELETE CASCADE,
    target_price DECIMAL NOT NULL,
    is_active    BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS price_history (
    id         SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    price      DECIMAL NOT NULL,
    checked_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_products (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, product_id)
);
"""


async def init_db(pool: asyncpg.Pool) -> None:
    """Run DDL to create tables if they don't exist yet."""
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLES_SQL)
