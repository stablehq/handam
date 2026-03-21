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
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Register tenant context event listeners
import app.db.tenant_context  # noqa: F401 — registers before_flush event


def init_db():
    """Initialize database tables and ensure default admin exists"""
    from app.db.models import Base, User, UserRole, Room, RoomBizItemLink
    from app.auth.utils import hash_password
    from sqlalchemy import inspect as sa_inspect, text
    import json

    Base.metadata.create_all(bind=engine)

    # Auto-migrate: add missing columns to existing tables
    inspector = sa_inspect(engine)
    with engine.begin() as conn:
        # rooms.building_id
        if "rooms" in inspector.get_table_names():
            existing_cols = [c["name"] for c in inspector.get_columns("rooms")]
            if "building_id" not in existing_cols:
                conn.execute(text("ALTER TABLE rooms ADD COLUMN building_id INTEGER"))
                print("AUTO-MIGRATE: Added building_id column to rooms table")

        # tenants.aligo_testmode
        if "tenants" in inspector.get_table_names():
            existing_cols = [c["name"] for c in inspector.get_columns("tenants")]
            if "aligo_testmode" not in existing_cols:
                conn.execute(text("ALTER TABLE tenants ADD COLUMN aligo_testmode BOOLEAN DEFAULT TRUE"))
                print("AUTO-MIGRATE: Added aligo_testmode column to tenants table")

        # naver_biz_items.default_capacity + section_hint
        if "naver_biz_items" in inspector.get_table_names():
            existing_cols = [c["name"] for c in inspector.get_columns("naver_biz_items")]
            if "default_capacity" not in existing_cols:
                conn.execute(text("ALTER TABLE naver_biz_items ADD COLUMN default_capacity INTEGER DEFAULT 1"))
                print("AUTO-MIGRATE: Added default_capacity column to naver_biz_items table")
            if "section_hint" not in existing_cols:
                conn.execute(text("ALTER TABLE naver_biz_items ADD COLUMN section_hint VARCHAR(20)"))
                print("AUTO-MIGRATE: Added section_hint column to naver_biz_items table")
                # Backfill section_hint for existing '파티만' products
                conn.execute(text("UPDATE naver_biz_items SET section_hint = 'party' WHERE name LIKE '%파티만%' AND section_hint IS NULL"))
            if "display_name" not in existing_cols:
                conn.execute(text("ALTER TABLE naver_biz_items ADD COLUMN display_name VARCHAR(200)"))
                print("AUTO-MIGRATE: Added display_name column to naver_biz_items table")

        # template_schedules.filters
        if "template_schedules" in inspector.get_table_names():
            existing_cols = [c["name"] for c in inspector.get_columns("template_schedules")]
            if "filters" not in existing_cols:
                conn.execute(text("ALTER TABLE template_schedules ADD COLUMN filters TEXT"))
                print("AUTO-MIGRATE: Added filters column to template_schedules table")

        # rules.active → is_active
        if "rules" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("rules")]
            if "active" in cols and "is_active" not in cols:
                conn.execute(text("ALTER TABLE rules RENAME COLUMN active TO is_active"))
                print("AUTO-MIGRATE: Renamed rules.active to is_active")

        # message_templates.active → is_active
        if "message_templates" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("message_templates")]
            if "active" in cols and "is_active" not in cols:
                conn.execute(text("ALTER TABLE message_templates RENAME COLUMN active TO is_active"))
                print("AUTO-MIGRATE: Renamed message_templates.active to is_active")

        # template_schedules.active → is_active
        if "template_schedules" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("template_schedules")]
            if "active" in cols and "is_active" not in cols:
                conn.execute(text("ALTER TABLE template_schedules RENAME COLUMN active TO is_active"))
                print("AUTO-MIGRATE: Renamed template_schedules.active to is_active")

        # messages.needs_review → is_needs_review
        if "messages" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("messages")]
            if "needs_review" in cols and "is_needs_review" not in cols:
                conn.execute(text("ALTER TABLE messages RENAME COLUMN needs_review TO is_needs_review"))
                print("AUTO-MIGRATE: Renamed messages.needs_review to is_needs_review")

        # documents.indexed → is_indexed
        if "documents" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("documents")]
            if "indexed" in cols and "is_indexed" not in cols:
                conn.execute(text("ALTER TABLE documents RENAME COLUMN indexed TO is_indexed"))
                print("AUTO-MIGRATE: Renamed documents.indexed to is_indexed")

        # template_schedules.exclude_sent → is_exclude_sent
        if "template_schedules" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("template_schedules")]
            if "exclude_sent" in cols and "is_exclude_sent" not in cols:
                conn.execute(text("ALTER TABLE template_schedules RENAME COLUMN exclude_sent TO is_exclude_sent"))
                print("AUTO-MIGRATE: Renamed template_schedules.exclude_sent to is_exclude_sent")

        # template_schedules.last_run → last_run_at, next_run → next_run_at
        if "template_schedules" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("template_schedules")]
            if "last_run" in cols and "last_run_at" not in cols:
                conn.execute(text("ALTER TABLE template_schedules RENAME COLUMN last_run TO last_run_at"))
                print("AUTO-MIGRATE: Renamed template_schedules.last_run to last_run_at")
            if "next_run" in cols and "next_run_at" not in cols:
                conn.execute(text("ALTER TABLE template_schedules RENAME COLUMN next_run TO next_run_at"))
                print("AUTO-MIGRATE: Renamed template_schedules.next_run to next_run_at")

        # reservations.confirmed_datetime → confirmed_at
        if "reservations" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("reservations")]
            if "confirmed_datetime" in cols and "confirmed_at" not in cols:
                conn.execute(text("ALTER TABLE reservations RENAME COLUMN confirmed_datetime TO confirmed_at"))
                print("AUTO-MIGRATE: Renamed reservations.confirmed_datetime to confirmed_at")
            if "cancelled_datetime" in cols and "cancelled_at" not in cols:
                conn.execute(text("ALTER TABLE reservations RENAME COLUMN cancelled_datetime TO cancelled_at"))
                print("AUTO-MIGRATE: Renamed reservations.cancelled_datetime to cancelled_at")
            # Consecutive stay (연박) columns
            if "stay_group_id" not in cols:
                conn.execute(text("ALTER TABLE reservations ADD COLUMN stay_group_id VARCHAR(36)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reservations_stay_group_id ON reservations (stay_group_id)"))
                print("AUTO-MIGRATE: Added stay_group_id column to reservations table")
            if "stay_group_order" not in cols:
                conn.execute(text("ALTER TABLE reservations ADD COLUMN stay_group_order INTEGER"))
                print("AUTO-MIGRATE: Added stay_group_order column to reservations table")

        # template_schedules.is_once_per_stay
        if "template_schedules" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("template_schedules")]
            if "is_once_per_stay" not in cols:
                conn.execute(text("ALTER TABLE template_schedules ADD COLUMN is_once_per_stay BOOLEAN DEFAULT FALSE"))
                print("AUTO-MIGRATE: Added is_once_per_stay column to template_schedules table")

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

        # Migrate legacy 1:1 naver_biz_item_id to N:M room_biz_item_links
        rooms_with_old_biz = db.query(Room).filter(Room.naver_biz_item_id.isnot(None)).all()
        migrated = 0
        for room in rooms_with_old_biz:
            existing_link = db.query(RoomBizItemLink).filter(
                RoomBizItemLink.room_id == room.id,
                RoomBizItemLink.biz_item_id == room.naver_biz_item_id,
            ).first()
            if not existing_link:
                db.add(RoomBizItemLink(room_id=room.id, biz_item_id=room.naver_biz_item_id, tenant_id=room.tenant_id))
                migrated += 1
        if migrated:
            db.commit()
            import logging
            logging.getLogger(__name__).info(f"Migrated {migrated} room biz_item links from 1:1 to N:M")

    finally:
        db.close()
