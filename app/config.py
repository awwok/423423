from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    bot_token: str
    database_url: str | None = None
    database_path: str = "/app/data/bot.db"
    data_dir: str = "/app/data"
    default_timezone: str = "Europe/Samara"
    log_level: str = "INFO"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        data_dir = Path(self.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        path = Path(self.database_path)
        if not path.is_absolute():
            path = data_dir / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{path.as_posix()}"

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
