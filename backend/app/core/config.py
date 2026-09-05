from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = 'sqlite:///./jm_trading.db'
    market_data_provider: str = 'mock'
    upstox_access_token: str | None = None
    zerodha_api_key: str | None = None
    zerodha_access_token: str | None = None
    upload_dir: str = '../data/incoming'
    quote_refresh_seconds: int = 30
    benchmark_isin: str | None = None
    benchmark_instrument_key: str | None = None
    app_env: str = 'development'
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    model_config = SettingsConfigDict(env_file='../.env', extra='ignore')

settings = Settings()
