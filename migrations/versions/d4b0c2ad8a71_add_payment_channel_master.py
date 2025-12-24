"""add payment channel master

Revision ID: d4b0c2ad8a71
Revises: c2a8c5e4d7f1
Create Date: 2025-01-05 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4b0c2ad8a71"
down_revision = "c2a8c5e4d7f1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_channel",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("channel_type", sa.String(length=20), nullable=False, server_default="Kartu"),
        sa.Column("note", sa.String(length=255), nullable=True),
    )
    op.add_column("penjualan", sa.Column("payment_channel_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_penjualan_payment_channel",
        "penjualan",
        "payment_channel",
        ["payment_channel_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("payment_channel", "channel_type", server_default=None)


def downgrade():
    op.drop_constraint("fk_penjualan_payment_channel", "penjualan", type_="foreignkey")
    op.drop_column("penjualan", "payment_channel_id")
    op.drop_table("payment_channel")
