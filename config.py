# config.py
from pydantic_settings import BaseSettings
from typing import List, Optional
from datetime import timedelta


class Settings(BaseSettings):
    # --- Database (opzionale nella versione Lite) -------------------
    MONGO_URL: Optional[str] = None          # <-- ora è facoltativa
    DB_NAME: str = "document_validator"

    # --- JWT / sicurezza -------------------------------------------
    # In produzione sovrascrivi con una variabile d’ambiente
    SECRET_KEY: str = "INSECURE-DEV-KEY"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # --- Altri parametri -------------------------------------------
    LOG_LEVEL: str = "INFO"
    MAX_FILE_SIZE: int = 20 * 1024 * 1024   # 20 MB
    ALLOWED_ORIGINS: List[str] = ["*"]      # restringi in prod

    ZENDESK_SUBDOMAIN: str
    ZENDESK_EMAIL: str
    ZENDESK_API_TOKEN: str

    # Helper per FastAPI
    @property
    def access_token_expires(self) -> timedelta:
        return timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

