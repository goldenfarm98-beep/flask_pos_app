"""add inventory adjustment account to accounting setting

Revision ID: e3f4a5b6c7d8
Revises: d1e2f3a4b5c6
Create Date: 2026-01-05 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e3f4a5b6c7d8"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "accounting_setting",
        sa.Column("inventory_adjustment_account_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_accounting_setting_inventory_adjustment",
        "accounting_setting",
        "account",
        ["inventory_adjustment_account_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        "fk_accounting_setting_inventory_adjustment",
        "accounting_setting",
        type_="foreignkey",
    )
    op.drop_column("accounting_setting", "inventory_adjustment_account_id")
