![CI](https://github.com/goldenfarm98-beep/flask_pos_app/actions/workflows/python-ci.yml/badge.svg)

---

## Menjalankan secara lokal (Windows PowerShell)
```powershell
cd "E:\Aplikasi Python\flask_pos_app"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:FLASK_APP = "app.py"
flask run --host 0.0.0.0 --port 5000
```

## Konfigurasi Database MySQL
- _Siapkan database dan user_
  ```sql
  CREATE DATABASE flask_pos CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  CREATE USER 'user'@'%' IDENTIFIED BY 'pass';
  GRANT ALL ON flask_pos.* TO 'user'@'%';
  FLUSH PRIVILEGES;
  ```
- _Atur environment sebelum menjalankan aplikasi_
  ```powershell
  $env:MYSQL_HOST = "localhost"
  $env:MYSQL_PORT = "3306"
  $env:MYSQL_USER = "user"
  $env:MYSQL_PASSWORD = "pass"
  $env:MYSQL_DATABASE = "flask_pos"
  # atau langsung pakai DSN penuh
  # $env:DATABASE_URL = "mysql+pymysql://user:pass@localhost:3306/flask_pos"
  ```
- _Inisialisasi skema_
  - Untuk database baru cukup jalankan `flask db upgrade` (menggunakan baseline `migrations/versions/0001_mysql_baseline.py`).
  - Jika database sudah ada dan ingin menandai versi migrasi tanpa menulis ulang skema, jalankan `flask db stamp head` setelah memastikan struktur tabel selaras dengan model Python.
