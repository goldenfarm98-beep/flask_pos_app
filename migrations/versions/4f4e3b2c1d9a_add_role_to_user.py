"""add role column to user table

Revision ID: 4f4e3b2c1d9a
Revises: 012a528ea987
Create Date: 2025-11-07 05:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4f4e3b2c1d9a'
down_revision = '012a528ea987'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('role', sa.String(length=50), nullable=False, server_default='sales'))
    op.execute("UPDATE user SET role = 'sales' WHERE role IS NULL OR role = ''")
    op.alter_column('user', 'role', server_default=None)


def downgrade():
    op.drop_column('user', 'role')
