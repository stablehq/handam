from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings with environment variable support"""

    # Demo mode flag - CRITICAL for hot-swapping providers
    DEMO_MODE: bool = True

    # Database (SQLite for demo, PostgreSQL for production)
    DATABASE_URL: str = "sqlite:///./sms_demo.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # ChromaDB
    CHROMADB_URL: str = "http://localhost:8001"

    # SMS API (only needed when DEMO_MODE=false)
    SMS_API_KEY: str = ""
    SMS_API_SECRET: str = ""
    SMS_WEBHOOK_URL: str = ""

    # Claude API (only needed when DEMO_MODE=false)
    CLAUDE_API_KEY: str = ""

    # Google Sheets (only needed when DEMO_MODE=false)
    GOOGLE_SHEETS_CREDENTIALS: str = ""

    # Naver Reservation (only needed when DEMO_MODE=false)
    NAVER_RESERVATION_EMAIL: str = ""
    NAVER_RESERVATION_PASSWORD: str = ""
    NAVER_BUSINESS_ID: str = "819409"
    NAVER_COOKIE: str = ""

    # JWT Authentication
    JWT_SECRET_KEY: str = "dev-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24

    # CORS
    CORS_ORIGINS: str = "*"

    # Admin
    ADMIN_DEFAULT_PASSWORD: str = "admin1234"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()
