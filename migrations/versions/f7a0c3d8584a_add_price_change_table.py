"""add price change log table

Revision ID: f7a0c3d8584a
Revises: 8b7835f8c0f1
Create Date: 2025-11-08 14:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f7a0c3d8584a'
down_revision = '8b7835f8c0f1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'price_change',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('price_level_id', sa.Integer(), nullable=True),
        sa.Column('old_price', sa.Float(), nullable=False, server_default='0'),
        sa.Column('new_price', sa.Float(), nullable=False, server_default='0'),
        sa.Column('margin_before', sa.Float(), nullable=False, server_default='0'),
        sa.Column('margin_after', sa.Float(), nullable=False, server_default='0'),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['price_level_id'], ['price_level.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['product_id'], ['produk.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('price_change')
