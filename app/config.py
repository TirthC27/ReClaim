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

    # OpenRouter (LLM)
    OPENROUTER_API_KEY: str = ""

    # Shopify
    SHOPIFY_STORE_URL: str = ""
    SHOPIFY_ADMIN_TOKEN: str = ""
    SHOPIFY_CLIENT_ID: str = ""
    SHOPIFY_CLIENT_SECRET: str = ""

    # Server
    PORT: int = 8000


settings = Settings()  # type: ignore[call-arg]
