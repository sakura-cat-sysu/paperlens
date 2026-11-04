"""replace model_settings with multi-config model_configs"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision = '8f2c5a1d7b3e'
down_revision = '3b7c1e9d42a0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'model_configs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('owner_id', sa.String(length=36), nullable=True),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('api_key_cipher', sa.String(length=1024), nullable=False),
        sa.Column('api_key_hint', sa.String(length=32), nullable=False),
        sa.Column('base_url', sa.String(length=300), nullable=False),
        sa.Column('model', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_id', 'name'),
    )
    op.create_index(op.f('ix_model_configs_owner_id'), 'model_configs', ['owner_id'], unique=False)
    op.add_column('analysis_jobs', sa.Column('model_config_id', sa.String(length=36), nullable=True))

    # 把原来「每账号一条」的配置搬成新表里的单条记录，密钥密文原样保留。
    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                "SELECT scope, api_key_cipher, api_key_hint, base_url, model, updated_at"
                " FROM model_settings"
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        scope = row['scope']
        owner = None if scope == 'global' else scope.split(':', 1)[-1]
        bind.execute(
            sa.text(
                "INSERT INTO model_configs (id, owner_id, name, api_key_cipher, api_key_hint,"
                " base_url, model, created_at, updated_at)"
                " VALUES (:id, :owner, :name, :cipher, :hint, :base, :model, :ts, :ts)"
            ),
            {
                'id': str(uuid4()),
                'owner': owner,
                'name': '全局配置' if owner is None else '配置 1',
                'cipher': row['api_key_cipher'],
                'hint': row['api_key_hint'],
                'base': row['base_url'],
                'model': row['model'],
                'ts': row['updated_at'],
            },
        )
    op.drop_table('model_settings')


def downgrade():
    op.create_table(
        'model_settings',
        sa.Column('scope', sa.String(length=80), nullable=False),
        sa.Column('api_key_cipher', sa.String(length=1024), nullable=False),
        sa.Column('api_key_hint', sa.String(length=32), nullable=False),
        sa.Column('base_url', sa.String(length=300), nullable=False),
        sa.Column('model', sa.String(length=120), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('scope'),
    )
    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                "SELECT owner_id, api_key_cipher, api_key_hint, base_url, model, updated_at"
                " FROM model_configs ORDER BY created_at"
            )
        )
        .mappings()
        .all()
    )
    seen: set[str] = set()
    for row in rows:
        scope = 'global' if row['owner_id'] is None else f"user:{row['owner_id']}"
        if scope in seen:
            continue
        seen.add(scope)
        bind.execute(
            sa.text(
                "INSERT INTO model_settings (scope, api_key_cipher, api_key_hint, base_url,"
                " model, updated_at) VALUES (:scope, :cipher, :hint, :base, :model, :ts)"
            ),
            {
                'scope': scope,
                'cipher': row['api_key_cipher'],
                'hint': row['api_key_hint'],
                'base': row['base_url'],
                'model': row['model'],
                'ts': row['updated_at'],
            },
        )
    op.drop_column('analysis_jobs', 'model_config_id')
    op.drop_index(op.f('ix_model_configs_owner_id'), table_name='model_configs')
    op.drop_table('model_configs')
