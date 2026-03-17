from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache
import secrets
import logging

_config_logger = logging.getLogger(__name__)

# 자동 생성 여부 추적 (Settings 모델 오염 방지)
_auto_generated = {"jwt_key": False, "admin_pw": False, "staff_pw": False}


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

    # Aligo SMS API (only needed when DEMO_MODE=false)
    ALIGO_API_KEY: str = ""
    ALIGO_USER_ID: str = ""
    ALIGO_SENDER: str = ""
    ALIGO_TESTMODE: bool = True  # True = 실제 발송 안함 (테스트), False = 실제 발송

    # SMS Webhook (optional)
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
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24

    # CORS
    CORS_ORIGINS: str = "*"

    # Default passwords (데모 모드에서 자동 생성, 프로덕션에서 필수)
    ADMIN_DEFAULT_PASSWORD: str = ""
    STAFF_DEFAULT_PASSWORD: str = ""

    @model_validator(mode='after')
    def validate_secrets(self) -> 'Settings':
        """Validate security-critical settings after .env loading"""
        # JWT Secret Key
        if not self.JWT_SECRET_KEY:
            if self.DEMO_MODE:
                self.JWT_SECRET_KEY = secrets.token_hex(32)
                _auto_generated["jwt_key"] = True
            else:
                raise ValueError(
                    "JWT_SECRET_KEY is required in production. "
                    "Generate with: openssl rand -hex 32"
                )

        # Admin password
        if not self.ADMIN_DEFAULT_PASSWORD:
            if self.DEMO_MODE:
                self.ADMIN_DEFAULT_PASSWORD = "demo-admin-" + secrets.token_hex(4)
                _auto_generated["admin_pw"] = True
            else:
                raise ValueError("ADMIN_DEFAULT_PASSWORD is required in production.")

        # CORS — 프로덕션에서 * 금지
        if not self.DEMO_MODE and self.CORS_ORIGINS == "*":
            raise ValueError(
                "CORS_ORIGINS='*' is not allowed in production. "
                "Set specific origins: CORS_ORIGINS=https://your-domain.com"
            )

        # Staff password
        if not self.STAFF_DEFAULT_PASSWORD:
            if self.DEMO_MODE:
                self.STAFF_DEFAULT_PASSWORD = "demo-staff-" + secrets.token_hex(4)
                _auto_generated["staff_pw"] = True
            else:
                raise ValueError("STAFF_DEFAULT_PASSWORD is required in production.")

        return self

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()


# Runtime Naver cookie management (서버 재시작 시 초기화)
_runtime_naver_cookie: str | None = None


def get_naver_cookie() -> str:
    """Get current Naver cookie (runtime override or .env)"""
    return _runtime_naver_cookie if _runtime_naver_cookie is not None else settings.NAVER_COOKIE


def set_naver_cookie(cookie: str | None) -> None:
    """Set or clear runtime Naver cookie"""
    global _runtime_naver_cookie
    _runtime_naver_cookie = cookie
