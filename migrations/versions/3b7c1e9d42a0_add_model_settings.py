"""add model settings for per-user and global model configuration"""

from alembic import op
import sqlalchemy as sa


revision = '3b7c1e9d42a0'
down_revision = '21ae7b947d20'
branch_labels = None
depends_on = None


def upgrade():
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


def downgrade():
    op.drop_table('model_settings')
