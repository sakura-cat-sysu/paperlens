"""add model protocol to model_configs"""

import sqlalchemy as sa
from alembic import op


revision = '9f3c7a5b1e2d'
down_revision = '8f2c5a1d7b3e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'model_configs',
        sa.Column('protocol', sa.String(length=20), nullable=False, server_default='chat'),
    )


def downgrade():
    op.drop_column('model_configs', 'protocol')
