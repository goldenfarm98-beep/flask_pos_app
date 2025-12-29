"""add marketplace pricing settings

Revision ID: f2c3d4e5f6a7
Revises: f0a1b2c3d4e5
Create Date: 2025-12-25 23:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f2c3d4e5f6a7"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "marketplace_pricing_setting",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_name", sa.String(length=150), nullable=True),
        sa.Column("sku", sa.String(length=80), nullable=True),
        sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("packing", sa.Float(), nullable=False, server_default="0"),
        sa.Column("target_profit", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fee_primary", sa.Float(), nullable=False, server_default="0.18"),
        sa.Column("fee_secondary", sa.Float(), nullable=False, server_default="0.105"),
        sa.Column("rounding_mode", sa.String(length=30), nullable=False, server_default="round_100"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
    )


def downgrade():
    op.drop_table("marketplace_pricing_setting")
