from flask import Blueprint, render_template, request, redirect, flash, url_for, session, jsonify
from app.models import User, db, Supplier, Satuan, Kategori, Produk, Pelanggan, Pembelian, BarangPembelian, Penjualan, DetailPenjualan
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
from flask import make_response
from io import BytesIO
from sqlalchemy import or_
import logging
from datetime import datetime
from app import csrf
from app.forms import SalesForm

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    return render_template('index.html')  # Pastikan file `index.html` ada di direktori template


@bp.route('/about')
def about():
    return render_template('about.html')

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        # Validasi password
        if password != confirm_password:
            flash('Passwords do not match!', 'danger')
            return render_template('register.html')

        # Periksa apakah email sudah ada
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email is already registered. Please use a different email.', 'danger')
            return render_template('register.html')

        # Hash password dan simpan ke database
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256', salt_length=8)
        new_user = User(username=username, email=email, password=hashed_password)

        db.session.add(new_user)
        db.session.commit()

        flash('Registration successful! Please log in.', 'success')
        return redirect('/login')

    return render_template('register.html')

@bp.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Please log in to access the dashboard.', 'danger')
        return redirect('/login')

    return render_template('dashboard.html', username=session.get('username'))

@bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect('/login')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        # Cari pengguna di database
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('Login successful!', 'success')
            return redirect('/dashboard')
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('login.html')

@bp.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        flash('Please log in to access the profile page.', 'danger')
        return redirect('/login')

    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        # Update username and email
        user.username = username
        user.email = email

        # Update password if provided
        if password:
            hashed_password = generate_password_hash(password, method='pbkdf2:sha256', salt_length=8)
            user.password = hashed_password

        # Commit changes to the database
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect('/profile')

    return render_template('profile.html', username=user.username, email=user.email)

@bp.route('/supplier', methods=['GET', 'POST'])
def supplier():
    if request.method == 'POST':
        # Ambil data dari formulir
        name = request.form['name']
        address = request.form['address']
        phone = request.form['phone']
        bank_account = request.form['bank_account']
        account_name = request.form['account_name']
        contact_person = request.form['contact_person']
        email = request.form['email']
        website = request.form['website']

        # Simpan ke database
        new_supplier = Supplier(
            name=name,
            address=address,
            phone=phone,
            bank_account=bank_account,
            account_name=account_name,
            contact_person=contact_person,
            email=email,
            website=website
        )

        db.session.add(new_supplier)
        db.session.commit()
        flash('Supplier added successfully!', 'success')
        return redirect('/supplier')

    suppliers = Supplier.query.all()
    return render_template('supplier.html', suppliers=suppliers)

@bp.route('/supplier/edit/<int:supplier_id>', methods=['GET', 'POST'])
def edit_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)

    if request.method == 'POST':
        # Ambil data dari formulir
        supplier.name = request.form['name']
        supplier.address = request.form['address']
        supplier.phone = request.form['phone']
        supplier.bank_account = request.form['bank_account']
        supplier.account_name = request.form['account_name']
        supplier.contact_person = request.form['contact_person']
        supplier.email = request.form['email']
        supplier.website = request.form['website']

        # Simpan perubahan ke database
        db.session.commit()
        flash('Supplier updated successfully!', 'success')
        return redirect('/supplier')

    # Kirim data supplier ke template untuk diisi di formulir
    return render_template('supplier.html', edit_supplier=supplier, suppliers=Supplier.query.all())

@bp.route('/supplier/delete/<int:supplier_id>', methods=['POST'])
def delete_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    db.session.delete(supplier)
    db.session.commit()
    flash('Supplier deleted successfully!', 'success')
    return redirect('/supplier')

