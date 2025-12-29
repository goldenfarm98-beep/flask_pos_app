"""add expedisi volumetric items and volume divisor

Revision ID: a7b8c9d0e1f2
Revises: f2c3d4e5f6a7
Create Date: 2025-12-26 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "f2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "expedisi",
        sa.Column(
            "volume_divisor", sa.Float(), nullable=True, server_default="6000"
        ),
    )

    op.create_table(
        "expedisi_volumetric_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("expedisi_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("packaging", sa.String(length=50), nullable=False),
        sa.Column("qty_per_pack", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("length_cm", sa.Float(), nullable=False),
        sa.Column("width_cm", sa.Float(), nullable=False),
        sa.Column("height_cm", sa.Float(), nullable=False),
        sa.Column("actual_weight", sa.Float(), nullable=True),
        sa.Column(
            "use_volumetric",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("note", sa.String(length=255), nullable=True),
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
        sa.ForeignKeyConstraint(["expedisi_id"], ["expedisi.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["produk.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "expedisi_id",
            "product_id",
            "packaging",
            name="uq_expedisi_product_packaging",
        ),
    )


def downgrade():
    op.drop_table("expedisi_volumetric_item")
    op.drop_column("expedisi", "volume_divisor")
