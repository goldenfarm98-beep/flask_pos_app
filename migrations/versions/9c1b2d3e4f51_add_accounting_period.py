"""create accounting period tracking

Revision ID: 9c1b2d3e4f51
Revises: 2f0c7f754660
Create Date: 2025-11-11 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9c1b2d3e4f51"
down_revision = "da213da7027c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "accounting_period",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'open'")),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("closed_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["closed_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("label"),
    )

    op.add_column(
        "journal_entry",
        sa.Column("accounting_period_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "journal_entry",
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.create_foreign_key(
        "fk_journal_entry_accounting_period",
        "journal_entry",
        "accounting_period",
        ["accounting_period_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "penjualan",
        sa.Column("accounting_period_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "penjualan",
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.create_foreign_key(
        "fk_penjualan_accounting_period",
        "penjualan",
        "accounting_period",
        ["accounting_period_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "pembelian",
        sa.Column("accounting_period_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "pembelian",
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.create_foreign_key(
        "fk_pembelian_accounting_period",
        "pembelian",
        "accounting_period",
        ["accounting_period_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_pembelian_accounting_period", "pembelian", type_="foreignkey")
    op.drop_column("pembelian", "is_locked")
    op.drop_column("pembelian", "accounting_period_id")

    op.drop_constraint("fk_penjualan_accounting_period", "penjualan", type_="foreignkey")
    op.drop_column("penjualan", "is_locked")
    op.drop_column("penjualan", "accounting_period_id")

    op.drop_constraint("fk_journal_entry_accounting_period", "journal_entry", type_="foreignkey")
    op.drop_column("journal_entry", "is_locked")
    op.drop_column("journal_entry", "accounting_period_id")

    op.drop_table("accounting_period")