@bp.route('/supplier/<int:supplier_id>', methods=['GET'])
def supplier_detail(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    return render_template('supplier_detail.html', supplier=supplier)

@bp.route('/supplier/export', methods=['GET'])
def export_suppliers():
    suppliers = Supplier.query.all()

    # Data untuk Excel
    data = [
        {
            "Nama Supplier": supplier.name,
            "Alamat": supplier.address,
            "No Telp": supplier.phone,
            "No Rekening Bank": supplier.bank_account,
            "Nama Rekening": supplier.account_name,
            "Kontak Person": supplier.contact_person,
            "Email": supplier.email,
            "Website": supplier.website,
        }
        for supplier in suppliers
    ]

    # Buat DataFrame pandas
    df = pd.DataFrame(data)

    # Simpan ke file Excel di memori
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)

    # Buat respons Flask
    response = make_response(output.read())
    response.headers["Content-Disposition"] = "attachment; filename=suppliers.xlsx"
    response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return response

@bp.route('/supplier/import', methods=['POST'])
def import_suppliers():
    if 'file' not in request.files:
        flash('No file uploaded!', 'danger')
        return redirect('/supplier')

    file = request.files['file']

    if file.filename == '':
        flash('No selected file!', 'danger')
        return redirect('/supplier')

    # Baca file Excel menggunakan pandas
    try:
        df = pd.read_excel(file)
    except Exception as e:
        flash(f'Error reading file: {e}', 'danger')
        return redirect('/supplier')

    # Validasi kolom yang diperlukan
    required_columns = ['Nama Supplier', 'Alamat', 'No Telp', 'No Rekening Bank', 'Nama Rekening', 'Kontak Person', 'Email', 'Website']
    if not all(column in df.columns for column in required_columns):
        flash('Invalid file format! Missing required columns.', 'danger')
        return redirect('/supplier')

    # Simpan data ke database
    for _, row in df.iterrows():
        # Periksa apakah email sudah ada
        existing_supplier = Supplier.query.filter_by(email=row['Email']).first()
        if existing_supplier:
            flash(f"Supplier with email {row['Email']} already exists. Skipping...", 'warning')
            continue

        # Jika tidak ada, tambahkan data baru
        supplier = Supplier(
            name=row['Nama Supplier'],
            address=row['Alamat'],
            phone=row['No Telp'],
            bank_account=row['No Rekening Bank'],
            account_name=row['Nama Rekening'],
            contact_person=row['Kontak Person'],
            email=row['Email'],
            website=row['Website']
        )
        db.session.add(supplier)

    db.session.commit()
    flash('Suppliers imported successfully!', 'success')
    return redirect('/supplier')

