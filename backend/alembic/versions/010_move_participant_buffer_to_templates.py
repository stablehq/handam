"""Move participant_buffer from template_schedules to message_templates

Revision ID: 010
Revises: 009
Create Date: 2026-03-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '010'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add participant_buffer to message_templates
    op.add_column(
        'message_templates',
        sa.Column('participant_buffer', sa.Integer(), nullable=True, server_default='0')
    )

    # 2. Migrate data: copy participant_buffer from template_schedules to message_templates
    #    For templates with multiple schedules, use the MAX value.
    op.execute("""
        UPDATE message_templates
        SET participant_buffer = (
            SELECT COALESCE(MAX(ts.participant_buffer), 0)
            FROM template_schedules ts
            WHERE ts.template_id = message_templates.id
        )
        WHERE EXISTS (
            SELECT 1 FROM template_schedules ts WHERE ts.template_id = message_templates.id
        )
    """)

    # 3. Set default 0 for templates with no schedules
    op.execute("""
        UPDATE message_templates
        SET participant_buffer = 0
        WHERE participant_buffer IS NULL
    """)

    # 4. Drop participant_buffer from template_schedules
    op.drop_column('template_schedules', 'participant_buffer')


def downgrade() -> None:
    # 1. Re-add participant_buffer to template_schedules
    op.add_column(
        'template_schedules',
        sa.Column('participant_buffer', sa.Integer(), nullable=True, server_default='0')
    )

    # 2. Migrate data back: copy from message_templates to all related schedules
    op.execute("""
        UPDATE template_schedules
        SET participant_buffer = (
            SELECT COALESCE(mt.participant_buffer, 0)
            FROM message_templates mt
            WHERE mt.id = template_schedules.template_id
        )
    """)

    # 3. Drop participant_buffer from message_templates
    op.drop_column('message_templates', 'participant_buffer')
