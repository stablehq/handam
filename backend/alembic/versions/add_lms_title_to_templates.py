"""Add lms_title to message_templates

Revision ID: add_lms_title
Revises: add_room_memo
Create Date: 2026-05-04 12:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = 'add_lms_title'
down_revision: Union[str, None] = 'add_room_memo'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('message_templates', sa.Column('lms_title', sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column('message_templates', 'lms_title')