# Route to fetch supplier data
@bp.route('/api/suppliers', methods=['GET'])
def get_suppliers():
    try:
        suppliers = Supplier.query.all()
        suppliers_data = [
            {
                "id": supplier.id,
                "name": supplier.name
            } for supplier in suppliers
        ]
        return jsonify(suppliers_data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/satuan', methods=['GET', 'POST'])
def satuan():
    if request.method == 'POST':
        # Ambil data dari formulir
        name = request.form['satuan']

        # Simpan ke database
        new_satuan = Satuan(name=name)
        db.session.add(new_satuan)
        db.session.commit()
        flash('Satuan added successfully!', 'success')
        return redirect('/satuan')

    # Ambil semua data satuan untuk ditampilkan
    satuans = Satuan.query.all()
    return render_template('data_satuan.html', satuans=satuans)

@bp.route('/satuan/edit/<int:satuan_id>', methods=['GET', 'POST'])
def edit_satuan(satuan_id):
    satuan = Satuan.query.get_or_404(satuan_id)

    if request.method == 'POST':
        # Ambil data dari formulir dan perbarui database
        satuan.name = request.form['satuan']
        db.session.commit()
        flash('Satuan updated successfully!', 'success')
        return redirect('/satuan')

    # Kirim data satuan ke template untuk diisi di formulir
    satuans = Satuan.query.all()
    return render_template('data_satuan.html', edit_satuan=satuan, satuans=satuans)

@bp.route('/satuan/delete/<int:satuan_id>', methods=['POST'])
def delete_satuan(satuan_id):
    satuan = Satuan.query.get_or_404(satuan_id)
    db.session.delete(satuan)
    db.session.commit()
    flash('Satuan deleted successfully!', 'success')
    return redirect('/satuan')

@bp.route('/kategori', methods=['GET', 'POST'])
def kategori():
    if request.method == 'POST':
        # Ambil data dari formulir
        name = request.form['kategori']

        # Simpan ke database
        new_kategori = Kategori(name=name)
        db.session.add(new_kategori)
        db.session.commit()
        flash('Kategori added successfully!', 'success')
        return redirect('/kategori')

    # Ambil semua data kategori untuk ditampilkan
    kategoris = Kategori.query.all()
    return render_template('data_kategori.html', kategoris=kategoris)

@bp.route('/kategori/edit/<int:kategori_id>', methods=['GET', 'POST'])
def edit_kategori(kategori_id):
    kategori = Kategori.query.get_or_404(kategori_id)

    if request.method == 'POST':
        # Ambil data dari formulir dan perbarui di database
        kategori.name = request.form['kategori']
        db.session.commit()
        flash('Kategori updated successfully!', 'success')
        return redirect('/kategori')

    # Kirim data kategori yang akan diedit ke template
    kategoris = Kategori.query.all()
    return render_template('data_kategori.html', edit_kategori=kategori, kategoris=kategoris)

@bp.route('/kategori/delete/<int:kategori_id>', methods=['POST'])
def delete_kategori(kategori_id):
    kategori = Kategori.query.get_or_404(kategori_id)
    db.session.delete(kategori)
    db.session.commit()
    flash('Kategori deleted successfully!', 'success')
    return redirect('/kategori')

@bp.route('/produk', methods=['GET', 'POST'])
def produk():
    satuans = Satuan.query.all()
    kategoris = Kategori.query.all()
    suppliers = Supplier.query.all()

    # Ambil parameter pencarian dan filter
    search_query = request.args.get('search', '').strip()
    kategori_filter = request.args.get('kategori', '').strip()
    supplier_filter = request.args.get('supplier', '').strip()

    # Jika pengguna mengklik tombol edit
    produk_id = request.args.get('edit')
    produk_to_edit = Produk.query.get(produk_id) if produk_id else None

    if request.method == 'POST':
        if produk_to_edit:
            # Update data produk
            produk_to_edit.kode_produk = request.form['kode_produk']
            produk_to_edit.sku = request.form['sku']  # Tambahkan SKU
            produk_to_edit.barcode = request.form['barcode']
            produk_to_edit.nama_produk = request.form['nama_produk']
            produk_to_edit.satuan_id = request.form['satuan']
            produk_to_edit.kategori_id = request.form['kategori']
            produk_to_edit.supplier_id = request.form['supplier']
            produk_to_edit.berat = float(request.form['berat']) if request.form['berat'] else None
            produk_to_edit.stok_minimal = int(request.form['stok_minimal']) if request.form['stok_minimal'] else None
            produk_to_edit.tanggal_expired = request.form['tanggal_expired'] if request.form['tanggal_expired'] else None
            db.session.commit()
            flash('Produk updated successfully!', 'success')
        else:
            # Tambah data produk baru
            kode_produk = request.form['kode_produk']
            sku = request.form['sku']  # Tambahkan SKU
            barcode = request.form['barcode']
            nama_produk = request.form['nama_produk']
            satuan_id = request.form['satuan']
            kategori_id = request.form['kategori']
            supplier_id = request.form['supplier']
            berat = float(request.form['berat']) if request.form['berat'] else None
            stok_minimal = int(request.form['stok_minimal']) if request.form['stok_minimal'] else None
            tanggal_expired = request.form['tanggal_expired'] if request.form['tanggal_expired'] else None

            new_produk = Produk(
                kode_produk=kode_produk,
                sku=sku,  # Tambahkan SKU
                barcode=barcode,
                nama_produk=nama_produk,
                satuan_id=satuan_id,
                kategori_id=kategori_id,
                supplier_id=supplier_id,
                berat=berat,
                stok_minimal=stok_minimal,
                tanggal_expired=tanggal_expired
            )
            db.session.add(new_produk)
            db.session.commit()
            flash('Produk added successfully!', 'success')

        return redirect('/produk')

    # Logika pencarian dan filter
    query = Produk.query
    if search_query:
        query = query.filter(Produk.nama_produk.ilike(f"%{search_query}%"))
    if kategori_filter:
        query = query.filter(Produk.kategori_id == kategori_filter)
    if supplier_filter:
        query = query.filter(Produk.supplier_id == supplier_filter)

    # Query data produk untuk tabel
    produks = query.all()

    # Statistik Produk
    stok_tinggi = Produk.query.order_by(Produk.stok_minimal.desc()).limit(5).all()
    stok_rendah = Produk.query.order_by(Produk.stok_minimal).limit(5).all()
    produk_aktif = Produk.query.count()
    stok_kosong = Produk.query.filter(Produk.stok_minimal == 0).count()

    statistik = {
        "stok_tinggi": len(stok_tinggi),
        "stok_rendah": len(stok_rendah),
        "produk_aktif": produk_aktif,
        "stok_kosong": stok_kosong
    }

    return render_template(
        'data_produk.html',
        produks=produks,
        satuans=satuans,
        kategoris=kategoris,
        suppliers=suppliers,
        statistik=statistik,
        edit_produk=produk_to_edit
    )


    # Logika pencarian dan filter
    query = Produk.query
    if search_query:
        query = query.filter(Produk.nama_produk.ilike(f"%{search_query}%"))
    if kategori_filter:
        query = query.filter(Produk.kategori_id == kategori_filter)
    if supplier_filter:
        query = query.filter(Produk.supplier_id == supplier_filter)

    # Ambil data produk setelah pencarian dan filter
    produks = query.all()

    return render_template(
        'data_produk.html',
        produks=produks,
        satuans=satuans,
        kategoris=kategoris,
        suppliers=suppliers,
        edit_produk=produk_to_edit
    )


@bp.route('/produk/edit/<int:produk_id>', methods=['GET', 'POST'])
def edit_produk(produk_id):
    produk = Produk.query.get_or_404(produk_id)

    if request.method == 'POST':
        produk.kode_produk = request.form['kode_produk']
        produk.barcode = request.form['barcode']
        produk.nama_produk = request.form['nama_produk']
        produk.satuan_id = request.form['satuan']
        produk.kategori_id = request.form['kategori']
        produk.supplier_id = request.form['supplier']
        produk.berat = float(request.form['berat']) if request.form['berat'] else None
        produk.stok_minimal = int(request.form['stok_minimal']) if request.form['stok_minimal'] else None
        produk.tanggal_expired = request.form['tanggal_expired'] if request.form['tanggal_expired'] else None

        db.session.commit()
        flash('Produk updated successfully!', 'success')
        return redirect('/produk')

    satuans = Satuan.query.all()
    kategoris = Kategori.query.all()
    suppliers = Supplier.query.all()
    return render_template('edit_produk.html', produk=produk, satuans=satuans, kategoris=kategoris, suppliers=suppliers)

@bp.route('/produk/delete/<int:produk_id>', methods=['POST'])
def delete_produk(produk_id):
    produk = Produk.query.get_or_404(produk_id)
    db.session.delete(produk)
    db.session.commit()
    flash('Produk deleted successfully!', 'success')
    return redirect('/produk')

@bp.route('/produk/detail/<int:produk_id>', methods=['GET'])
def detail_produk(produk_id):
    produk = Produk.query.get_or_404(produk_id)
    return render_template('detail_produk.html', produk=produk)

@bp.route('/produk/export', methods=['GET'])
def export_produk():
    produks = Produk.query.all()

    # Data untuk Excel
    data = [
        {
            "Kode Produk": produk.kode_produk,
            "SKU": produk.sku,
            "Nama Produk": produk.nama_produk,
            "Kategori": produk.kategori.name,
            "Supplier": produk.supplier.name,
            "Berat": produk.berat,
            "Stok Minimal": produk.stok_minimal,
            "Tanggal Expired": produk.tanggal_expired,
        }
        for produk in produks
    ]

    # Buat DataFrame pandas
    df = pd.DataFrame(data)

    # Simpan ke file Excel di memori
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)

    # Buat respons Flask
    response = make_response(output.read())
    response.headers["Content-Disposition"] = "attachment; filename=produk.xlsx"
    response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return response

