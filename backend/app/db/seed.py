"""
Seed data - creates initial user accounts
"""
from sqlalchemy.orm import Session
from app.db.database import SessionLocal, init_db
from app.db.models import User, UserRole
from app.auth.utils import hash_password
from app.config import settings, _auto_generated
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_seed_users(db: Session):
    """Create initial user accounts (upsert — skip if already exists)"""
    seed_users = [
        ("admin", settings.ADMIN_DEFAULT_PASSWORD, "관리자", UserRole.SUPERADMIN),
        ("staff1", settings.STAFF_DEFAULT_PASSWORD, "직원1", UserRole.STAFF),
    ]
    created = 0
    for username, password, name, role in seed_users:
        existing = db.query(User).filter(User.username == username).first()
        if not existing:
            user = User(
                username=username,
                hashed_password=hash_password(password),
                name=name,
                role=role,
                is_active=True,
            )
            db.add(user)
            created += 1
    if created:
        db.flush()
        # 자동 생성된 비밀번호인 경우 콘솔에 출력
        if _auto_generated["admin_pw"] or _auto_generated["staff_pw"]:
            logger.info("=" * 50)
            logger.info("생성된 계정 비밀번호:")
            if _auto_generated["admin_pw"]:
                logger.info(f"  admin: {settings.ADMIN_DEFAULT_PASSWORD}")
            if _auto_generated["staff_pw"]:
                logger.info(f"  staff1: {settings.STAFF_DEFAULT_PASSWORD}")
            logger.info("=" * 50)
    logger.info(f"Seed users: {created} created, {len(seed_users) - created} already existed")


def seed_all():
    """Run all seed functions"""
    logger.info("Initializing database...")
    init_db()

    logger.info("Seeding data...")
    db = SessionLocal()
    try:
        # Create seed users (upsert — don't delete existing users)
        create_seed_users(db)

        db.commit()
        logger.info("✅ Seeding completed successfully!")
    except Exception as e:
        logger.error(f"❌ Seeding failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_all()
