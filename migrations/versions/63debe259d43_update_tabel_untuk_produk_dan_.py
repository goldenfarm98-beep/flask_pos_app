"""Update tabel untuk Produk dan BarangPembelian

Revision ID: 63debe259d43
Revises: bb1805b2b273
Create Date: 2025-01-20 02:11:01.748343

"""
from alembic import op
import sqlalchemy as sa


# Revision identifiers, used by Alembic.
revision = '63debe259d43'
down_revision = 'bb1805b2b273'
branch_labels = None
depends_on = None

def upgrade():
    # Membuat tabel `barang_pembelian`
    op.create_table(
        'barang_pembelian',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pembelian_id', sa.Integer(), nullable=False),
        sa.Column('kode_barang', sa.String(length=50), nullable=False),
        sa.Column('nama_barang', sa.String(length=100), nullable=False),
        sa.Column('kategori', sa.String(length=100), nullable=False),
        sa.Column('jumlah', sa.Integer(), nullable=False),
        sa.Column('harga_beli', sa.Float(), nullable=False),
        sa.Column('diskon', sa.Float(), nullable=False),
        sa.Column('pajak', sa.Float(), nullable=False),
        sa.Column('harga_jual', sa.Float(), nullable=False),
        sa.Column('exp_date', sa.Date(), nullable=True),
        sa.Column('hpp', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['kode_barang'], ['produk.kode_produk'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pembelian_id'], ['pembelian.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Perubahan pada tabel `pembelian`
    with op.batch_alter_table('pembelian', schema=None) as batch_op:
        batch_op.drop_column('kode_barang')
        batch_op.drop_column('diskon')
        batch_op.drop_column('nama_barang')
        batch_op.drop_column('hpp')
        batch_op.drop_column('harga_jual')
        batch_op.drop_column('kategori')
        batch_op.drop_column('pajak')
        batch_op.drop_column('exp_date')
        batch_op.drop_column('jumlah')
        batch_op.drop_column('harga_beli')

    # Set nilai default untuk NULL sebelum mengubah kolom menjadi NOT NULL
    op.execute("UPDATE produk SET jumlah_beli = 0 WHERE jumlah_beli IS NULL")
    op.execute("UPDATE produk SET harga_beli = 0 WHERE harga_beli IS NULL")

    # Perubahan pada tabel `produk`
    with op.batch_alter_table('produk', schema=None) as batch_op:
        # Hapus constraint dengan CASCADE
        batch_op.execute('ALTER TABLE produk DROP CONSTRAINT produk_kode_produk_key CASCADE')

        # Buat ulang constraint
        batch_op.create_index(batch_op.f('ix_produk_kode_produk'), ['kode_produk'], unique=True)

        # Ubah kolom menjadi NOT NULL
        batch_op.alter_column('stok_minimal',
                              existing_type=sa.INTEGER(),
                              nullable=False)
        batch_op.alter_column('harga_beli',
                              existing_type=sa.DOUBLE_PRECISION(precision=53),
                              nullable=False)
        batch_op.alter_column('jumlah_beli',
                              existing_type=sa.INTEGER(),
                              nullable=False)

def downgrade():
    # Membalikkan perubahan
    with op.batch_alter_table('produk', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_produk_kode_produk'))
        batch_op.create_unique_constraint('produk_kode_produk_key', ['kode_produk'])

        # Ubah kolom kembali menjadi nullable
        batch_op.alter_column('jumlah_beli',
                              existing_type=sa.INTEGER(),
                              nullable=True)
        batch_op.alter_column('harga_beli',
                              existing_type=sa.DOUBLE_PRECISION(precision=53),
                              nullable=True)
        batch_op.alter_column('stok_minimal',
                              existing_type=sa.INTEGER(),
                              nullable=True)

    with op.batch_alter_table('pembelian', schema=None) as batch_op:
        batch_op.add_column(sa.Column('harga_beli', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column('jumlah', sa.INTEGER(), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column('exp_date', sa.DATE(), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column('pajak', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column('kategori', sa.VARCHAR(length=100), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column('harga_jual', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column('hpp', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column('nama_barang', sa.VARCHAR(length=100), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column('diskon', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column('kode_barang', sa.VARCHAR(length=50), autoincrement=False, nullable=False))

    op.drop_table('barang_pembelian')
