from alembic import op
import sqlalchemy as sa

# --- metadata revision ---
revision = '63debe259d43'
down_revision = 'bb1805b2b273'
branch_labels = None
depends_on = None

# --- helpers ---
def _insp(bind=None):
    return sa.inspect(bind or op.get_bind())

def _table_exists(name, bind=None):
    insp = _insp(bind)
    return name in insp.get_table_names()

def _column_exists(table, column, bind=None):
    insp = _insp(bind)
    try:
        cols = [c['name'] for c in insp.get_columns(table)]
    except Exception:
        return False
    return column in cols

def upgrade():
    bind = op.get_bind()
    insp = _insp(bind)

    # Matikan FK biar aman saat drop/create
    op.execute("SET FOREIGN_KEY_CHECKS=0")

    # --- Pastikan 'produk' ada (minimal) ---
    if not _table_exists('produk', bind):
        op.execute("""
        CREATE TABLE produk (
          kode_produk  VARCHAR(50) NOT NULL,
          jumlah_beli  INT NOT NULL DEFAULT 0,
          PRIMARY KEY (kode_produk)
        ) ENGINE=InnoDB
          DEFAULT CHARSET=utf8mb4
          COLLATE=utf8mb4_unicode_ci;
        """)
    else:
        # Tambahkan kolom jumlah_beli bila belum ada
        if not _column_exists('produk', 'jumlah_beli', bind):
            op.add_column('produk', sa.Column('jumlah_beli', sa.Integer(), nullable=False, server_default='0'))
            # opsional lepas default runtime kalau mau
            op.execute("ALTER TABLE produk ALTER jumlah_beli DROP DEFAULT")

    # --- Buat tabel 'barang_pembelian' bila belum ada ---
    if not _table_exists('barang_pembelian', bind):
        op.create_table(
            'barang_pembelian',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
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
            sa.ForeignKeyConstraint(['kode_barang'], ['produk.kode_produk'], name='fk_bp_produk', ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['pembelian_id'], ['pembelian.id'], name='fk_bp_pembelian', ondelete='CASCADE'),
            mysql_charset='utf8mb4',
            mysql_collate='utf8mb4_unicode_ci'
        )

    # --- Bersihkan kolom yang “dipindah” dari tabel pembelian (cek dulu ada/tidak) ---
    cols_to_drop = [
        'kode_barang','nama_barang','kategori','jumlah',
        'harga_beli','diskon','pajak','harga_jual','exp_date','hpp'
    ]
    for col in cols_to_drop:
        if _column_exists('pembelian', col, bind):
            op.drop_column('pembelian', col)

    op.execute("SET FOREIGN_KEY_CHECKS=1")


def downgrade():
    bind = op.get_bind()

    op.execute("SET FOREIGN_KEY_CHECKS=0")

    # Kembalikan kolom ke 'pembelian' bila belum ada (nullable agar aman)
    add_back = [
        ('kode_barang', sa.String(50)),
        ('nama_barang', sa.String(100)),
        ('kategori', sa.String(100)),
        ('jumlah', sa.Integer()),
        ('harga_beli', sa.Float()),
        ('diskon', sa.Float()),
        ('pajak', sa.Float()),
        ('harga_jual', sa.Float()),
        ('exp_date', sa.Date()),
        ('hpp', sa.Float()),
    ]
    for name, typ in add_back:
        if not _column_exists('pembelian', name, bind):
            op.add_column('pembelian', sa.Column(name, typ, nullable=True))

    # Drop tabel barang_pembelian kalau ada
    if _table_exists('barang_pembelian', bind):
        op.drop_table('barang_pembelian')

    op.execute("SET FOREIGN_KEY_CHECKS=1")
