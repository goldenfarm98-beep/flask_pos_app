"""add jenis pembayaran

Revision ID: 2d8b89ae7897
Revises: 2c9d6c2f6c7d
Create Date: 2025-11-09 06:31:04.304381

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2d8b89ae7897'
down_revision = '2c9d6c2f6c7d'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "pembelian",
        sa.Column(
            "jenis_pembayaran",
            sa.String(length=20),
            nullable=False,
            server_default="Tunai",
        ),
    )
    op.execute(
        "UPDATE pembelian SET jenis_pembayaran = COALESCE(jenis_pembayaran, 'Tunai')"
    )
    op.alter_column(
        "pembelian",
        "jenis_pembayaran",
        server_default=None,
        existing_type=sa.String(length=20),
        nullable=False,
    )


def downgrade():
    op.drop_column("pembelian", "jenis_pembayaran")
