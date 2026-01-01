"""add marketplace fee accounts to accounting setting

Revision ID: d1e2f3a4b5c6
Revises: c9d1e2f3a4b5
Create Date: 2025-12-29 13:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "c9d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "accounting_setting",
        sa.Column("marketplace_expense_account_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "accounting_setting",
        sa.Column("marketplace_payable_account_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_accounting_setting_marketplace_expense",
        "accounting_setting",
        "account",
        ["marketplace_expense_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_accounting_setting_marketplace_payable",
        "accounting_setting",
        "account",
        ["marketplace_payable_account_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        "fk_accounting_setting_marketplace_expense",
        "accounting_setting",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_accounting_setting_marketplace_payable",
        "accounting_setting",
        type_="foreignkey",
    )
    op.drop_column("accounting_setting", "marketplace_expense_account_id")
    op.drop_column("accounting_setting", "marketplace_payable_account_id")
