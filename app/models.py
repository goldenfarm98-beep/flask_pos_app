from app import db
from datetime import datetime


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    def __repr__(self):
        return f'<User {self.username}>'
    
class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    bank_account = db.Column(db.String(100), nullable=False)
    account_name = db.Column(db.String(100), nullable=False)
    contact_person = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
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
    
class Pelanggan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pelanggan_id = db.Column(db.String(50), unique=True, nullable=False)
    nama = db.Column(db.String(100), nullable=False)
    kontak = db.Column(db.String(50), nullable=False)
    alamat = db.Column(db.String(200), nullable=False)

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
    no_faktur = db.Column(db.String(50), unique=True, nullable=False, default=lambda: f"F{int(datetime.utcnow().timestamp())}")
    tanggal_penjualan = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    sales_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    pelanggan_id = db.Column(db.Integer, db.ForeignKey('pelanggan.id'), nullable=False)
    total_harga = db.Column(db.Float, nullable=False)

    sales = db.relationship('User', backref='penjualan')
    pelanggan = db.relationship('Pelanggan', backref='penjualan')

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




