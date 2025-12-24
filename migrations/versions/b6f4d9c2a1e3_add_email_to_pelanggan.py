"""add email to pelanggan

Revision ID: b6f4d9c2a1e3
Revises: c7c74dd53942
Create Date: 2025-01-05 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b6f4d9c2a1e3"
down_revision = "c7c74dd53942"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pelanggan", sa.Column("email", sa.String(length=120), nullable=True))


def downgrade():
    op.drop_column("pelanggan", "email")
