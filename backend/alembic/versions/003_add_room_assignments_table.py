"""Add room_assignments table for per-date room assignment

Revision ID: 003
Revises: 002
Create Date: 2026-03-11

This migration adds:
- room_assignments table with per-date room assignment tracking
- Backfill from existing reservation.room_number data

NOTE: PostgreSQL-only migration.
Uses SERIAL, LATERAL, generate_series(), and ::date/::text casts which are
PostgreSQL-specific syntax. This migration will fail on SQLite (demo mode).
Run only against a PostgreSQL database (DEMO_MODE=false).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    # Create room_assignments table
    op.execute("""
CREATE TABLE IF NOT EXISTS room_assignments (
    id SERIAL PRIMARY KEY,
    reservation_id INTEGER NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
    date VARCHAR(20) NOT NULL,
    room_number VARCHAR(20) NOT NULL,
    room_password VARCHAR(20),
    sms_sent BOOLEAN DEFAULT FALSE,
    sms_sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
""")

    # Unique constraint: one room per reservation per date
    op.execute("""
ALTER TABLE room_assignments ADD CONSTRAINT uq_room_assignment_res_date UNIQUE (reservation_id, date);
""")

    # Index for occupancy queries
    op.execute("""
CREATE INDEX ix_room_assignment_date_room ON room_assignments (date, room_number);
""")

    # Index for reservation lookups
    op.execute("""
CREATE INDEX ix_room_assignment_reservation_id ON room_assignments (reservation_id);
""")

    # Backfill room_assignments from existing reservation.room_number data
    # For multi-night: create one record per date in [date, end_date)
    # For single night: create one record for date
    op.execute("""
INSERT INTO room_assignments (reservation_id, date, room_number, room_password, sms_sent, sms_sent_at, created_at, updated_at)
SELECT
    r.id,
    d.date::text,
    r.room_number,
    r.room_password,
    r.room_sms_sent,
    r.room_sms_sent_at,
    NOW(),
    NOW()
FROM reservations r
CROSS JOIN LATERAL generate_series(
    r.date::date,
    COALESCE((r.end_date::date - interval '1 day')::date, r.date::date),
    interval '1 day'
) AS d(date)
WHERE r.room_number IS NOT NULL;
""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS room_assignments;")
