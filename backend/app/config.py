from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache
from zoneinfo import ZoneInfo
import secrets

KST = ZoneInfo("Asia/Seoul")


def today_kst() -> str:
    """Return today's date as YYYY-MM-DD string, always in KST."""
    from datetime import datetime
    return datetime.now(KST).strftime("%Y-%m-%d")


def today_kst_date():
    """Return today's date as a date object, always in KST."""
    from datetime import datetime
    return datetime.now(KST).date()


# 자동 생성 여부 추적 (Settings 모델 오염 방지)
_auto_generated = {"jwt_key": False, "admin_pw": False, "staff_pw": False}


class Settings(BaseSettings):
    """Application settings with environment variable support"""

    # Demo mode flag — LLM mock/real, JWT/password auto-gen, CORS relaxation
    DEMO_MODE: bool = True

    # Swagger UI — None이면 DEMO_MODE 따라감
    ENABLE_SWAGGER: bool | None = None

    # Database (SQLite for demo, PostgreSQL for production)
    DATABASE_URL: str = "sqlite:///./sms_demo.db"

    # Aligo SMS API (실제 발송 여부는 tenant.aligo_testmode로 제어)
    ALIGO_API_KEY: str = ""
    ALIGO_USER_ID: str = ""
    ALIGO_SENDER: str = ""

    # JWT Authentication
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 1
    JWT_REFRESH_EXPIRE_DAYS: int = 7

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
        extra = "ignore"  # .env에 남아있는 ALIGO_TESTMODE 등 미사용 변수 무시


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()

