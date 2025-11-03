# models.py — sinkron dengan skema MySQL yang sudah ada
from app import db
from datetime import datetime, date

# ------------------------------------------------------------
# USER (standalone; tabel ini belum ada di DB kamu saat ini)
# ------------------------------------------------------------
class User(db.Model):
    __tablename__ = "user"
    id       = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email    = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    def __repr__(self):
        return f"<User {self.username}>"

# ------------------------------------------------------------
# MASTER: SUPPLIER  (MATCH dengan tabel MySQL: supplier)
# kolom: id, nama, alamat, telepon
# ------------------------------------------------------------
class Supplier(db.Model):
    __tablename__ = "supplier"
    id      = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nama    = db.Column(db.String(100), nullable=False)
    alamat  = db.Column(db.String(255), nullable=True)
    telepon = db.Column(db.String(50), nullable=True)

    # --- Compatibility alias untuk kode lama yang pakai English field ---
    @property
    def name(self): return self.nama
    @name.setter
    def name(self, v): self.nama = v

    @property
    def address(self): return self.alamat
    @address.setter
    def address(self, v): self.alamat = v

    @property
    def phone(self): return self.telepon
    @phone.setter
    def phone(self, v): self.telepon = v

    # Catatan:
    # Field berikut BELUM ADA di DB: bank_account, account_name, contact_person, email, website
    # Jika ingin dipakai, buatkan migrasi terpisah untuk menambah kolom2 itu.

    def __repr__(self):
        return f"<Supplier {self.id} {self.nama}>"

# ------------------------------------------------------------
# MASTER: SATUAN & KATEGORI (belum ada di DB; untuk migrasi berikutnya)
# ------------------------------------------------------------
class Satuan(db.Model):
    __tablename__ = "satuan"
    id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f"<Satuan {self.name}>"

class Kategori(db.Model):
    __tablename__ = "kategori"
    id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f"<Kategori {self.name}>"

# ------------------------------------------------------------
# MASTER: PRODUK (MATCH dengan tabel MySQL: produk)
# kolom: kode_produk (PK), jumlah_beli, harga
# ------------------------------------------------------------
class Produk(db.Model):
    __tablename__ = "produk"
    # Primary Key memang STRING (kode_produk), bukan integer
    kode_produk = db.Column(db.String(50), primary_key=True)
    jumlah_beli = db.Column(db.Integer, nullable=False, default=0)
    harga       = db.Column(db.Float,   nullable=False, default=0.0)

    # Compatibility alias: beberapa kode lama mungkin akses .id
    @property
    def id(self): return self.kode_produk
    @id.setter
    def id(self, v): self.kode_produk = v

    # Helper aman untuk update stok beli (tanpa kolom stok/hpp lain)
    def tambah_pembelian(self, qty: int):
        if qty is None or qty <= 0:
            raise ValueError("qty harus > 0")
        self.jumlah_beli = (self.jumlah_beli or 0) + int(qty)

    def __repr__(self):
        return f"<Produk {self.kode_produk} harga={self.harga}>"

# ------------------------------------------------------------
# PELANGGAN (belum ada di DB; untuk migrasi berikutnya)
# ------------------------------------------------------------
class Pelanggan(db.Model):
    __tablename__ = "pelanggan"
    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    pelanggan_id = db.Column(db.String(50), unique=True, nullable=False)
    nama         = db.Column(db.String(100), nullable=False)
    kontak       = db.Column(db.String(50), nullable=False)
    alamat       = db.Column(db.String(200), nullable=False)

    @staticmethod
    def generate_pelanggan_id():
        last = Pelanggan.query.order_by(Pelanggan.id.desc()).first()
        if not last:
            return "CUST001"
        last_num = int(last.pelanggan_id[4:])
        return f"CUST{last_num + 1:03d}"

    def __repr__(self):
        return f"<Pelanggan {self.nama}>"

