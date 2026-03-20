"""Drop stale global unique indexes left over from pre-tenant era

SQLAlchemy auto-created UNIQUE indexes (ix_*) on columns that are now
tenant-scoped via composite unique constraints (uq_tenant_*).
The global UNIQUE indexes prevent the same value across different tenants.

Affected:
- ix_message_templates_key       → uq_tenant_template_key (tenant_id, key)
- ix_messages_message_id         → uq_tenant_message_id (tenant_id, message_id)
- ix_reservations_external_id    → uq_tenant_external_id (tenant_id, external_id)
- ix_participant_snapshots_date  → uq_tenant_snapshot_date (tenant_id, date)
- ix_naver_biz_items_biz_item_id → uq_tenant_biz_item_id (tenant_id, biz_item_id)
  (requires dropping room_biz_item_links FK first, then recreating as plain index)

Revision ID: 015
Revises: 014
"""
from alembic import op
import sqlalchemy as sa

revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None

# (table, index_name, columns)
SIMPLE_DROPS = [
    ('message_templates', 'ix_message_templates_key', ['key']),
    ('messages', 'ix_messages_message_id', ['message_id']),
    ('reservations', 'ix_reservations_external_id', ['external_id']),
    ('participant_snapshots', 'ix_participant_snapshots_date', ['date']),
]


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # 1. Drop simple global unique indexes
    for table, idx_name, _ in SIMPLE_DROPS:
        indexes = [i['name'] for i in inspector.get_indexes(table)]
        if idx_name in indexes:
            op.drop_index(idx_name, table_name=table)

    # 2. naver_biz_items: drop FK dependency first, then unique index, recreate as plain
    nbi_indexes = [i['name'] for i in inspector.get_indexes('naver_biz_items')]
    if 'ix_naver_biz_items_biz_item_id' in nbi_indexes:
        # Check if FK exists before trying to drop
        fks = [fk['name'] for fk in inspector.get_foreign_keys('room_biz_item_links')]
        if 'room_biz_item_links_biz_item_id_fkey' in fks:
            op.drop_constraint('room_biz_item_links_biz_item_id_fkey', 'room_biz_item_links', type_='foreignkey')
        op.drop_index('ix_naver_biz_items_biz_item_id', table_name='naver_biz_items')
        op.create_index('ix_naver_biz_items_biz_item_id', 'naver_biz_items', ['biz_item_id'], unique=False)


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Restore naver_biz_items unique index and FK
    op.drop_index('ix_naver_biz_items_biz_item_id', table_name='naver_biz_items')
    op.create_index('ix_naver_biz_items_biz_item_id', 'naver_biz_items', ['biz_item_id'], unique=True)
    fks = [fk['name'] for fk in inspector.get_foreign_keys('room_biz_item_links')]
    if 'room_biz_item_links_biz_item_id_fkey' not in fks:
        op.create_foreign_key(
            'room_biz_item_links_biz_item_id_fkey',
            'room_biz_item_links', 'naver_biz_items',
            ['biz_item_id'], ['biz_item_id'],
        )

    # Restore simple unique indexes
    for table, idx_name, columns in SIMPLE_DROPS:
        op.create_index(idx_name, table, columns, unique=True)
