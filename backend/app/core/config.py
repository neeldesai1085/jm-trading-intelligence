from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///./jm_trading.db'
    market_data_provider: str = 'yahoo'
    upstox_access_token: str | None = None
    zerodha_api_key: str | None = None
    zerodha_access_token: str | None = None
    zerodha_api_secret: str | None = None
    upload_dir: str = '../data/incoming'
    quote_refresh_seconds: int = 60
    benchmark_isin: str | None = None
    benchmark_instrument_key: str | None = None
    app_env: str = 'development'
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    auth_secret: str = 'change-this-secret'
    auth_access_minutes: int = 20
    auth_refresh_days: int = 30
    auth_cookie_name: str = 'jmti_refresh'
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = 'lax'
    rate_limit_per_minute: int = 30
    password_reset_minutes: int = 30
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    object_storage_provider: str = 'local'
    store_raw_pdf: bool = False
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    token_encryption_key: str | None = None
    upstox_client_id: str | None = None
    upstox_client_secret: str | None = None
    upstox_redirect_uri: str | None = None
    zerodha_redirect_uri: str | None = None

settings = Settings()
