"""add expedisi and sales payment fields

Revision ID: c2a8c5e4d7f1
Revises: b6f4d9c2a1e3
Create Date: 2025-01-05 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c2a8c5e4d7f1"
down_revision = "b6f4d9c2a1e3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "expedisi",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("address", sa.String(length=200), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
    )
    op.add_column("penjualan", sa.Column("expedition_id", sa.Integer(), nullable=True))
    op.add_column("penjualan", sa.Column("shipping_fee", sa.Float(), nullable=False, server_default="0"))
    op.add_column("penjualan", sa.Column("total_weight", sa.Float(), nullable=False, server_default="0"))
    op.add_column("penjualan", sa.Column("payment_method", sa.String(length=20), nullable=True))
    op.add_column("penjualan", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("penjualan", sa.Column("amount_paid", sa.Float(), nullable=False, server_default="0"))
    op.add_column("penjualan", sa.Column("change_due", sa.Float(), nullable=False, server_default="0"))
    op.create_foreign_key(
        "fk_penjualan_expedisi",
        "penjualan",
        "expedisi",
        ["expedition_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("penjualan", "shipping_fee", server_default=None)
    op.alter_column("penjualan", "total_weight", server_default=None)
    op.alter_column("penjualan", "amount_paid", server_default=None)
    op.alter_column("penjualan", "change_due", server_default=None)


def downgrade():
    op.drop_constraint("fk_penjualan_expedisi", "penjualan", type_="foreignkey")
    op.drop_column("penjualan", "change_due")
    op.drop_column("penjualan", "amount_paid")
    op.drop_column("penjualan", "due_date")
    op.drop_column("penjualan", "payment_method")
    op.drop_column("penjualan", "total_weight")
    op.drop_column("penjualan", "shipping_fee")
    op.drop_column("penjualan", "expedition_id")
    op.drop_table("expedisi")
