from app import db
from datetime import datetime


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='sales')

    def __repr__(self):
        return f'<User {self.username}>'


class PasswordResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    token = db.Column(db.String(128), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('reset_tokens', lazy=True, cascade='all, delete-orphan'))

    def mark_used(self):
        self.used = True


class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    bank_account = db.Column(db.String(100), nullable=False)
    account_name = db.Column(db.String(100), nullable=False)
    contact_person = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    website = db.Column(db.String(200), nullable=True)

    def __repr__(self):
        return f"<Supplier {self.name}>"


class Satuan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f"<Satuan {self.name}>"


class Kategori(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f"<Kategori {self.name}>"


class Produk(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kode_produk = db.Column(db.String(50), unique=True, nullable=False, index=True)
    sku = db.Column(db.String(50), unique=True, nullable=True)  # SKU
    barcode = db.Column(db.String(100), unique=True, nullable=True)
    nama_produk = db.Column(db.String(100), nullable=False)
    harga = db.Column(db.Float, default=0.0, nullable=False)
    satuan_id = db.Column(db.Integer, db.ForeignKey('satuan.id', ondelete='SET NULL'), nullable=False)
    kategori_id = db.Column(db.Integer, db.ForeignKey('kategori.id', ondelete='SET NULL'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id', ondelete='SET NULL'), nullable=False)
    berat = db.Column(db.Float, nullable=True)
    stok_minimal = db.Column(db.Integer, default=0, nullable=False)
    stok_lama = db.Column(db.Integer, default=0, nullable=False)
    harga_lama = db.Column(db.Float, default=0.0, nullable=False)
    harga_beli = db.Column(db.Float, default=0.0, nullable=False)
    jumlah_beli = db.Column(db.Integer, default=0, nullable=False)
    tanggal_expired = db.Column(db.Date, nullable=True)

    satuan = db.relationship('Satuan', backref=db.backref('produk', lazy=True))
    kategori = db.relationship('Kategori', backref=db.backref('produk', lazy=True))
    supplier = db.relationship('Supplier', backref=db.backref('produk', lazy=True))

    def update_stok_dan_hpp(self, harga_beli_baru: float, jumlah_beli_baru: int):
        """
        Menghitung HPP berdasarkan stok lama dan pembelian baru.
        """
        if jumlah_beli_baru <= 0:
            raise ValueError("Jumlah pembelian baru harus lebih besar dari 0")

        total_stok = self.stok_lama + jumlah_beli_baru
        total_harga = (self.harga_lama * self.stok_lama) + (harga_beli_baru * jumlah_beli_baru)

        # HPP baru dihitung dari total stok dan total harga
        self.harga_lama = total_harga / total_stok if total_stok > 0 else harga_beli_baru
        self.stok_lama = total_stok
        self.harga_beli = harga_beli_baru

    def __repr__(self):
        return f"<Produk {self.nama_produk}>"


class PriceLevel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)

    costs = db.relationship(
        "PriceLevelCost",
        backref=db.backref("level", lazy=True),
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def active_costs(self):
        return self.costs.filter_by(is_active=True)

    def __repr__(self):
        return f"<PriceLevel {self.name}>"



class ProductPriceLevel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('produk.id', ondelete='CASCADE'), nullable=False)
    level_id = db.Column(db.Integer, db.ForeignKey('price_level.id', ondelete='CASCADE'), nullable=False)
    price = db.Column(db.Float, nullable=False)

    produk = db.relationship('Produk', backref=db.backref('level_prices', cascade='all, delete-orphan'))
    level = db.relationship('PriceLevel', backref=db.backref('product_prices', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('product_id', 'level_id', name='uq_product_level_price'),
    )


class PriceLevelCost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    level_id = db.Column(
        db.Integer, db.ForeignKey('price_level.id', ondelete='CASCADE'), nullable=False
    )
    name = db.Column(db.String(120), nullable=False)
    type = db.Column(db.Enum('percent', 'nominal', name='price_level_cost_type'), nullable=False, default='percent')
    value = db.Column(db.Float, nullable=False, default=0.0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def formatted_value(self):
        if self.type == 'percent':
            return f"{self.value:.2f}%"
        return f"Rp {int(self.value):,}".replace(',', '.')

    def __repr__(self):
        return f"<PriceLevelCost {self.name} ({self.type}={self.value})>"


class Pelanggan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pelanggan_id = db.Column(db.String(50), unique=True, nullable=False)
    nama = db.Column(db.String(100), nullable=False)
    kontak = db.Column(db.String(50), nullable=False)
    alamat = db.Column(db.String(200), nullable=False)
    price_level_id = db.Column(db.Integer, db.ForeignKey('price_level.id'), nullable=True)
    price_level = db.relationship('PriceLevel', backref=db.backref('pelanggan', lazy=True))

    @staticmethod
    def generate_pelanggan_id():
        # Ambil pelanggan terakhir berdasarkan ID
        last_pelanggan = Pelanggan.query.order_by(Pelanggan.id.desc()).first()
        if not last_pelanggan:
            return "CUST001"
        # Ambil angka dari pelanggan_id terakhir dan tambahkan 1
        last_id_number = int(last_pelanggan.pelanggan_id[4:])
        new_id_number = last_id_number + 1
        return f"CUST{new_id_number:03d}"

    def __repr__(self):
        return f"<Pelanggan {self.nama}>"


class Pembelian(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tanggal_faktur = db.Column(db.Date, nullable=False)
    no_faktur = db.Column(db.String(50), unique=True, nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    jenis_pembayaran = db.Column(db.String(20), nullable=False, default='Tunai')
    supplier = db.relationship('Supplier', backref=db.backref('pembelian', lazy=True))
    barang = db.relationship('BarangPembelian', backref='pembelian', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Pembelian {self.no_faktur}>"


class BarangPembelian(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pembelian_id = db.Column(db.Integer, db.ForeignKey('pembelian.id', ondelete='CASCADE'), nullable=False)
    kode_barang = db.Column(db.String(50), db.ForeignKey('produk.kode_produk'), nullable=False)  # Hubungkan ke Produk
    nama_barang = db.Column(db.String(100), nullable=False)
    kategori = db.Column(db.String(100), nullable=False)
    jumlah = db.Column(db.Integer, nullable=False)
    harga_beli = db.Column(db.Float, nullable=False)
    diskon = db.Column(db.Float, nullable=False)
    pajak = db.Column(db.Float, nullable=False)
    harga_jual = db.Column(db.Float, nullable=False)
    exp_date = db.Column(db.Date, nullable=True)
    hpp = db.Column(db.Float, nullable=False)

    produk = db.relationship('Produk', backref=db.backref('barang_pembelian', lazy=True))

    def __repr__(self):
        return f"<BarangPembelian {self.kode_barang}>"


class Penjualan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    no_faktur = db.Column(
        db.String(50),
        unique=True,
        nullable=False,
        default=lambda: f"F{int(datetime.utcnow().timestamp())}",
    )
    tanggal_penjualan = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    sales_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    pelanggan_id = db.Column(db.Integer, db.ForeignKey("pelanggan.id"), nullable=False)
    price_level_id = db.Column(
        db.Integer, db.ForeignKey("price_level.id"), nullable=True
    )
    total_harga = db.Column(db.Float, nullable=False)
    marketplace_cost_total = db.Column(db.Float, nullable=False, default=0.0)
    marketplace_cost_details = db.Column(db.Text, nullable=True)

    sales = db.relationship("User", backref="penjualan")
    pelanggan = db.relationship("Pelanggan", backref="penjualan")
    price_level = db.relationship("PriceLevel", backref="penjualan")

    @property
    def net_revenue(self):
        base = float(self.total_harga or 0.0)
        cost = float(self.marketplace_cost_total or 0.0)
        return max(base - cost, 0.0)


class DetailPenjualan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    penjualan_id = db.Column(db.Integer, db.ForeignKey('penjualan.id'), nullable=False)
    produk_id = db.Column(db.Integer, db.ForeignKey('produk.id'), nullable=False)
    jumlah = db.Column(db.Integer, nullable=False)
    harga_satuan = db.Column(db.Float, nullable=False)
    diskon = db.Column(db.Float, nullable=False, default=0.0)
    pajak = db.Column(db.Float, nullable=False, default=0.0)
    harga_total = db.Column(db.Float, nullable=False)

    penjualan = db.relationship('Penjualan', backref='detail_penjualan')
    produk = db.relationship('Produk', backref='detail_penjualan')


class PriceChange(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('produk.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    price_level_id = db.Column(db.Integer, db.ForeignKey('price_level.id', ondelete='SET NULL'), nullable=True)
    old_price = db.Column(db.Float, nullable=False, default=0.0)
    new_price = db.Column(db.Float, nullable=False, default=0.0)
    margin_before = db.Column(db.Float, nullable=False, default=0.0)
    margin_after = db.Column(db.Float, nullable=False, default=0.0)
    reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    product = db.relationship('Produk', backref=db.backref('price_changes', lazy=True))
    user = db.relationship('User', backref=db.backref('price_changes', lazy=True))
    price_level = db.relationship('PriceLevel', backref=db.backref('price_changes', lazy=True))


class StockOpnameSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(50), unique=True, nullable=False)
    location = db.Column(db.String(100), nullable=True)
    note = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='draft')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    finalized_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('stock_opname_sessions', lazy=True))


class StockOpnameItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('stock_opname_session.id', ondelete='CASCADE'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('produk.id', ondelete='CASCADE'), nullable=False)
    system_qty = db.Column(db.Integer, nullable=False, default=0)
    counted_qty = db.Column(db.Integer, nullable=False, default=0)
    difference_qty = db.Column(db.Integer, nullable=False, default=0)
    note = db.Column(db.String(255), nullable=True)

    session = db.relationship('StockOpnameSession', backref=db.backref('items', lazy=True, cascade='all, delete-orphan'))
    product = db.relationship('Produk')


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # asset, liability, equity, income, expense
    parent_id = db.Column(db.Integer, db.ForeignKey('account.id', ondelete='SET NULL'), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    parent = db.relationship('Account', remote_side=[id], backref=db.backref('children', lazy=True))

    def __repr__(self):
        return f"<Account {self.code} - {self.name}>"


class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(50), unique=True, nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    memo = db.Column(db.String(255), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('journal_entries', lazy=True))


class JournalLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('journal_entry.id', ondelete='CASCADE'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id', ondelete='CASCADE'), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    debit = db.Column(db.Float, nullable=False, default=0.0)
    credit = db.Column(db.Float, nullable=False, default=0.0)

    entry = db.relationship('JournalEntry', backref=db.backref('lines', lazy=True, cascade='all, delete-orphan'))
    account = db.relationship('Account', backref=db.backref('journal_lines', lazy=True))
