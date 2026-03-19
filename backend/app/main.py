"""
FastAPI application entry point
"""
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from app.rate_limit import limiter
from app.api import messages, webhooks, auto_response, rules, documents, reservations, dashboard, scheduler, rooms, templates, template_schedules, auth, settings, activity_logs, buildings, party_checkin, events, tenants
from app.config import settings as app_settings
from app.db.database import init_db, get_db
from app.scheduler.jobs import start_scheduler, stop_scheduler
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Task 1.4: Swagger UI 프로덕션 비활성화
app = FastAPI(
    title="SMS Reservation System API",
    description="Demo/MVP version with mock providers",
    version="1.0.0",
    docs_url="/docs" if app_settings.DEMO_MODE else None,
    redoc_url="/redoc" if app_settings.DEMO_MODE else None,
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

# Rate Limiting 미들웨어 + 에러 핸들러
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

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
    start_scheduler()
    logging.info("Scheduler started")


@app.on_event("shutdown")
async def shutdown_event():
    # Stop scheduler on shutdown
    stop_scheduler()
    logging.info("Scheduler stopped")


# Include routers
app.include_router(auth.router)
app.include_router(messages.router)
app.include_router(webhooks.router)
app.include_router(auto_response.router)
app.include_router(rules.router)
app.include_router(documents.router)
app.include_router(reservations.router)
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
