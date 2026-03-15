"""
FastAPI application entry point
"""
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.api import messages, webhooks, auto_response, rules, documents, reservations, dashboard, campaigns, scheduler, rooms, templates, template_schedules, auth, settings
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


# Initialize database and scheduler on startup
@app.on_event("startup")
async def startup_event():
    # Task 1.1: JWT 시크릿 프로덕션 검증
    if not app_settings.DEMO_MODE and app_settings.JWT_SECRET_KEY == "dev-secret-key-change-in-production":
        raise RuntimeError("Production mode requires a secure JWT_SECRET_KEY. Set JWT_SECRET_KEY in .env")

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
app.include_router(campaigns.router)
app.include_router(scheduler.router)
app.include_router(templates.router)
app.include_router(template_schedules.router)
app.include_router(settings.router)


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
