"""add payable payment and fixed asset

Revision ID: f8c1d2e3f4a6
Revises: e3f4a5b6c7d8
Create Date: 2025-03-08 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f8c1d2e3f4a6"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "payable_payment" not in existing_tables:
        op.create_table(
            "payable_payment",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("pembelian_id", sa.Integer(), nullable=False),
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
                ["pembelian_id"],
                ["pembelian.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["created_by"],
                ["user.id"],
                ondelete="SET NULL",
            ),
        )
        op.create_index(
            "ix_payable_payment_pembelian_id",
            "payable_payment",
            ["pembelian_id"],
        )
        op.create_index(
            "ix_payable_payment_paid_at",
            "payable_payment",
            ["paid_at"],
        )
        op.alter_column("payable_payment", "payment_method", server_default=None)

    if "fixed_asset" not in existing_tables:
        op.create_table(
            "fixed_asset",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("category", sa.String(length=100), nullable=True),
            sa.Column("acquisition_date", sa.Date(), nullable=False),
            sa.Column("cost", sa.Float(), nullable=False),
            sa.Column(
                "salvage_value",
                sa.Float(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "useful_life_months",
                sa.Integer(),
                nullable=False,
                server_default="12",
            ),
            sa.Column(
                "method",
                sa.String(length=20),
                nullable=False,
                server_default="straight_line",
            ),
            sa.Column("note", sa.String(length=255), nullable=True),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["created_by"],
                ["user.id"],
                ondelete="SET NULL",
            ),
        )
        op.create_index(
            "ix_fixed_asset_acquisition_date",
            "fixed_asset",
            ["acquisition_date"],
        )
        op.create_index(
            "ix_fixed_asset_is_active",
            "fixed_asset",
            ["is_active"],
        )


def downgrade():
    op.drop_index("ix_fixed_asset_is_active", table_name="fixed_asset")
    op.drop_index("ix_fixed_asset_acquisition_date", table_name="fixed_asset")
    op.drop_table("fixed_asset")

    op.drop_index("ix_payable_payment_paid_at", table_name="payable_payment")
    op.drop_index("ix_payable_payment_pembelian_id", table_name="payable_payment")
    op.drop_table("payable_payment")
