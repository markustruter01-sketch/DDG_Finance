from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Data Source Keys ---
    fred_api_key: str = Field(..., description="FRED API key from fred.stlouisfed.org")
    news_api_key: str = Field(..., description="NewsAPI key from newsapi.org")

    # --- Alpaca (Paper Trading) ---
    alpaca_api_key: str = Field(default="", description="Alpaca paper trading API key")
    alpaca_secret_key: str = Field(default="", description="Alpaca paper trading secret key")
    alpaca_base_url: str = Field(
        default="https://paper-api.alpaca.markets",
        description="Alpaca paper trading base URL",
    )

    # --- LLM: Claude (sole provider) ---
    anthropic_api_key: str = Field(..., description="Anthropic Claude API key — sole LLM provider")
    claude_model_smart: str = Field(
        default="claude-sonnet-4-6",
        description="Claude model for high-stakes calls: regime analysis, fleet audit, fleet chat",
    )
    claude_model_fast: str = Field(
        default="claude-haiku-4-5",
        description="Claude model for fast/cheap calls: commentary, learning journal, feedback injection",
    )

    # --- Retired LLM keys (kept for env-var compat; not used by any active call path) ---
    groq_api_key: str = Field(default="", description="Groq API key (retired — kept for env-var compat)")
    deepseek_api_key: str = Field(default="", description="DeepSeek API key (optional future use)")

    # --- Trading Constraints ---
    conviction_threshold: float = Field(
        default=0.75,
        description="Minimum LLM conviction score (0-1) required to place a trade",
    )
    kill_switch_drawdown_pct: float = Field(
        default=0.05,
        description="Portfolio daily drawdown % that triggers the kill switch (e.g. 0.05 = 5%)",
    )
    total_capital_slots: int = Field(
        default=10,
        description="Total number of capital allocation slots",
    )
    cash_equivalent_ticker: str = Field(
        default="SGOV",
        description="Ticker used to fill empty/low-conviction slots",
    )

    # --- Claude Pacing (interval throttle — NOT a hard budget gate) ---
    regime_fallback_max_age_hours: float = Field(
        default=1.5,
        description="How many hours a cached regime analysis remains valid when Claude is rate-limited",
    )
    claude_regime_interval_minutes: int = Field(
        default=90,
        description="Minimum minutes between regime/crypto Claude calls. 0 = disabled.",
    )
    claude_commentary_daily_cap: int = Field(
        default=4,
        description="Max auto-triggered commentary refreshes per endpoint per day. Force=true bypasses.",
    )

    # --- Legacy Groq pacing aliases (read by claude_budget shim for backward compat) ---
    groq_daily_token_budget: int = Field(
        default=500_000,
        description="(Legacy alias) Daily token tracking budget — used for reporting only, not as a gate.",
    )
    groq_min_regime_interval_minutes: int = Field(
        default=90,
        description="(Legacy alias) Delegates to claude_regime_interval_minutes if that is not set.",
    )
    groq_commentary_daily_cap: int = Field(
        default=4,
        description="(Legacy alias) Delegates to claude_commentary_daily_cap if that is not set.",
    )

    # --- Throttling ---
    max_retries: int = Field(
        default=5,
        description="Maximum retry attempts for API calls with exponential backoff",
    )
    backoff_min_wait: float = Field(
        default=1.0,
        description="Minimum wait seconds between retries",
    )
    backoff_max_wait: float = Field(
        default=60.0,
        description="Maximum wait seconds between retries",
    )

    # --- Logging ---
    log_level: str = Field(default="INFO", description="Loguru log level")
    log_file: str = Field(default="logs/trading.log", description="Log file path")

    @field_validator(
        "fred_api_key", "news_api_key",
        "alpaca_api_key", "alpaca_secret_key",
        "anthropic_api_key", "groq_api_key", "deepseek_api_key",
        mode="before",
    )
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


settings = Settings()
