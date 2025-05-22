from pydantic_settings import BaseSettings
from typing import List
from datetime import timedelta

class Settings(BaseSettings):
    # Variabili configurabili (tipi e default)
    MONGO_URL: str
    DB_NAME: str = "document_validator"

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    LOG_LEVEL: str = "INFO"
    MAX_FILE_SIZE: int = 20 * 1024 * 1024  # 20 MB
    ALLOWED_ORIGINS: List[str] = ["*"]  # default *

    @property
    def access_token_expires(self) -> timedelta:
        return timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)

    class Config:
        env_file = ".env"           # Legge da file .env se presente
        env_file_encoding = "utf-8" # Codifica file .env

# Istanzi la configurazione globale
settings = Settings()
