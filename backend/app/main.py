"""
FastAPI application entry point
"""
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from app.rate_limit import limiter


from app.api import reservations, reservations_room, reservations_sms, reservations_stay, dashboard, scheduler, rooms, templates, template_schedules, auth, settings, activity_logs, buildings, party_checkin, events, tenants
from app.api.event_sms import router as event_sms_router
from app.api.sales_report import router as sales_report_router
from app.api.daily_host import router as daily_host_router
from app.api.party_hosts import router as party_hosts_router
from app.api.daily_review import router as daily_review_router
from app.api.onsite_female_invite import router as onsite_female_invite_router
from app.api.cleancrew import router as cleancrew_router
from app.config import settings as app_settings
from app.db.database import init_db, get_db
from app.scheduler.jobs import start_scheduler, stop_scheduler
import logging

# DIAG_BLOCK_START: request correlation middleware (refactor-2026-04)
import uuid
from app.diag_logger import (
    diag,
    set_request_context,
    reset_request_context,
    is_enabled,
)
# DIAG_BLOCK_END

# Sentry 초기화 (DEMO_MODE=false + SENTRY_DSN 설정 시)
if not app_settings.DEMO_MODE and app_settings.SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=app_settings.SENTRY_DSN,
            traces_sample_rate=0.2,
            environment="production",
        )
    except ImportError:
        logging.warning("SENTRY_DSN이 설정되었지만 sentry-sdk가 설치되지 않았습니다. pip install sentry-sdk[fastapi]")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses (defense-in-depth with nginx)."""
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Swagger UI — ENABLE_SWAGGER 설정 우선, 미설정 시 DEMO_MODE 따라감
_enable_swagger = app_settings.ENABLE_SWAGGER if app_settings.ENABLE_SWAGGER is not None else app_settings.DEMO_MODE
app = FastAPI(
    title="SMS Reservation System API",
    version="1.0.0",
    docs_url="/docs" if _enable_swagger else None,
    redoc_url="/redoc" if _enable_swagger else None,
)

# Task 1.2: CORS 도메인 화이트리스트
cors_origins = (
    app_settings.CORS_ORIGINS.split(",")
    if app_settings.CORS_ORIGINS != "*"
    else ["*"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=app_settings.CORS_ORIGINS != "*",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers (defense-in-depth with nginx)
app.add_middleware(SecurityHeadersMiddleware)

# Rate Limiting 미들웨어 + 에러 핸들러
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


# DIAG_BLOCK_START: diag correlation middleware (refactor-2026-04)
@app.middleware("http")
async def diag_correlation_middleware(request, call_next):
    """Request correlation ID + user action 태그 주입.
    DIAG_LEVEL=off 면 아무 동작 안 함 (is_enabled로 early return).
    /health 는 docker healthcheck 노이즈라 스킵."""
    if not is_enabled("critical") or request.url.path == "/health":
        return await call_next(request)

    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    # Frontend 가 encodeURIComponent 로 ASCII-safe 화 (한글 포함 가능)
    from urllib.parse import unquote
    raw_action = request.headers.get("X-Diag-Action", "-")
    try:
        action = unquote(raw_action)
    except Exception:
        action = raw_action
    tokens = set_request_context(req_id, action)

    import time
    start = time.perf_counter()
    try:
        diag(
            "request.enter",
            level="verbose",
            method=request.method,
            path=request.url.path,
        )
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        diag(
            "request.exit",
            level="verbose",
            status=response.status_code,
            ms=elapsed_ms,
        )
        return response
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        diag(
            "request.error",
            level="critical",
            error=type(e).__name__,
            msg=str(e)[:200],
            ms=elapsed_ms,
        )
        raise
    finally:
        reset_request_context(tokens)
# DIAG_BLOCK_END

@app.get("/sentry-debug")
async def trigger_error():
    """Sentry 연동 테스트용 (의도적 500 에러)"""


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "로그인 시도 횟수를 초과했습니다. 잠시 후 다시 시도해주세요."},
    )


# Initialize database and scheduler on startup
@app.on_event("startup")
async def startup_event():
    # 보안 경고 (자동 생성된 값 알림)
    from app.config import _auto_generated
    if _auto_generated["jwt_key"]:
        logging.warning(
            "DEMO MODE: JWT Secret Key가 자동 생성되었습니다. "
            "서버 재시작 시 기존 토큰이 무효화됩니다. "
            ".env에 JWT_SECRET_KEY를 설정하면 이를 방지할 수 있습니다."
        )
    if _auto_generated["admin_pw"]:
        logging.warning(f"DEMO MODE: Admin 비밀번호: {app_settings.ADMIN_DEFAULT_PASSWORD}")
    if _auto_generated["staff_pw"]:
        logging.warning(f"DEMO MODE: Staff 비밀번호: {app_settings.STAFF_DEFAULT_PASSWORD}")

    init_db()
    logging.info("Database initialized")

    # Start scheduler for automated tasks
    if app_settings.DISABLE_SCHEDULER:
        logging.info("Scheduler disabled (DISABLE_SCHEDULER set)")
    else:
        start_scheduler()
        logging.info("Scheduler started")


@app.on_event("shutdown")
async def shutdown_event():
    # Stop scheduler on shutdown
    stop_scheduler()
    logging.info("Scheduler stopped")


# Include routers
app.include_router(auth.router)
app.include_router(reservations.router)
app.include_router(reservations_room.router)
app.include_router(reservations_sms.router)
app.include_router(reservations_stay.router)
app.include_router(rooms.router)
app.include_router(dashboard.router)
app.include_router(scheduler.router)
app.include_router(templates.router)
app.include_router(templates.router_misc)
app.include_router(template_schedules.router)
app.include_router(settings.router)
app.include_router(activity_logs.router)
app.include_router(buildings.router)
app.include_router(party_checkin.router)
app.include_router(events.router)
app.include_router(tenants.router)
app.include_router(event_sms_router)
app.include_router(sales_report_router)
app.include_router(daily_host_router)
app.include_router(party_hosts_router)
app.include_router(daily_review_router)
app.include_router(onsite_female_invite_router)
app.include_router(cleancrew_router)


@app.get("/")
async def root():
    return {
        "message": "SMS Reservation System API",
        "version": "1.0.0",
        "docs": "/docs",
    }


# Task 1.3: Health Check 강화
@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    health = {"status": "healthy", "checks": {}}
    try:
        db.execute(text("SELECT 1"))
        health["checks"]["database"] = "ok"
    except Exception as e:
        health["status"] = "unhealthy"
        health["checks"]["database"] = "error" if not app_settings.DEMO_MODE else str(e)
    return health
