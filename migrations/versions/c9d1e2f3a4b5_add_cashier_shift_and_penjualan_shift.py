"""add cashier shift for penjualan

Revision ID: c9d1e2f3a4b5
Revises: a7b8c9d0e1f2
Create Date: 2025-12-29 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c9d1e2f3a4b5"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cashier_shift",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("shift_date", sa.Date(), nullable=False),
        sa.Column(
            "opened_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "closed_by",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "forced_close",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("user_id", "shift_date", name="uq_cashier_shift_user_date"),
    )

    op.add_column("penjualan", sa.Column("shift_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_penjualan_shift_id",
        "penjualan",
        "cashier_shift",
        ["shift_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_penjualan_shift_id", "penjualan", type_="foreignkey")
    op.drop_column("penjualan", "shift_id")
    op.drop_table("cashier_shift")
