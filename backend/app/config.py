from typing import Literal

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

    # 스케줄러 비활성화 (로컬 개발 시 운영 칩 덮어쓰기 방지용).
    # True면 main.py 의 start_scheduler() 호출 안 함. 기본 False → 기존 동작 유지.
    DISABLE_SCHEDULER: bool = False

    # split-group P3: 분할 primary 취소 시 sibling 자동 전파 모드.
    # 'alert' (기본): 경보만 (P2 동작 그대로) / 'auto': 비보호 sibling 자동 취소.
    # Literal 타입 — 오타('AUTO'/'on' 등) 시 기동 거부 (조용히 alert 잔류 방지).
    # ⚠️ auto 전환은 반드시 절차 준수: docs/plans/split-group-step-03-auto-propagation.md §7
    #    (backfill 완료 + P0 정리 재실행 + 정답지 forbidden 해제 후에만.
    #     롤백은 'alert' 복귀 — 재배포 불요. 그룹당 1회 ledger 는 단일 워커 전제 —
    #     GUNICORN_WORKERS=1, entrypoint.sh 기본값)
    SPLIT_CANCEL_MODE: Literal["alert", "auto"] = "alert"

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

    # Sentry (운영 에러 모니터링, 비워두면 비활성)
    SENTRY_DSN: str = ""

    # CORS
    CORS_ORIGINS: str = "*"

    # Default passwords (데모 모드에서 자동 생성, 프로덕션에서 필수)
    ADMIN_DEFAULT_PASSWORD: str = ""
    STAFF_DEFAULT_PASSWORD: str = ""

    # 옵션 C (Session-bound tenant) 마이그레이션 단계 제어
    # 0=비활성 (legacy ContextVar 만), 1=shim only (factory 사용 가능),
    # 2=API layer 전환, 3=scheduler 전환, 4=service 전환,
    # 5=ContextVar 사용 0 검증, 6=ContextVar 정의 제거
    # 자세한 마이그레이션 계획: docs/option-c-discovery/
    OPTION_C_PHASE: int = 0

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

