from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Bili Web"
    public_base_url: str = "http://localhost:8000"
    frontend_dir: Path = Path("/app/frontend")
    download_dir: Path = Path("/data/downloads")
    public_download_path: str = "/downloads"
    bili_cookie: str = ""
    request_timeout: float = 15.0
    max_download_mb: int = 2048
    max_parallel_downloads: int = 2
    chunk_download_workers: int = 6
    chunk_download_min_mb: int = 20
    download_retry_count: int = 3
    file_retention_hours: int = 24
    cleanup_interval_minutes: int = 30
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )


settings = Settings()