@bp.route('/produk/import', methods=['POST'])
def import_produk():
    if 'file' not in request.files:
        flash('Tidak ada file yang diunggah!', 'danger')
        return redirect('/produk')

    file = request.files['file']

    if file.filename == '':
        flash('File tidak dipilih!', 'danger')
        return redirect('/produk')

    # Baca file Excel menggunakan pandas
    try:
        df = pd.read_excel(file)
    except Exception as e:
        flash(f'Gagal membaca file: {e}', 'danger')
        return redirect('/produk')

    # Validasi kolom yang diperlukan
    required_columns = ['Kode Produk', 'SKU', 'Nama Produk', 'Satuan ID', 'Kategori ID', 'Supplier ID', 'Berat', 'Stok Minimal', 'Tanggal Expired']
    if not all(column in df.columns for column in required_columns):
        flash('Format file tidak valid! Pastikan semua kolom yang diperlukan ada.', 'danger')
        return redirect('/produk')

    # Simpan data ke database
    for _, row in df.iterrows():
        # Validasi data
        kode_produk = row['Kode Produk']
        existing_produk = Produk.query.filter_by(kode_produk=kode_produk).first()
        if existing_produk:
            flash(f"Produk dengan kode '{kode_produk}' sudah ada. Data dilewati.", 'warning')
            continue

        # Pastikan foreign key valid
        satuan = Satuan.query.get(row['Satuan ID'])
        kategori = Kategori.query.get(row['Kategori ID'])
        supplier = Supplier.query.get(row['Supplier ID'])

        if not satuan or not kategori or not supplier:
            flash(f"Produk {row['Nama Produk']} dilewati karena Satuan, Kategori, atau Supplier tidak valid.", 'warning')
            continue

        # Buat produk baru
        produk = Produk(
            kode_produk=row['Kode Produk'],
            sku=row['SKU'],
            nama_produk=row['Nama Produk'],
            satuan_id=row['Satuan ID'],
            kategori_id=row['Kategori ID'],
            supplier_id=row['Supplier ID'],
            berat=row['Berat'] if not pd.isna(row['Berat']) else 0.0,
            stok_minimal=row['Stok Minimal'] if not pd.isna(row['Stok Minimal']) else 0,
            tanggal_expired=row['Tanggal Expired'] if not pd.isna(row['Tanggal Expired']) else None,
            stok_lama=0,
            harga_lama=0.0,
            harga_beli=None,
            jumlah_beli=None
        )
        db.session.add(produk)

    db.session.commit()
    flash('Data produk berhasil diimport!', 'success')
    return redirect('/produk')


