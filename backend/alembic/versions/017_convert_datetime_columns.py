"""Convert confirmed_at/cancelled_at from String to DateTime

Revision ID: 017
Revises: aceea3667c87
Create Date: 2026-04-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '017'
down_revision: Union[str, None] = 'aceea3667c87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Convert empty strings to NULL first
    op.execute("UPDATE reservations SET confirmed_at = NULL WHERE confirmed_at = ''")
    op.execute("UPDATE reservations SET cancelled_at = NULL WHERE cancelled_at = ''")

    # Alter column types
    op.alter_column('reservations', 'confirmed_at',
                     type_=sa.DateTime(),
                     existing_type=sa.String(50),
                     postgresql_using='confirmed_at::timestamp')
    op.alter_column('reservations', 'cancelled_at',
                     type_=sa.DateTime(),
                     existing_type=sa.String(50),
                     postgresql_using='cancelled_at::timestamp')


def downgrade() -> None:
    op.alter_column('reservations', 'confirmed_at',
                     type_=sa.String(50),
                     existing_type=sa.DateTime())
    op.alter_column('reservations', 'cancelled_at',
                     type_=sa.String(50),
                     existing_type=sa.DateTime())
