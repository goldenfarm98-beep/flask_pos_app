"""add price level tables and customer relation

Revision ID: 8b7835f8c0f1
Revises: 4f4e3b2c1d9a
Create Date: 2025-11-07 06:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8b7835f8c0f1'
down_revision = '4f4e3b2c1d9a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'price_level',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    op.create_table(
        'product_price_level',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('level_id', sa.Integer(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['level_id'], ['price_level.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['produk.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('product_id', 'level_id', name='uq_product_level_price')
    )

    op.add_column('pelanggan', sa.Column('price_level_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_pelanggan_price_level',
        'pelanggan',
        'price_level',
        ['price_level_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade():
    op.drop_constraint('fk_pelanggan_price_level', 'pelanggan', type_='foreignkey')
    op.drop_column('pelanggan', 'price_level_id')
    op.drop_table('product_price_level')
    op.drop_table('price_level')
