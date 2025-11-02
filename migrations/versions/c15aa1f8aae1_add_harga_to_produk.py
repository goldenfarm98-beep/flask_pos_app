"""Add harga to Produk

Revision ID: c15aa1f8aae1
Revises: 63debe259d43
Create Date: 2025-01-20 20:50:36.649643

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c15aa1f8aae1'
down_revision = '63debe259d43'
branch_labels = None
depends_on = None


def upgrade():
    # Tidak ada perubahan di sini karena kolom 'harga' sudah ada
    pass


def downgrade():
    # Jika perlu menghapus kolom 'harga', tetap tambahkan logika ini
    with op.batch_alter_table('produk', schema=None) as batch_op:
        batch_op.drop_column('harga')
