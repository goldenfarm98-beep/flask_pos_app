"""add stock opname session tables

Revision ID: 1c5bcd87f132
Revises: f7a0c3d8584a
Create Date: 2025-11-08 15:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1c5bcd87f132'
down_revision = 'f7a0c3d8584a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'stock_opname_session',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reference', sa.String(length=50), nullable=False),
        sa.Column('location', sa.String(length=100), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('finalized_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reference')
    )

    op.create_table(
        'stock_opname_item',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('system_qty', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('counted_qty', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('difference_qty', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['produk.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['session_id'], ['stock_opname_session.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('stock_opname_item')
    op.drop_table('stock_opname_session')
