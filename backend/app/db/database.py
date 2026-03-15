"""
Database connection and session management
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings
from typing import Generator

# Task 1.6: DB 커넥션 풀링 설정
connect_args = {}
engine_kwargs = {}

if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
else:
    # PostgreSQL (Supabase) 커넥션 풀링
    engine_kwargs.update(
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=300,
    )

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=connect_args,
    **engine_kwargs,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency for FastAPI routes"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables and ensure default admin exists"""
    from app.db.models import Base, User, UserRole
    from app.auth.utils import hash_password

    Base.metadata.create_all(bind=engine)

    # Task 1.5: admin 기본 비밀번호 환경변수화
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == "admin").first():
            db.add(User(
                username="admin",
                hashed_password=hash_password(settings.ADMIN_DEFAULT_PASSWORD),
                name="관리자",
                role=UserRole.SUPERADMIN,
                is_active=True,
            ))
            db.commit()
    finally:
        db.close()
