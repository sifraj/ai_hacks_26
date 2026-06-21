from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Anthropic
    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")

    # Coinbase Advanced
    coinbase_api_key: str = Field("", alias="COINBASE_API_KEY")
    coinbase_api_secret: str = Field("", alias="COINBASE_API_SECRET")

    # Data Sources
    newsapi_key: str = Field("", alias="NEWSAPI_KEY")
    cryptopanic_api_key: str = Field("", alias="CRYPTOPANIC_API_KEY")
    coinglass_api_key: str = Field("", alias="COINGLASS_API_KEY")
    glassnode_api_key: str = Field("", alias="GLASSNODE_API_KEY")

    # Infrastructure
    database_url: str = Field(..., alias="DATABASE_URL")
    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")

    # System Config
    paper_trading: bool = Field(True, alias="PAPER_TRADING")
    tick_interval_seconds: int = Field(300, alias="TICK_INTERVAL_SECONDS")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    log_dir: str = Field("./logs", alias="LOG_DIR")
    max_llm_calls_per_tick: int = Field(15, alias="MAX_LLM_CALLS_PER_TICK")


settings = Settings()
