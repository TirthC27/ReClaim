"""
Project Flow — Application settings.

Reads from .env via pydantic-settings.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Supabase
    SUPABASE_URL: str
    SUPABASE_KEY: str

    # Razorpay
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""

    FRONTEND_BASE_URL: str = "http://localhost:5173"

    # OpenRouter (LLM)
    OPENROUTER_API_KEY: str = ""

    # Shopify
    SHOPIFY_STORE_URL: str = ""
    SHOPIFY_ADMIN_TOKEN: str = ""
    SHOPIFY_CLIENT_ID: str = ""
    SHOPIFY_CLIENT_SECRET: str = ""
    SHOPIFY_WEBHOOK_SECRET: str = ""

    # Abandonment detection
    ABANDONMENT_TIMEOUT_MINUTES: int = 2  # 1-2 for demo, 10+ for production

    # Section 9A merchant selection — PLACEHOLDER VALUES pending final formula
    SMALL_POOL_THRESHOLD: int = 5       # pools below this → single best merchant
    DEMAND_PER_MERCHANT: int = 5        # signals-per-merchant ratio for large pools
    TIE_TOLERANCE_PCT: float = 3.0      # 9A.2: ±% of top score = "genuinely comparable"

    # Payment link expiry
    PAYMENT_EXPIRY_HOURS: int = 8        # Razorpay payment link TTL

    # Server
    PORT: int = 8000


settings = Settings()  # type: ignore[call-arg]
