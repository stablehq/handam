"""add party_hosts table

Revision ID: d8df417f1b7c
Revises: 017
Create Date: 2026-04-10 10:39:32.374094
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd8df417f1b7c'
down_revision: Union[str, None] = '017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'party_hosts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id'), nullable=False),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_party_host_tenant_name'),
    )


def downgrade() -> None:
    op.drop_table('party_hosts')
