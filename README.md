![CI](https://github.com/goldenfarm98-beep/flask_pos_app/actions/workflows/python-ci.yml/badge.svg)

# Flask POS App

Aplikasi POS (Point of Sale) berbasis Flask untuk kebutuhan kasir, penjualan,
pembelian, stok, serta laporan operasional dan akuntansi. Cocok untuk toko
ritel/wholesale yang butuh pencatatan transaksi, invoice, dan monitoring
persediaan secara terpusat.

## Fitur utama
- Penjualan: invoice, struk, surat jalan, draft invoice
- Pembelian: PO, penerimaan, pembayaran, harga beli
- Stok: stok opname, mutasi, level harga
- Pelanggan, supplier, ekspedisi, dan metode pembayaran
- Laporan: penjualan, pembelian, stok, laba rugi, piutang
- Shift kasir dan ringkasan aktivitas
- Pengaturan perusahaan, struk, dan database

## Teknologi
- Python + Flask
- SQLAlchemy + Flask-Migrate (Alembic)
- MySQL/MariaDB atau SQLite (fallback)
- Jinja2 templates + AdminKit
- PyTest untuk testing

## Menjalankan secara lokal (Linux/macOS)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app app.py run --host 0.0.0.0 --port 5000
```

## Menjalankan secara lokal (Windows PowerShell)
```powershell
cd "E:\Aplikasi Python\flask_pos_app"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
flask --app app.py run --host 0.0.0.0 --port 5000
```

## Konfigurasi environment
Salin `.env.example` menjadi `.env` lalu sesuaikan. Prioritas koneksi database:
`SQLALCHEMY_DATABASE_URI` -> `DATABASE_URL` -> gabungan `MYSQL_*` -> SQLite.

| Key | Deskripsi |
| --- | --- |
| `SECRET_KEY` | Kunci session/CSRF |
| `SQLALCHEMY_DATABASE_URI` | DSN utama (mis. `mysql+pymysql://user:pass@host:3306/db`) |
| `DATABASE_URL` | Alternatif DSN (mendukung `postgresql://`) |
| `MYSQL_HOST` | Host MySQL |
| `MYSQL_PORT` | Port MySQL (default 3306) |
| `MYSQL_USER` | User MySQL |
| `MYSQL_PASSWORD` | Password MySQL |
| `MYSQL_DATABASE` | Nama database |
| `COMPANY_NAME` | Nama perusahaan di laporan/struk |
| `COMPANY_ADDRESS` | Alamat perusahaan |
| `COMPANY_PHONE` | Telepon perusahaan |
| `RECEIPT_*` | Pengaturan tampilan struk |

Catatan: Jika semua variabel DB kosong, aplikasi akan memakai SQLite di
`instance/app.db`.

## Migrasi database
```bash
flask --app app.py db upgrade
```

Jika ada perubahan model dan perlu membuat migration baru:
```bash
flask --app app.py db migrate -m "deskripsi perubahan"
flask --app app.py db upgrade
```

## Testing
```bash
pytest
```

## Template import
- `stok_opname_import_template.xlsx`
- `stok_opname_import_template.csv`

## Catatan pengembangan
- Banyak halaman UI ada di `app/templates`.
- Logika bisnis berada di `app/services`.
- Model database di `app/models.py`.
