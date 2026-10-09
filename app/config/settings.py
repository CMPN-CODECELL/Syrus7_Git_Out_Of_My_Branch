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
        "postgresql://postgres:change-me@postgres:5432/NexusQuantDB",
        validation_alias="DATABASE_URL"
    )

    # Analysis market data provider (yfinance + NSE scraper)
    MarketDataProvider: str = Field("nse", validation_alias="MARKET_DATA_PROVIDER")

    # Supabase (app login). Only the anon key is ever sent to the browser.
    SupabaseUrl: str = Field("", validation_alias="supabaseUrl")
    SupabaseKey: str = Field("", validation_alias="supabaseKey")
    SupabaseConnectionString: str = Field("", validation_alias="supabaseConnectionString")
    SupabaseJwtSecret: str = Field("", validation_alias="SUPABASE_JWT_SECRET")
    SupabaseJwtAudience: str = Field("authenticated", validation_alias="SUPABASE_JWT_AUDIENCE")

    # 021 Trade broker (server-side only; never logged, never sent to the LLM or browser)
    TradeApiBaseUrl: str = Field("https://devapi.021.trade/api/developer-api/v1", validation_alias="TRADE_API_BASE_URL")
    TradeWsBaseUrl: str  = Field("wss://devapi.021.trade/api/developer/websocket", validation_alias="TRADE_WS_BASE_URL")
    TradeApiUsername: str = Field("", validation_alias="TRADE_API_USERNAME")
    TradeApiPassword: str = Field("", validation_alias="TRADE_API_PASSWORD")
    TradeApiTimeoutSeconds: float = Field(10.0, validation_alias="TRADE_API_TIMEOUT_SECONDS")
    TradeApiRatePerSecond: float = Field(5.0, validation_alias="TRADE_API_RATE_PER_SECOND")
    TradeApiMaxGetRetries: int = Field(3, validation_alias="TRADE_API_MAX_GET_RETRIES")
    InstrumentsCachePath: str = Field("data/instruments.csv.gz", validation_alias="INSTRUMENTS_CACHE_PATH")

    # Order safety limits (enforced server-side from Phase 2 on)
    TradingKillSwitch: bool = Field(False, validation_alias="TRADING_KILL_SWITCH")
    MaxOrderValuePaise: int = Field(20_000_000, validation_alias="MAX_ORDER_VALUE_PAISE")  # Rs 2,00,000
    MaxOrderQty: int        = Field(5_000, validation_alias="MAX_ORDER_QTY")
    AllowedExchanges: str   = Field("NSE,NSEFO", validation_alias="ALLOWED_EXCHANGES")
    AllowedProducts: str    = Field("CNC,INTRADAY,NRML", validation_alias="ALLOWED_PRODUCTS")

    # LLM (Gemini). Key stays server-side.
    GeminiApiKey: str = Field("", validation_alias="GEMINI_API_KEY")
    GeminiModel: str  = Field("gemini-2.5-flash", validation_alias="GEMINI_MODEL")
    ChatMaxMessageChars: int = Field(1000, validation_alias="CHAT_MAX_MESSAGE_CHARS")
    ChatRateLimitPerMinute: int = Field(20, validation_alias="CHAT_RATE_LIMIT_PER_MINUTE")
    ChatMaxToolCalls: int = Field(6, validation_alias="CHAT_MAX_TOOL_CALLS")

    # Ingestion & Polling
    DefaultSymbols: str       = Field(
        "",
        validation_alias="WATCHLIST_SYMBOLS"
    )
    PricePollIntervalSeconds: int = Field(5, validation_alias="PRICE_POLL_INTERVAL_SECONDS")
    OptionsPollIntervalSeconds: int = Field(15, validation_alias="OPTIONS_POLL_INTERVAL_SECONDS")
    BackfillDays: int = Field(400, validation_alias="BACKFILL_DAYS")

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

    def get_allowed_exchanges(self) -> set[str]:
        return {e.strip().upper() for e in self.AllowedExchanges.split(",") if e.strip()}

    def get_allowed_products(self) -> set[str]:
        return {p.strip().upper() for p in self.AllowedProducts.split(",") if p.strip()}


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
