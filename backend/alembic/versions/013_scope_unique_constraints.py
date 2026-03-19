"""Scope message_id and external_id unique constraints to tenant

Revision ID: 013
Revises: 012
Create Date: 2026-03-19
"""
from alembic import op
import sqlalchemy as sa

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # messages.message_id: global unique -> (tenant_id, message_id) unique
    existing_uq = [c['name'] for c in inspector.get_unique_constraints('messages')]
    if 'uq_tenant_message_id' not in existing_uq:
        for name in ['messages_message_id_key', 'uq_messages_message_id']:
            if name in existing_uq:
                op.drop_constraint(name, 'messages', type_='unique')
                break
        op.create_unique_constraint('uq_tenant_message_id', 'messages', ['tenant_id', 'message_id'])

    # reservations.external_id: global unique -> (tenant_id, external_id) unique
    existing_uq = [c['name'] for c in inspector.get_unique_constraints('reservations')]
    if 'uq_tenant_external_id' not in existing_uq:
        for name in ['reservations_external_id_key', 'uq_reservations_external_id']:
            if name in existing_uq:
                op.drop_constraint(name, 'reservations', type_='unique')
                break
        op.create_unique_constraint('uq_tenant_external_id', 'reservations', ['tenant_id', 'external_id'])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    existing_uq = [c['name'] for c in inspector.get_unique_constraints('messages')]
    if 'uq_tenant_message_id' in existing_uq:
        op.drop_constraint('uq_tenant_message_id', 'messages', type_='unique')
        op.create_unique_constraint('messages_message_id_key', 'messages', ['message_id'])

    existing_uq = [c['name'] for c in inspector.get_unique_constraints('reservations')]
    if 'uq_tenant_external_id' in existing_uq:
        op.drop_constraint('uq_tenant_external_id', 'reservations', type_='unique')
        op.create_unique_constraint('reservations_external_id_key', 'reservations', ['external_id'])
