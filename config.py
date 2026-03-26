"""
Application configuration loaded from environment variables.
All settings are read via pydantic-settings so they are validated at startup.
"""

from pydantic_settings import BaseSettings
from pydantic import EmailStr


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql://postgres:postgres@localhost:5432/pricehound"

    # ── JWT ───────────────────────────────────────────────────────────────────
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    # ── OpenAI ────────────────────────────────────────────────────────────────
    openai_api_key: str = ""

    # ── ScraperAPI (optional) ─────────────────────────────────────────────────
    # Enables Amazon, eBay and other bot-protected sites.
    # Free tier: 1000 requests/month — sign up at scraperapi.com
    scraper_api_key: str = ""

    # ── SMTP (email notifications) ────────────────────────────────────────────
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # defaults to smtp_user if empty

    # ── Scheduler ─────────────────────────────────────────────────────────────
    price_check_interval_hours: int = 4

    # ── App ───────────────────────────────────────────────────────────────────
    app_name: str = "PriceHound"
    app_host: str = "http://localhost:8000"
    debug: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Singleton instance used across the app
settings = Settings()
