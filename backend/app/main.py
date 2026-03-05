"""
FastAPI application entry point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import messages, webhooks, auto_response, rules, documents, reservations, dashboard, campaigns, scheduler, rooms, templates, template_schedules, auth
from app.db.database import init_db
from app.scheduler.jobs import start_scheduler, stop_scheduler
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI(
    title="SMS Reservation System API",
    description="Demo/MVP version with mock providers",
    version="1.0.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database and scheduler on startup
@app.on_event("startup")
async def startup_event():
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


@app.get("/")
async def root():
    return {
        "message": "SMS Reservation System API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