@bp.route('/pelanggan', methods=['GET', 'POST'])
def pelanggan():
    if request.method == 'POST':
        # Gunakan generate_pelanggan_id jika pelanggan_id tidak diisi
        pelanggan_id = request.form.get('pelanggan_id') or Pelanggan.generate_pelanggan_id()
        nama = request.form['nama']
        kontak = request.form['kontak']
        alamat = request.form['alamat']

        # Tambahkan pelanggan baru
        new_pelanggan = Pelanggan(
            pelanggan_id=pelanggan_id,
            nama=nama,
            kontak=kontak,
            alamat=alamat
        )
        db.session.add(new_pelanggan)
        db.session.commit()
        flash('Pelanggan added successfully!', 'success')
        return redirect('/pelanggan')

    pelanggans = Pelanggan.query.all()
    return render_template('data_pelanggan.html', pelanggans=pelanggans)


@bp.route('/pelanggan/edit/<int:pelanggan_id>', methods=['GET', 'POST'])
def edit_pelanggan(pelanggan_id):
    pelanggan = Pelanggan.query.get_or_404(pelanggan_id)

    if request.method == 'POST':
        pelanggan.nama = request.form['nama']
        pelanggan.kontak = request.form['kontak']
        pelanggan.alamat = request.form['alamat']
        db.session.commit()
        flash(f'Pelanggan {pelanggan.nama} updated successfully!', 'success')
        return redirect('/pelanggan')

    pelanggans = Pelanggan.query.all()
    return render_template('data_pelanggan.html', edit_pelanggan=pelanggan, pelanggans=pelanggans)


