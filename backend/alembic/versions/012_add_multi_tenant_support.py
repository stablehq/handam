"""Add multi-tenant support

Revision ID: 012
Revises: 011
Create Date: 2026-03-19
"""
from alembic import op
import sqlalchemy as sa

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None

# All tables that need tenant_id
TENANT_TABLES = [
    'messages',
    'reservations',
    'rules',
    'documents',
    'message_templates',
    'reservation_sms_assignments',
    'campaign_logs',
    'gender_stats',
    'room_biz_item_links',
    'buildings',
    'rooms',
    'room_assignments',
    'naver_biz_items',
    'template_schedules',
    'activity_logs',
    'party_checkins',
    'reservation_daily_info',
    'participant_snapshots',
]


def upgrade():
    # 1. Create tenants table (skip if already created by create_all)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'tenants' not in inspector.get_table_names():
        op.create_table(
            'tenants',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('slug', sa.String(50), nullable=False, unique=True),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('naver_business_id', sa.String(50), nullable=True),
            sa.Column('naver_cookie', sa.Text(), nullable=True),
            sa.Column('naver_email', sa.String(200), nullable=True),
            sa.Column('naver_password', sa.String(200), nullable=True),
            sa.Column('aligo_sender', sa.String(20), nullable=True),
            sa.Column('is_active', sa.Boolean(), server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_tenants_slug', 'tenants', ['slug'])

    # 2. Insert default tenant (skip if exists)
    result = conn.execute(sa.text("SELECT id FROM tenants WHERE slug = 'handam'"))
    if result.fetchone() is None:
        op.execute("INSERT INTO tenants (id, slug, name, is_active) VALUES (1, 'handam', 'HANDAM', true)")

    # 3. Add tenant_id to all 18 tables (skip if already exists from create_all)
    for table in TENANT_TABLES:
        cols = [c['name'] for c in inspector.get_columns(table)]
        if 'tenant_id' not in cols:
            op.add_column(table, sa.Column('tenant_id', sa.Integer(), nullable=True))

    # 4. Set all existing rows to default tenant
    for table in TENANT_TABLES:
        op.execute(f"UPDATE {table} SET tenant_id = 1 WHERE tenant_id IS NULL")

    # 5. Make tenant_id NOT NULL
    for table in TENANT_TABLES:
        op.alter_column(table, 'tenant_id', nullable=False)

    # 6. Add indexes on tenant_id (skip if exists)
    for table in TENANT_TABLES:
        idx_name = f'ix_{table}_tenant_id'
        existing_idx = [i['name'] for i in inspector.get_indexes(table)]
        if idx_name not in existing_idx:
            op.create_index(idx_name, table, ['tenant_id'])

    # 7. Add foreign key constraints (skip if exists)
    for table in TENANT_TABLES:
        existing_fks = [fk['name'] for fk in inspector.get_foreign_keys(table)]
        fk_name = f'fk_{table}_tenant_id'
        if fk_name not in existing_fks:
            op.create_foreign_key(fk_name, table, 'tenants', ['tenant_id'], ['id'])

    # 8. Drop old unique constraints and create tenant-scoped ones (idempotent)
    def _swap_unique(table, old_name, new_name, new_cols):
        existing_uq = [c['name'] for c in inspector.get_unique_constraints(table)]
        if new_name in existing_uq:
            return  # Already migrated
        if old_name in existing_uq:
            op.drop_constraint(old_name, table, type_='unique')
        op.create_unique_constraint(new_name, table, new_cols)

    _swap_unique('message_templates', 'message_templates_key_key', 'uq_tenant_template_key', ['tenant_id', 'key'])
    _swap_unique('naver_biz_items', 'naver_biz_items_biz_item_id_key', 'uq_tenant_biz_item_id', ['tenant_id', 'biz_item_id'])
    _swap_unique('buildings', 'buildings_name_key', 'uq_tenant_building_name', ['tenant_id', 'name'])
    _swap_unique('participant_snapshots', 'participant_snapshots_date_key', 'uq_tenant_snapshot_date', ['tenant_id', 'date'])

    # 9. Create user_tenant_roles table (skip if exists)
    if 'user_tenant_roles' not in inspector.get_table_names():
        op.create_table(
            'user_tenant_roles',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('user_id', 'tenant_id', name='uq_user_tenant'),
        )

    # 10. Map existing active users to default tenant (skip if already mapped)
    op.execute("""
        INSERT INTO user_tenant_roles (user_id, tenant_id, created_at)
        SELECT id, 1, CURRENT_TIMESTAMP FROM users
        WHERE is_active = true
        AND id NOT IN (SELECT user_id FROM user_tenant_roles WHERE tenant_id = 1)
    """)


def downgrade():
    # Drop user_tenant_roles
    op.drop_table('user_tenant_roles')

    # Restore old unique constraints
    with op.batch_alter_table('participant_snapshots') as batch_op:
        batch_op.drop_constraint('uq_tenant_snapshot_date', type_='unique')
        batch_op.create_unique_constraint('uq_participant_snapshots_date', ['date'])

    with op.batch_alter_table('buildings') as batch_op:
        batch_op.drop_constraint('uq_tenant_building_name', type_='unique')
        batch_op.create_unique_constraint('uq_buildings_name', ['name'])

    with op.batch_alter_table('naver_biz_items') as batch_op:
        batch_op.drop_constraint('uq_tenant_biz_item_id', type_='unique')
        batch_op.create_unique_constraint('uq_naver_biz_items_biz_item_id', ['biz_item_id'])

    with op.batch_alter_table('message_templates') as batch_op:
        batch_op.drop_constraint('uq_tenant_template_key', type_='unique')
        batch_op.create_unique_constraint('uq_message_templates_key', ['key'])

    # Drop tenant_id from all tables
    for table in reversed(TENANT_TABLES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(f'fk_{table}_tenant_id', type_='foreignkey')
        op.drop_index(f'ix_{table}_tenant_id', table)
        op.drop_column(table, 'tenant_id')

    # Drop tenants table
    op.drop_index('ix_tenants_slug', 'tenants')
    op.drop_table('tenants')
