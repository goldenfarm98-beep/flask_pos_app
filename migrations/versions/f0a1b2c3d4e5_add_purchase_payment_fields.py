"""add purchase payment fields

Revision ID: f0a1b2c3d4e5
Revises: e2f3a4b5c6d7
Create Date: 2025-03-02 11:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f0a1b2c3d4e5"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("pembelian")}
    if "due_date" not in columns:
        op.add_column("pembelian", sa.Column("due_date", sa.Date(), nullable=True))
    if "payment_bank" not in columns:
        op.add_column(
            "pembelian", sa.Column("payment_bank", sa.String(length=120), nullable=True)
        )
    if "payment_reference" not in columns:
        op.add_column(
            "pembelian",
            sa.Column("payment_reference", sa.String(length=100), nullable=True),
        )


def downgrade():
    op.drop_column("pembelian", "payment_reference")
    op.drop_column("pembelian", "payment_bank")
    op.drop_column("pembelian", "due_date")