@bp.route('/pelanggan/delete/<int:pelanggan_id>', methods=['POST'])
def delete_pelanggan(pelanggan_id):
    pelanggan = Pelanggan.query.get_or_404(pelanggan_id)
    pelanggan_name = pelanggan.nama  # Simpan nama pelanggan untuk pesan flash
    db.session.delete(pelanggan)
    db.session.commit()
    flash(f'Pelanggan {pelanggan_name} deleted successfully!', 'success')
    return redirect('/pelanggan')


@bp.route('/api/get_product', methods=['GET'])
def get_product():
    product_code = request.args.get('product_code')
    product = Produk.query.filter_by(kode_produk=product_code).first()

    if product:
        return {
            'success': True,
            'product_name': product.nama_produk,
            'category': product.kategori.name,
            'satuan': product.satuan.name
        }
    else:
        return {'success': False, 'message': 'Produk tidak ditemukan.'}, 404


@bp.route('/api/products', methods=['GET'])
def get_products():
    search_query = request.args.get('q', '').strip()
    products = Produk.query

    # Filter berdasarkan nama produk dan kode produk jika ada query pencarian
    if search_query:
        products = products.filter(
            or_(
                Produk.nama_produk.ilike(f"%{search_query}%"),
                Produk.kode_produk.ilike(f"%{search_query}%")
            )
        )

    products = products.limit(100).all()  # Batasi jumlah hasil untuk performa

    # Format data untuk ditampilkan
    product_list = [{
        'id': product.id,
        'kode_produk': product.kode_produk,
        'nama_produk': product.nama_produk,
        'kategori': product.kategori.name if product.kategori else 'Tidak dikategorikan'
    } for product in products]

    return {'products': product_list}


@bp.route('/pembelian', methods=['GET', 'POST'])
def pembelian():
    try:
        # Jika metode GET, tampilkan halaman pembelian
        if request.method == 'GET':
            return render_template('pembelian.html')

        # Jika metode POST, proses data pembelian
        if request.method == 'POST':
            # Validasi Content-Type
            if not request.is_json:
                return jsonify({"success": False, "message": "Content-Type harus 'application/json'"}), 415

            data = request.json
            tanggal_faktur = data.get('tanggal_faktur')
            no_faktur = data.get('no_faktur')
            supplier_id = data.get('supplier')
            items = data.get('items', [])

            # Validasi data utama
            if not (tanggal_faktur and no_faktur and supplier_id):
                return jsonify({"success": False, "message": "Data utama tidak lengkap."}), 400

            # Validasi keberadaan barang
            if not items:
                return jsonify({"success": False, "message": "Tidak ada data barang yang dikirim."}), 400

            # Cek apakah nomor faktur sudah ada
            if Pembelian.query.filter_by(no_faktur=no_faktur).first():
                return jsonify({"success": False, "message": f"Nomor faktur {no_faktur} sudah ada."}), 400

            # Simpan data pembelian
            pembelian = Pembelian(
                tanggal_faktur=datetime.strptime(tanggal_faktur, '%Y-%m-%d'),
                no_faktur=no_faktur,
                supplier_id=supplier_id
            )
            db.session.add(pembelian)
            db.session.flush()  # Memastikan ID faktur tersedia untuk relasi

            # Simpan setiap barang
            for item in items:
                kode_barang = item.get('kode_barang')
                nama_barang = item.get('nama_barang')
                kategori = item.get('kategori')
                jumlah = item.get('jumlah', 0)
                harga_beli = item.get('harga_beli', 0.0)
                diskon = item.get('diskon', 0.0)
                pajak = item.get('pajak', 0.0)
                harga_jual = item.get('harga_jual', 0.0)
                exp_date = item.get('exp_date')

                # Hitung diskon, pajak, dan harga final
                diskon_amount = (diskon / 100) * harga_beli
                pajak_amount = (pajak / 100) * (harga_beli - diskon_amount)
                harga_final = harga_beli - diskon_amount + pajak_amount

                # Ambil produk dari database
                produk = Produk.query.filter_by(kode_produk=kode_barang).first()

                if produk:
                    # Update stok dan HPP
                    produk.update_stok_dan_hpp(harga_final, jumlah)
                else:
                    return jsonify({"success": False, "message": f"Produk dengan kode {kode_barang} tidak ditemukan."}), 404

                barang_pembelian = BarangPembelian(
                    pembelian_id=pembelian.id,
                    kode_barang=kode_barang,
                    nama_barang=nama_barang,
                    kategori=kategori,
                    jumlah=jumlah,
                    harga_beli=harga_beli,
                    diskon=diskon,
                    pajak=pajak,
                    harga_jual=harga_jual,
                    exp_date=datetime.strptime(exp_date, '%Y-%m-%d') if exp_date else None,
                    hpp=harga_final * jumlah
                )
                db.session.add(barang_pembelian)

            db.session.commit()
            return jsonify({"success": True, "message": "Pembelian berhasil disimpan!"}), 200

    except Exception as e:
        db.session.rollback()
        print("Error:", str(e))
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500


