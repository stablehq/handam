"""
Seed data - creates initial user accounts
"""
from sqlalchemy.orm import Session
from app.db.database import SessionLocal, init_db
from app.db.models import User, UserRole
from app.auth.utils import hash_password
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_seed_users(db: Session):
    """Create initial user accounts (upsert — skip if already exists)"""
    seed_users = [
        ("admin", "admin1234", "관리자", UserRole.SUPERADMIN),
        ("staff1", "staff1234", "직원1", UserRole.STAFF),
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
