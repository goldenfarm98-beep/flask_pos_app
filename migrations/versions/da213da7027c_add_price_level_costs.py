"""add price level costs

Revision ID: da213da7027c
Revises: 2d8b89ae7897
Create Date: 2025-11-10 23:45:38.754994

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "da213da7027c"
down_revision = "2d8b89ae7897"
branch_labels = None
depends_on = None


def upgrade():
    cost_type_enum = sa.Enum("percent", "nominal", name="price_level_cost_type")
    cost_type_enum.create(op.get_bind(), checkfirst=False)

    op.add_column(
        "penjualan",
        sa.Column(
            "price_level_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "penjualan",
        sa.Column(
            "marketplace_cost_total",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "penjualan",
        sa.Column(
            "marketplace_cost_details",
            sa.Text(),
            nullable=True,
            server_default="[]",
        ),
    )

    op.create_foreign_key(
        "fk_penjualan_price_level_id_price_level",
        "penjualan",
        "price_level",
        ["price_level_id"],
        ["id"],
    )

    op.create_table(
        "price_level_cost",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "level_id",
            sa.Integer(),
            sa.ForeignKey("price_level.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("type", cost_type_enum, nullable=False),
        sa.Column("value", sa.Float(), nullable=False, default=0.0),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade():
    op.drop_table("price_level_cost")
    op.drop_constraint(
        "fk_penjualan_price_level_id_price_level", "penjualan", type_="foreignkey"
    )
    op.drop_column("penjualan", "marketplace_cost_details")
    op.drop_column("penjualan", "marketplace_cost_total")
    op.drop_column("penjualan", "price_level_id")
    sa.Enum("percent", "nominal", name="price_level_cost_type").drop(
        op.get_bind(), checkfirst=False
    )
