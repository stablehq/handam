"""Add male_priority and female_priority to room_biz_item_links

Revision ID: 011
Revises: 010
Create Date: 2026-03-19
"""
from alembic import op
import sqlalchemy as sa

revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('room_biz_item_links', sa.Column('male_priority', sa.Integer(), server_default='0', nullable=True))
    op.add_column('room_biz_item_links', sa.Column('female_priority', sa.Integer(), server_default='0', nullable=True))


def downgrade():
    op.drop_column('room_biz_item_links', 'female_priority')
    op.drop_column('room_biz_item_links', 'male_priority')
