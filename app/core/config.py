import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional
from pydantic import field_validator
from pathlib import Path
from fastapi_mail import ConnectionConfig

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATE_FOLDER = Path(__file__).parent.parent / 'templates'

class Settings(BaseSettings):
    PROJECT_NAME: str = "Green Light Quiz API"
    API_V1_STR: str = "/api/v1"
    
    JWT_SECRET_KEY: str = ""   
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    GOOGLE_CLIENT_ID: str = ""   
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    
    CORS_ORIGINS: List[str] = ["*"]
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "hello@falconmail.online"
    APP_NAME: str = "Green Light Quiz" 
    
    ADMIN_USERNAME: str = ""
    ADMIN_PASSWORD: str = ""
    ADMIN_HASHED_PASSWORD: str = ""

    # Let Pydantic handle validation naturally from fields or the env file
    DATABASE_URL: str = ""

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def fix_postgres_protocol(cls, v: Optional[str]) -> Optional[str]:
        if v and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql://", 1)
        return v
 
    # Force Pydantic to read our .env.docker file automatically!
    model_config = SettingsConfigDict(
        env_file=".env.docker", 
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

mail_conf = ConnectionConfig(
    TEMPLATE_FOLDER=TEMPLATE_FOLDER,
    MAIL_USERNAME="resend", 
    MAIL_PASSWORD=settings.RESEND_API_KEY, 
    MAIL_FROM=settings.RESEND_FROM_EMAIL,
    MAIL_PORT=587,
    MAIL_SERVER="smtp.resend.com",
    MAIL_FROM_NAME=settings.APP_NAME,
    MAIL_STARTTLS=True, 
    MAIL_SSL_TLS=False,  
    USE_CREDENTIALS=True, 
    VALIDATE_CERTS=True, 
)