@bp.route('/check_no_faktur', methods=['POST'])
def check_no_faktur():
    try:
        # Pastikan request dalam format JSON
        if not request.is_json:
            return jsonify({"success": False, "message": "Content-Type harus 'application/json'"}), 415

        # Ambil data dari request
        data = request.json
        no_faktur = data.get('no_faktur')

        if not no_faktur:
            return jsonify({"success": False, "message": "Nomor faktur tidak diberikan."}), 400

        # Cek apakah nomor faktur sudah ada
        existing_pembelian = Pembelian.query.filter_by(no_faktur=no_faktur).first()
        if existing_pembelian:
            return jsonify({"success": False, "exists": True, "message": f"Nomor faktur {no_faktur} sudah ada."}), 200

        # Jika tidak ada
        return jsonify({"success": True, "exists": False, "message": "Nomor faktur tersedia."}), 200

    except Exception as e:
        print("Error:", str(e))
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@bp.route('/penjualan', methods=['GET', 'POST'])
def penjualan():
    form = SalesForm()
    form.pelanggan_id.choices = [(p.id, p.nama) for p in Pelanggan.query.all()]  # Dropdown pelanggan

    # Ambil data produk dari database
    produk_list = Produk.query.all()

    if form.validate_on_submit():
        try:
            sales_id = session.get('user_id')
            pelanggan_id = form.pelanggan_id.data

            # Buat data penjualan
            penjualan = Penjualan(
                sales_id=sales_id,
                pelanggan_id=pelanggan_id,
                total_harga=0.0
            )
            db.session.add(penjualan)
            db.session.flush()  # Untuk mendapatkan ID penjualan

            # Proses detail barang
            produk_id_list = request.form.getlist('produk_id[]')
            jumlah_list = request.form.getlist('jumlah[]')
            harga_list = request.form.getlist('harga[]')

            for produk_id, jumlah, harga in zip(produk_id_list, jumlah_list, harga_list):
                detail = DetailPenjualan(
                    penjualan_id=penjualan.id,
                    produk_id=int(produk_id),
                    jumlah=int(jumlah),
                    harga_satuan=float(harga),
                    harga_total=int(jumlah) * float(harga)
                )
                penjualan.total_harga += detail.harga_total
                db.session.add(detail)

            db.session.commit()
            flash('Penjualan berhasil disimpan!', 'success')
            return redirect('/penjualan')

        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')

    return render_template('penjualan.html', form=form, produk_list=produk_list)

@bp.route('/api/get_product1', methods=['GET'])
def get_product1():
    product_id = request.args.get('product_id')
    product = Produk.query.get(product_id)

    if product:
        return jsonify({
            'success': True,
            'id': product.id,
            'nama_produk': product.nama_produk,
            'kode_produk': product.kode_produk,
            'harga': product.harga
        })
    return jsonify({'success': False, 'message': 'Produk tidak ditemukan.'}), 404







