from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


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

    # --- LLM ---
    anthropic_api_key: str = Field(default="", description="Claude API key (primary LLM)")
    deepseek_api_key: str = Field(default="", description="DeepSeek API key (fallback LLM)")

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


settings = Settings()
