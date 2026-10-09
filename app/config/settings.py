import os
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    # Application
    AppEnv: str          = Field("development", validation_alias="APP_ENV")
    LogLevel: str        = Field("INFO", validation_alias="LOG_LEVEL")
    AllowedOrigins: str  = Field("http://localhost:8000,http://127.0.0.1:8000", validation_alias="ALLOWED_ORIGINS")
    InternalApiKey: str  = Field("", validation_alias="INTERNAL_API_KEY")

    # Redis
    RedisUrl: str        = Field("redis://redis:6379/0", validation_alias="REDIS_URL")

    # PostgreSQL
    DatabaseUrl: str = Field(
        "postgresql://postgres:postgres@postgres:5432/NexusQuantDB",
        validation_alias="DATABASE_URL"
    )

    # Market Data Provider
    MarketDataProvider: str = Field("nse", validation_alias="MARKET_DATA_PROVIDER")
    GrowwApiKey: str      = Field("", validation_alias="GROWW_API_KEY")
    GrowwApiSecret: str   = Field("", validation_alias="GROWW_API_SECRET")
    GrowwAccessToken: str = Field("", validation_alias="GROWW_ACCESS_TOKEN")
    GrowwTotpSecret: str  = Field("", validation_alias="GROWW_TOTP_SECRET")
    GrowwPin: str         = Field("", validation_alias="GROWW_PIN")

    # Supabase
    SupabaseUrl: str = Field("", validation_alias="supabaseUrl")
    SupabaseKey: str = Field("", validation_alias="supabaseKey")
    SupabaseConnectionString: str = Field("", validation_alias="supabaseConnectionString")

    # Ingestion & Polling
    DefaultSymbols: str       = Field(
        "",
        validation_alias="WATCHLIST_SYMBOLS"
    )
    PricePollIntervalSeconds: int = Field(5, validation_alias="PRICE_POLL_INTERVAL_SECONDS")
    OptionsPollIntervalSeconds: int = Field(15, validation_alias="OPTIONS_POLL_INTERVAL_SECONDS")

    # Macroeconomic Defaults
    DefaultRiskFreeRateInr: float = Field(6.5, validation_alias="DEFAULT_RISK_FREE_RATE_INR")
    DefaultRiskFreeRateUsd: float = Field(5.25, validation_alias="DEFAULT_RISK_FREE_RATE_USD")

    def get_default_symbols_as_list(self) -> list[str]:
        """Parse DefaultSymbols into a clean list."""
        return [s.strip().upper() for s in self.DefaultSymbols.split(",") if s.strip()]

    def get_allowed_origins_list(self) -> list[str]:
        """Parse AllowedOrigins into a clean list."""
        if not self.AllowedOrigins or self.AllowedOrigins.strip() == "*":
            return ["http://localhost:8000", "http://127.0.0.1:8000"]
        return [o.strip() for o in self.AllowedOrigins.split(",") if o.strip()]


@lru_cache()
def get_settings() -> Settings:
    env = os.getenv("APP_ENV", "development").lower()
    if env == "production":
        from app.config.production import ProductionSettings
        return ProductionSettings()
    elif env == "testing":
        from app.config.testing import TestingSettings
        return TestingSettings()
    else:
        from app.config.development import DevelopmentSettings
        return DevelopmentSettings()
