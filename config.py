import sys
from pathlib import Path
from datetime import timedelta
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    # --- Database (opzionale nella versione Lite) -------------------
    MONGO_URL: Optional[str] = None          # ora è facoltativa
    DB_NAME: str = "document_validator"

    # --- JWT / sicurezza -------------------------------------------
    SECRET_KEY: str = "INSECURE-DEV-KEY"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # --- Altri parametri -------------------------------------------
    LOG_LEVEL: str = "INFO"
    MAX_FILE_SIZE: int = 20 * 1024 * 1024   # 20 MB
    # Legge ALLOWED_ORIGINS come stringa grezza per evitare il JSON parse predefinito
    ALLOWED_ORIGINS: str = "*"              # in .env: dominio1,dominio2 o ["a","b"]

    ZENDESK_SUBDOMAIN: Optional[str] = None
    ZENDESK_EMAIL: Optional[str] = None
    ZENDESK_API_TOKEN: Optional[str] = None

    # Helper per FastAPI
    @property
    def access_token_expires(self) -> timedelta:
        return timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)

    @property
    def allowed_origins_list(self) -> List[str]:
        """
        Restituisce ALLOWED_ORIGINS come lista di stringhe.
        Supporta sia formato JSON array che comma-separated.
        """
        raw = self.ALLOWED_ORIGINS.strip()
        # Prova JSON
        try:
            import json
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except Exception:
            pass
        # Fallback: split per virgola
        return [item.strip() for item in raw.split(',') if item.strip()]

    # -------------------------------------------------------------
    # Validator per pulire raw env (rimuove spazi, newlines e commenti)
    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _clean_allowed_origins(cls, v):
        if isinstance(v, str):
            # rimuove commenti dopo #
            return v.split('#')[0].replace("\n", "").strip()
        return v

    @field_validator("ACCESS_TOKEN_EXPIRE_MINUTES", "MAX_FILE_SIZE", mode="before")
    @classmethod
    def _parse_int_fields(cls, v):
        if isinstance(v, str):
            # rimuove commenti dopo # e spazi
            raw = v.split('#')[0].strip()
            return int(raw)
        return v
    # -------------------------------------------------------------

    class Config:
        # trova la cartella in cui è stato scompattato il bundle
        BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"


# Instanzia le impostazioni
settings = Settings()
