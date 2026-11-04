"""add independent guest identities and entry rate limits"""

from alembic import op
import sqlalchemy as sa

revision = "21ae7b947d20"
down_revision = "e414b7d846fa"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("is_guest", sa.Boolean(), server_default="false", nullable=False))
    op.create_table(
        "guest_identities",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_guest_identities_expires_at", "guest_identities", ["expires_at"])
    op.create_table(
        "guest_entry_rates",
        sa.Column("address_hash", sa.String(64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("address_hash"),
    )


def downgrade():
    op.drop_table("guest_entry_rates")
    op.drop_index("ix_guest_identities_expires_at", table_name="guest_identities")
    op.drop_table("guest_identities")
    op.drop_column("users", "is_guest")
