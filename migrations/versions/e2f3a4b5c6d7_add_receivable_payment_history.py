"""add receivable payment history

Revision ID: e2f3a4b5c6d7
Revises: d4b0c2ad8a71
Create Date: 2025-03-02 10:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e2f3a4b5c6d7"
down_revision = "d4b0c2ad8a71"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "receivable_payment" not in inspector.get_table_names():
        op.create_table(
            "receivable_payment",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("penjualan_id", sa.Integer(), nullable=False),
            sa.Column("amount", sa.Float(), nullable=False),
            sa.Column(
                "payment_method",
                sa.String(length=20),
                nullable=False,
                server_default="Tunai",
            ),
            sa.Column("reference", sa.String(length=100), nullable=True),
            sa.Column("note", sa.String(length=255), nullable=True),
            sa.Column("paid_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(
                ["penjualan_id"],
                ["penjualan.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["created_by"],
                ["user.id"],
                ondelete="SET NULL",
            ),
        )
        op.create_index(
            "ix_receivable_payment_penjualan_id",
            "receivable_payment",
            ["penjualan_id"],
        )
        op.create_index(
            "ix_receivable_payment_paid_at",
            "receivable_payment",
            ["paid_at"],
        )
        op.alter_column("receivable_payment", "payment_method", server_default=None)


def downgrade():
    op.drop_index("ix_receivable_payment_paid_at", table_name="receivable_payment")
    op.drop_index("ix_receivable_payment_penjualan_id", table_name="receivable_payment")
    op.drop_table("receivable_payment")
