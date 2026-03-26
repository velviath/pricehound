"""
Pydantic models used for API request / response validation.
These are NOT ORM models — asyncpg returns plain dicts/Records.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, EmailStr


# ── Auth ─────────────────────────────────────────────────────────────────────

class UserRegister(BaseModel):
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Products ─────────────────────────────────────────────────────────────────

class TrackRequest(BaseModel):
    url: str


class PricePoint(BaseModel):
    price: float
    checked_at: datetime


class ProductResponse(BaseModel):
    id: int
    url: str
    name: Optional[str]
    image_url: Optional[str]
    current_price: Optional[float]
    source: Optional[str]
    last_checked: Optional[datetime]
    created_at: datetime
    price_history: list[PricePoint] = []
    ai_insight: Optional[str] = None
    watcher_count: int = 0


# ── Alerts ───────────────────────────────────────────────────────────────────

class AlertCreate(BaseModel):
    product_id: int
    target_price: float
    email: Optional[EmailStr] = None  # for anonymous users; JWT users use account email


class AlertResponse(BaseModel):
    id: int
    product_id: int
    target_price: float
    is_active: bool
    created_at: datetime


# ── Dashboard ────────────────────────────────────────────────────────────────

class DashboardProduct(BaseModel):
    id: int
    url: str
    name: Optional[str]
    image_url: Optional[str]
    current_price: Optional[float]
    source: Optional[str]
    price_24h_ago: Optional[float]
    change_24h: Optional[float]          # absolute
    change_24h_pct: Optional[float]      # percentage
    target_price: Optional[float]
    alert_active: Optional[bool]
    alert_id: Optional[int]


class DashboardSummary(BaseModel):
    total_products: int
    active_alerts: int
    alerts_triggered: int
    products: list[DashboardProduct]
