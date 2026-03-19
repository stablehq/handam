"""Add date to reservation_sms_assignments and target_mode to template_schedules

Revision ID: 007
Revises: 4fbe178197f2
Create Date: 2026-03-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '007'
down_revision: Union[str, None] = '4fbe178197f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add target_mode to template_schedules
    op.add_column('template_schedules', sa.Column('target_mode', sa.String(20), nullable=True, server_default='once'))

    # 2. Add date to reservation_sms_assignments (nullable first for backfill)
    op.add_column('reservation_sms_assignments', sa.Column('date', sa.String(20), nullable=True))

    # 3. Backfill date from reservations (check_in_date is stored in "date" column)
    op.execute("""
        UPDATE reservation_sms_assignments
        SET date = (
            SELECT date FROM reservations
            WHERE reservations.id = reservation_sms_assignments.reservation_id
        )
    """)

    # 4. Set default for any remaining NULLs
    op.execute("UPDATE reservation_sms_assignments SET date = '' WHERE date IS NULL")

    # 5. Drop old unique constraint and add new one with date column (SQLite-compatible)
    with op.batch_alter_table('reservation_sms_assignments') as batch_op:
        batch_op.drop_constraint('uq_res_sms_template', type_='unique')
        batch_op.create_unique_constraint(
            'uq_res_sms_template_date',
            ['reservation_id', 'template_key', 'date']
        )


def downgrade() -> None:
    # Reverse constraint change
    with op.batch_alter_table('reservation_sms_assignments') as batch_op:
        batch_op.drop_constraint('uq_res_sms_template_date', type_='unique')
        batch_op.create_unique_constraint(
            'uq_res_sms_template',
            ['reservation_id', 'template_key']
        )

    op.drop_column('reservation_sms_assignments', 'date')
    op.drop_column('template_schedules', 'target_mode')
