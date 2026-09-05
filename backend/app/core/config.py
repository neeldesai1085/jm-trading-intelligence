from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///./jm_trading.db'
    market_data_provider: str = 'yahoo'
    upload_dir: str = '../data/incoming'
    quote_refresh_seconds: int = 60
    benchmark_isin: str | None = None
    benchmark_yahoo_symbol: str | None = None
    app_env: str = 'development'
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    auth_secret: str = 'change-this-secret'
    auth_access_minutes: int = 20
    auth_refresh_days: int = 30
    auth_cookie_name: str = 'jmti_refresh'
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = 'lax'
    rate_limit_per_minute: int = 30

settings = Settings()
