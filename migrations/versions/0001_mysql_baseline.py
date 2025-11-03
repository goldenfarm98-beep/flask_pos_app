"""Initial schema compatible with MySQL

Revision ID: 0001_mysql_baseline
Revises: 
Create Date: 2025-01-21 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0001_mysql_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'kategori',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'satuan',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'supplier',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('address', sa.String(length=200), nullable=False),
        sa.Column('phone', sa.String(length=50), nullable=False),
        sa.Column('bank_account', sa.String(length=100), nullable=False),
        sa.Column('account_name', sa.String(length=100), nullable=False),
        sa.Column('contact_person', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('website', sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', name='uq_supplier_email')
    )

    op.create_table(
        'user',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=80), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('password', sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', name='uq_user_email'),
        sa.UniqueConstraint('username', name='uq_user_username')
    )

    op.create_table(
        'pelanggan',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pelanggan_id', sa.String(length=50), nullable=False),
        sa.Column('nama', sa.String(length=100), nullable=False),
        sa.Column('kontak', sa.String(length=50), nullable=False),
        sa.Column('alamat', sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pelanggan_id', name='uq_pelanggan_kode')
    )

    op.create_table(
        'produk',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kode_produk', sa.String(length=50), nullable=False),
        sa.Column('sku', sa.String(length=50), nullable=True),
        sa.Column('barcode', sa.String(length=100), nullable=True),
        sa.Column('nama_produk', sa.String(length=100), nullable=False),
        sa.Column('harga', sa.Float(), nullable=False, server_default=sa.text('0')),
        sa.Column('satuan_id', sa.Integer(), nullable=True),
        sa.Column('kategori_id', sa.Integer(), nullable=True),
        sa.Column('supplier_id', sa.Integer(), nullable=True),
        sa.Column('berat', sa.Float(), nullable=True),
        sa.Column('stok_minimal', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('stok_lama', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('harga_lama', sa.Float(), nullable=False, server_default=sa.text('0')),
        sa.Column('harga_beli', sa.Float(), nullable=False, server_default=sa.text('0')),
        sa.Column('jumlah_beli', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('tanggal_expired', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['kategori_id'], ['kategori.id'], name='fk_produk_kategori', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['satuan_id'], ['satuan.id'], name='fk_produk_satuan', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['supplier_id'], ['supplier.id'], name='fk_produk_supplier', ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('barcode', name='uq_produk_barcode'),
        sa.UniqueConstraint('kode_produk', name='uq_produk_kode'),
        sa.UniqueConstraint('sku', name='uq_produk_sku')
    )

    op.create_index('ix_produk_kode_produk', 'produk', ['kode_produk'], unique=True)

    op.create_table(
        'pembelian',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tanggal_faktur', sa.Date(), nullable=False),
        sa.Column('no_faktur', sa.String(length=50), nullable=False),
        sa.Column('supplier_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['supplier_id'], ['supplier.id'], name='fk_pembelian_supplier'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('no_faktur', name='uq_pembelian_no_faktur')
    )

    op.create_table(
        'barang_pembelian',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pembelian_id', sa.Integer(), nullable=False),
        sa.Column('kode_barang', sa.String(length=50), nullable=False),
        sa.Column('nama_barang', sa.String(length=100), nullable=False),
        sa.Column('kategori', sa.String(length=100), nullable=False),
        sa.Column('jumlah', sa.Integer(), nullable=False),
        sa.Column('harga_beli', sa.Float(), nullable=False),
        sa.Column('diskon', sa.Float(), nullable=False, server_default=sa.text('0')),
        sa.Column('pajak', sa.Float(), nullable=False, server_default=sa.text('0')),
        sa.Column('harga_jual', sa.Float(), nullable=False),
        sa.Column('exp_date', sa.Date(), nullable=True),
        sa.Column('hpp', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['kode_barang'], ['produk.kode_produk'], name='fk_barang_pembelian_kode', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pembelian_id'], ['pembelian.id'], name='fk_barang_pembelian_pembelian', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'penjualan',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('no_faktur', sa.String(length=50), nullable=False),
        sa.Column('tanggal_penjualan', sa.Date(), nullable=False),
        sa.Column('sales_id', sa.Integer(), nullable=False),
        sa.Column('pelanggan_id', sa.Integer(), nullable=False),
        sa.Column('total_harga', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['pelanggan_id'], ['pelanggan.id'], name='fk_penjualan_pelanggan'),
        sa.ForeignKeyConstraint(['sales_id'], ['user.id'], name='fk_penjualan_user'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('no_faktur', name='uq_penjualan_no_faktur')
    )

    op.create_table(
        'detail_penjualan',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('penjualan_id', sa.Integer(), nullable=False),
        sa.Column('produk_id', sa.Integer(), nullable=False),
        sa.Column('jumlah', sa.Integer(), nullable=False),
        sa.Column('harga_satuan', sa.Float(), nullable=False),
        sa.Column('diskon', sa.Float(), nullable=False, server_default=sa.text('0')),
        sa.Column('pajak', sa.Float(), nullable=False, server_default=sa.text('0')),
        sa.Column('harga_total', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['penjualan_id'], ['penjualan.id'], name='fk_detail_penjualan_penjualan', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['produk_id'], ['produk.id'], name='fk_detail_penjualan_produk'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('detail_penjualan')
    op.drop_table('penjualan')
    op.drop_table('barang_pembelian')
    op.drop_table('pembelian')
    op.drop_index('ix_produk_kode_produk', table_name='produk')
    op.drop_table('produk')
    op.drop_table('pelanggan')
    op.drop_table('user')
    op.drop_table('supplier')
    op.drop_table('satuan')
    op.drop_table('kategori')