# ------------------------------------------------------------
# PEMBELIAN (MATCH dengan tabel MySQL: pembelian)
# kolom: id, tanggal_faktur, no_faktur (UNIQUE), supplier_id(FK)
# ------------------------------------------------------------
class Pembelian(db.Model):
    __tablename__ = "pembelian"
    id             = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tanggal_faktur = db.Column(db.Date, nullable=False)
    no_faktur      = db.Column(db.String(50), unique=True, nullable=False)
    supplier_id    = db.Column(db.Integer, db.ForeignKey("supplier.id"), nullable=False)

    supplier = db.relationship("Supplier", backref=db.backref("pembelian", lazy=True))
    barang   = db.relationship(
        "BarangPembelian",
        backref="pembelian",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy=True,
    )

    def __repr__(self):
        return f"<Pembelian {self.no_faktur}>"

# ------------------------------------------------------------
# BARANG_PEMBELIAN (MATCH dengan tabel MySQL: barang_pembelian)
# kolom: id, pembelian_id(FK), kode_barang(FK->produk.kode_produk), dst.
# ------------------------------------------------------------
class BarangPembelian(db.Model):
    __tablename__ = "barang_pembelian"
    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    pembelian_id = db.Column(
        db.Integer,
        db.ForeignKey("pembelian.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relasi ke Produk via KODE, bukan integer id
    kode_barang  = db.Column(
        db.String(50),
        db.ForeignKey("produk.kode_produk"),
        nullable=False,
        index=True,
    )

    nama_barang  = db.Column(db.String(100), nullable=False)
    kategori     = db.Column(db.String(100), nullable=False)
    jumlah       = db.Column(db.Integer,     nullable=False)
    harga_beli   = db.Column(db.Float,       nullable=False)
    diskon       = db.Column(db.Float,       nullable=False, default=0.0)
    pajak        = db.Column(db.Float,       nullable=False, default=0.0)
    harga_jual   = db.Column(db.Float,       nullable=False)
    exp_date     = db.Column(db.Date,        nullable=True)
    hpp          = db.Column(db.Float,       nullable=False)

    produk = db.relationship("Produk", backref=db.backref("barang_pembelian", lazy=True))

    def __repr__(self):
        return f"<BarangPembelian {self.kode_barang} x{self.jumlah}>"

# ------------------------------------------------------------
# PENJUALAN & DETAIL_PENJUALAN (belum ada di DB; untuk migrasi berikutnya)
# Catatan: DetailPenjualan refer ke produk.kode_produk (kolom: produk_kode)
# ------------------------------------------------------------
class Penjualan(db.Model):
    __tablename__ = "penjualan"
    id                = db.Column(db.Integer, primary_key=True, autoincrement=True)
    no_faktur         = db.Column(db.String(50), unique=True, nullable=False,
                                  default=lambda: f"F{int(datetime.utcnow().timestamp())}")
    tanggal_penjualan = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    sales_id          = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    pelanggan_id      = db.Column(db.Integer, db.ForeignKey("pelanggan.id"), nullable=False)
    total_harga       = db.Column(db.Float, nullable=False)

    sales     = db.relationship("User", backref="penjualan")
    pelanggan = db.relationship("Pelanggan", backref="penjualan")

    def __repr__(self):
        return f"<Penjualan {self.no_faktur}>"

class DetailPenjualan(db.Model):
    __tablename__ = "detail_penjualan"
    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    penjualan_id  = db.Column(db.Integer, db.ForeignKey("penjualan.id"), nullable=False)
    # Konsisten dengan Produk: relasi via kode
    produk_kode   = db.Column(db.String(50), db.ForeignKey("produk.kode_produk"), nullable=False)

    jumlah        = db.Column(db.Integer, nullable=False)
    harga_satuan  = db.Column(db.Float,   nullable=False)
    diskon        = db.Column(db.Float,   nullable=False, default=0.0)
    pajak         = db.Column(db.Float,   nullable=False, default=0.0)
    harga_total   = db.Column(db.Float,   nullable=False)

    penjualan = db.relationship("Penjualan", backref="detail_penjualan")
    produk    = db.relationship("Produk", backref="detail_penjualan")

    def __repr__(self):
        return f"<DetailPenjualan {self.produk_kode} x{self.jumlah}>"
