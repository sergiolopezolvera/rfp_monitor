from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    database_url: str = Field(default="sqlite:///rfp_monitor.db", alias="DATABASE_URL")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")

    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")
    raw_dir: Path = Field(default=Path("data/raw"), alias="RAW_DIR")
    parsed_dir: Path = Field(default=Path("data/parsed"), alias="PARSED_DIR")
    export_dir: Path = Field(default=Path("data/exports"), alias="EXPORT_DIR")
    log_dir: Path = Field(default=Path("data/logs"), alias="LOG_DIR")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def ensure_directories(self) -> None:
        for directory in [
            self.data_dir,
            self.raw_dir,
            self.parsed_dir,
            self.export_dir,
            self.log_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()