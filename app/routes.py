from flask import Blueprint, render_template, request, redirect, flash, url_for, session, jsonify
from app.models import User, db, Supplier, Satuan, Kategori, Produk, Pelanggan, Pembelian, BarangPembelian, Penjualan, DetailPenjualan
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
from flask import make_response
from io import BytesIO
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError
import logging
from datetime import datetime
from app import csrf
from app.forms import SalesForm

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    stats = {
        "produk": Produk.query.count(),
        "penjualan": Penjualan.query.count(),
        "pembelian": Pembelian.query.count(),
        "pelanggan": Pelanggan.query.count(),
        "supplier": Supplier.query.count()
    }

    recent_sales = (
        Penjualan.query.order_by(Penjualan.tanggal_penjualan.desc()).limit(5).all()
    )
    recent_purchases = (
        Pembelian.query.order_by(Pembelian.tanggal_faktur.desc()).limit(5).all()
    )

    if session.get('user_id'):
        quick_links = [
            {
                "title": "Mulai Penjualan",
                "subtitle": "Catat transaksi baru",
                "icon": "fa-cash-register",
                "url": url_for('main.penjualan'),
                "tag": "Transaksi"
            },
            {
                "title": "Tambah Produk",
                "subtitle": "Kelola inventori",
                "icon": "fa-box-open",
                "url": url_for('main.produk'),
                "tag": "Inventori"
            },
            {
                "title": "Kelola Supplier",
                "subtitle": "Bangun relasi pemasok",
                "icon": "fa-truck",
                "url": url_for('main.supplier'),
                "tag": "Relasi"
            },
            {
                "title": "Data Pelanggan",
                "subtitle": "Lihat daftar pelanggan",
                "icon": "fa-users",
                "url": url_for('main.pelanggan'),
                "tag": "CRM"
            }
        ]
    else:
        quick_links = [
            {
                "title": "Masuk ke akun",
                "subtitle": "Lihat fitur lengkap aplikasi",
                "icon": "fa-sign-in-alt",
                "url": url_for('main.login'),
                "tag": "Akses"
            },
            {
                "title": "Buat akun baru",
                "subtitle": "Mulai kelola penjualan secara digital",
                "icon": "fa-user-plus",
                "url": url_for('main.register'),
                "tag": "Daftar"
            },
            {
                "title": "Jelajahi fitur",
                "subtitle": "Kenali kemampuan POS lebih dekat",
                "icon": "fa-info-circle",
                "url": url_for('main.about'),
                "tag": "Panduan"
            },
            {
                "title": "Hubungi tim",
                "subtitle": "Siap bantu setup pertama Anda",
                "icon": "fa-headset",
                "url": url_for('main.about'),
                "tag": "Dukungan"
            }
        ]

    return render_template(
        'index.html',
        stats=stats,
        recent_sales=recent_sales,
        recent_purchases=recent_purchases,
        quick_links=quick_links
    )


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

def _build_supplier_page_context(edit_supplier=None, search_query=''):
    base_query = Supplier.query.order_by(Supplier.name.asc())
    if search_query:
        like = f"%{search_query}%"
        base_query = base_query.filter(
            or_(
                Supplier.name.ilike(like),
                Supplier.email.ilike(like),
                Supplier.contact_person.ilike(like),
                Supplier.phone.ilike(like)
            )
        )

    suppliers = base_query.all()
    all_suppliers = Supplier.query.all()

    def has_value(value):
        return bool(value and str(value).strip())

    total_suppliers = len(all_suppliers)
    contact_complete = sum(1 for sup in all_suppliers if has_value(sup.phone))
    email_complete = sum(1 for sup in all_suppliers if has_value(sup.email))
    website_complete = sum(1 for sup in all_suppliers if has_value(sup.website))
    contact_missing = total_suppliers - contact_complete
    email_missing = total_suppliers - email_complete

    purchase_count = Pembelian.query.count()

    supplier_stat_cards = [
        {
            "label": "Total Supplier",
            "value": total_suppliers,
            "icon": "fa-truck",
            "accent": "text-primary",
            "type": "count",
            "description": "Partner pemasok yang siap dihubungi."
        },
        {
            "label": "Kontak Lengkap",
            "value": contact_complete,
            "icon": "fa-phone-alt",
            "accent": "text-success",
            "type": "count",
            "description": "Supplier dengan nomor telepon tercatat."
        },
        {
            "label": "Punya Website",
            "value": website_complete,
            "icon": "fa-globe",
            "accent": "text-info",
            "type": "count",
            "description": "Supplier yang menyediakan alamat website."
        },
        {
            "label": "Faktur Pembelian",
            "value": purchase_count,
            "icon": "fa-file-invoice",
            "accent": "text-warning",
            "type": "count",
            "description": "Jumlah transaksi pembelian tercatat."
        }
    ]

    supplier_insights = [
        {
            "title": "Perlu nomor kontak",
            "value": contact_missing,
            "status": "warning" if contact_missing else "success",
            "type": "count",
            "description": "Lengkapi nomor telepon untuk respons cepat."
        },
        {
            "title": "Perlu email",
            "value": email_missing,
            "status": "info" if email_missing else "success",
            "type": "count",
            "description": "Email memudahkan pengiriman PO dan faktur."
        },
        {
            "title": "Memiliki website",
            "value": website_complete,
            "status": "success" if website_complete else "secondary",
            "type": "count",
            "description": "Website membantu akses katalog pemasok."
        }
    ]

    top_supplier = (
        db.session.query(Supplier.name, func.count(Pembelian.id).label('jumlah'))
        .join(Pembelian, Pembelian.supplier_id == Supplier.id)
        .group_by(Supplier.id)
        .order_by(func.count(Pembelian.id).desc())
        .first()
    )
    if top_supplier:
        supplier_insights.append({
            "title": "Partner teraktif",
            "value": top_supplier.jumlah,
            "status": "success",
            "type": "count",
            "description": f"{top_supplier.name} paling sering memasok."
        })

    supplier_payload = [
        {
            "id": supplier.id,
            "name": supplier.name,
            "address": supplier.address,
            "phone": supplier.phone,
            "bank_account": supplier.bank_account,
            "account_name": supplier.account_name,
            "contact_person": supplier.contact_person,
            "email": supplier.email,
            "website": supplier.website
        }
        for supplier in suppliers
    ]

    recent_purchases = []
    recent_query = (
        Pembelian.query.order_by(Pembelian.tanggal_faktur.desc(), Pembelian.id.desc())
        .limit(5)
        .all()
    )
    for purchase in recent_query:
        total_units = sum(item.jumlah for item in purchase.barang)
        recent_purchases.append({
            "no_faktur": purchase.no_faktur,
            "tanggal": purchase.tanggal_faktur.strftime('%d %b %Y') if purchase.tanggal_faktur else '-',
            "supplier": purchase.supplier.name if purchase.supplier else 'Tanpa supplier',
            "items": total_units
        })

    return {
        "suppliers": suppliers,
        "supplier_payload": supplier_payload,
        "supplier_stat_cards": supplier_stat_cards,
        "supplier_insights": supplier_insights,
        "recent_purchases": recent_purchases,
        "search_query": search_query,
        "edit_supplier": edit_supplier
    }


@bp.route('/supplier', methods=['GET', 'POST'])
def supplier():
    search_query = request.args.get('search', '').strip()

    if request.method == 'POST':
        # Ambil data dari formulir
        name = request.form['name'].strip()
        address = request.form['address'].strip()
        phone = request.form['phone'].strip()
        bank_account = request.form['bank_account'].strip()
        account_name = request.form['account_name'].strip()
        contact_person = request.form['contact_person'].strip()
        email = request.form['email'].strip()
        website = request.form['website'].strip()

        existing_supplier = Supplier.query.filter_by(email=email).first()
        if existing_supplier:
            flash('Email supplier sudah terdaftar.', 'warning')
            return redirect(url_for('main.supplier'))

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

    return render_template('supplier.html', **_build_supplier_page_context(search_query=search_query))


@bp.route('/supplier/edit/<int:supplier_id>', methods=['GET', 'POST'])
def edit_supplier(supplier_id):
    search_query = request.args.get('search', '').strip()
    supplier = Supplier.query.get_or_404(supplier_id)

    if request.method == 'POST':
        supplier.name = request.form['name'].strip()
        supplier.address = request.form['address'].strip()
        supplier.phone = request.form['phone'].strip()
        supplier.bank_account = request.form['bank_account'].strip()
        supplier.account_name = request.form['account_name'].strip()
        supplier.contact_person = request.form['contact_person'].strip()
        email = request.form['email'].strip()
        supplier.website = request.form['website'].strip()

        existing = Supplier.query.filter(Supplier.email == email, Supplier.id != supplier.id).first()
        if existing:
            flash('Email supplier sudah digunakan oleh supplier lain.', 'warning')
            return redirect(url_for('main.edit_supplier', supplier_id=supplier_id))

        supplier.email = email

        db.session.commit()
        flash('Supplier updated successfully!', 'success')
        return redirect('/supplier')

    return render_template(
        'supplier.html',
        **_build_supplier_page_context(edit_supplier=supplier, search_query=search_query)
    )

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

    def _parse_float(value, default=None):
        if value is None:
            return default
        try:
            value = str(value).strip()
            if not value:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _parse_int(value, default=None):
        if value is None:
            return default
        try:
            value = str(value).strip()
            if not value:
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    def _parse_date(value):
        if not value:
            return None
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            return None

    if request.method == 'POST':
        if not produk_to_edit:
            produk_id_form = request.form.get('produk_id')
            if produk_id_form:
                produk_to_edit = Produk.query.get(produk_id_form)

        kode_produk = request.form.get('kode_produk', '').strip()
        nama_produk = request.form.get('nama_produk', '').strip()
        satuan_id = _parse_int(request.form.get('satuan'))
        kategori_id = _parse_int(request.form.get('kategori'))
        supplier_id = _parse_int(request.form.get('supplier'))
        sku = request.form.get('sku', '').strip() or None
        barcode = request.form.get('barcode', '').strip() or None
        berat = _parse_float(request.form.get('berat'))
        stok_minimal = _parse_int(request.form.get('stok_minimal'), default=0)
        tanggal_expired = _parse_date(request.form.get('tanggal_expired'))

        if not kode_produk or not nama_produk or not satuan_id or not kategori_id or not supplier_id:
            flash('Pastikan semua field wajib diisi.', 'warning')
            return redirect(url_for('main.produk'))

        try:
            if produk_to_edit:
                existing = Produk.query.filter(
                    Produk.kode_produk == kode_produk,
                    Produk.id != produk_to_edit.id
                ).first()
                if existing:
                    flash(f'Kode produk {kode_produk} sudah digunakan.', 'warning')
                    return redirect(url_for('main.produk', edit=produk_to_edit.id))

                produk_to_edit.kode_produk = kode_produk
                produk_to_edit.sku = sku
                produk_to_edit.barcode = barcode
                produk_to_edit.nama_produk = nama_produk
                produk_to_edit.satuan_id = satuan_id
                produk_to_edit.kategori_id = kategori_id
                produk_to_edit.supplier_id = supplier_id
                produk_to_edit.berat = berat
                produk_to_edit.stok_minimal = stok_minimal or 0
                produk_to_edit.tanggal_expired = tanggal_expired
                db.session.commit()
                flash('Produk updated successfully!', 'success')
            else:
                existing = Produk.query.filter_by(kode_produk=kode_produk).first()
                if existing:
                    flash(f'Kode produk {kode_produk} sudah digunakan.', 'warning')
                    return redirect(url_for('main.produk'))

                new_produk = Produk(
                    kode_produk=kode_produk,
                    sku=sku,
                    barcode=barcode,
                    nama_produk=nama_produk,
                    satuan_id=satuan_id,
                    kategori_id=kategori_id,
                    supplier_id=supplier_id,
                    berat=berat,
                    stok_minimal=stok_minimal or 0,
                    tanggal_expired=tanggal_expired
                )
                db.session.add(new_produk)
                db.session.commit()
                flash('Produk added successfully!', 'success')

        except IntegrityError as exc:
            db.session.rollback()
            flash(f'Gagal menyimpan produk: {str(exc.orig)}', 'danger')
        except Exception as exc:
            db.session.rollback()
            logging.exception('Gagal menyimpan produk')
            flash(f'Error: {str(exc)}', 'danger')

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

    total_produk = len(produks)
    total_kategori = len(kategoris)
    total_suppliers = len(suppliers)
    stok_threshold_missing = Produk.query.filter(
        or_(Produk.stok_minimal.is_(None), Produk.stok_minimal <= 0)
    ).count()
    expiry_tracked = Produk.query.filter(Produk.tanggal_expired.isnot(None)).count()
    no_barcode = Produk.query.filter(or_(Produk.barcode.is_(None), Produk.barcode == '')).count()

    stat_cards = [
        {
            "label": "Produk Aktif",
            "value": total_produk,
            "icon": "fa-box-open",
            "accent": "text-primary",
            "description": "Item tersedia di katalog"
        },
        {
            "label": "Kategori",
            "value": total_kategori,
            "icon": "fa-tags",
            "accent": "text-success",
            "description": "Kelompok produk yang digunakan"
        },
        {
            "label": "Supplier Terhubung",
            "value": total_suppliers,
            "icon": "fa-truck",
            "accent": "text-warning",
            "description": "Relasi pemasok tersimpan"
        },
        {
            "label": "Kadaluarsa Dipantau",
            "value": expiry_tracked,
            "icon": "fa-hourglass-half",
            "accent": "text-danger",
            "description": "Produk memiliki tanggal expired"
        },
    ]

    health_insights = [
        {
            "title": "Butuh target stok",
            "value": stok_threshold_missing,
            "status": "warning" if stok_threshold_missing else "success",
            "description": "Produk belum memiliki batas stok minimal. Atur angka untuk menghindari kehabisan."
        },
        {
            "title": "Belum ada barcode",
            "value": no_barcode,
            "status": "info" if no_barcode else "success",
            "description": "Lengkapi barcode agar proses penjualan kasir lebih cepat."
        },
        {
            "title": "Tanggal expired tercatat",
            "value": expiry_tracked,
            "status": "success" if expiry_tracked else "secondary",
            "description": "Pantau masa kadaluarsa barang sensitif dan atur promo lebih awal."
        }
    ]

    expiring_products = (
        Produk.query.filter(Produk.tanggal_expired.isnot(None))
        .order_by(Produk.tanggal_expired.asc())
        .limit(5)
        .all()
    )

    return render_template(
        'data_produk.html',
        produks=produks,
        satuans=satuans,
        kategoris=kategoris,
        suppliers=suppliers,
        stat_cards=stat_cards,
        health_insights=health_insights,
        expiring_products=expiring_products,
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
    try:
        db.session.delete(produk)
        db.session.commit()
        flash('Produk deleted successfully!', 'success')
    except IntegrityError as exc:
        db.session.rollback()
        flash('Produk tidak dapat dihapus karena masih memiliki relasi transaksi.', 'warning')
    except Exception as exc:
        db.session.rollback()
        logging.exception('Gagal menghapus produk')
        flash(f'Gagal menghapus produk: {str(exc)}', 'danger')
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


def _build_customer_page_context(edit_pelanggan=None, search_query=''):
    all_customers = Pelanggan.query.order_by(Pelanggan.id.desc()).all()

    filtered_query = Pelanggan.query.order_by(Pelanggan.id.desc())
    if search_query:
        like_pattern = f"%{search_query}%"
        filtered_query = filtered_query.filter(
            or_(
                Pelanggan.nama.ilike(like_pattern),
                Pelanggan.pelanggan_id.ilike(like_pattern),
                Pelanggan.kontak.ilike(like_pattern)
            )
        )

    pelanggans = filtered_query.all()

    total_customers = len(all_customers)

    def has_value(value):
        return bool(value and value.strip())

    complete_contacts = sum(1 for pelanggan in all_customers if has_value(pelanggan.kontak))
    complete_addresses = sum(1 for pelanggan in all_customers if has_value(pelanggan.alamat))
    missing_contact = total_customers - complete_contacts
    missing_address = total_customers - complete_addresses

    unique_contacts = len({pelanggan.kontak.strip() for pelanggan in all_customers if has_value(pelanggan.kontak)})
    duplicate_contacts = max(0, complete_contacts - unique_contacts)

    contact_completion = int(round((complete_contacts / total_customers) * 100)) if total_customers else 0
    address_completion = int(round((complete_addresses / total_customers) * 100)) if total_customers else 0

    stat_cards = [
        {
            "label": "Total Pelanggan",
            "value": total_customers,
            "icon": "fa-users",
            "accent": "text-primary",
            "description": "Relasi aktif tersimpan"
        },
        {
            "label": "Kontak Lengkap",
            "value": complete_contacts,
            "icon": "fa-phone-alt",
            "accent": "text-success",
            "description": f"{contact_completion}% siap dihubungi"
        },
        {
            "label": "Alamat Tercatat",
            "value": complete_addresses,
            "icon": "fa-map-marker-alt",
            "accent": "text-info",
            "description": f"{address_completion}% siap dikunjungi"
        },
        {
            "label": "Perlu Kontak",
            "value": missing_contact,
            "icon": "fa-user-clock",
            "accent": "text-warning",
            "description": "Lengkapi agar mudah follow-up"
        },
    ]

    insights = [
        {
            "title": "Pelanggan tanpa kontak",
            "value": missing_contact,
            "status": "warning" if missing_contact else "success",
            "description": "Tambahkan nomor telepon agar mudah dihubungi."
        },
        {
            "title": "Pelanggan tanpa alamat",
            "value": missing_address,
            "status": "info" if missing_address else "success",
            "description": "Alamat penting untuk pengiriman dan layanan purna jual."
        },
        {
            "title": "Kontak duplikat",
            "value": duplicate_contacts,
            "status": "secondary" if duplicate_contacts == 0 else "warning",
            "description": "Gunakan data unik supaya kampanye marketing lebih akurat."
        }
    ]

    next_customer_id = Pelanggan.generate_pelanggan_id()
    recent_customers = all_customers[:5]

    return {
        "pelanggans": pelanggans,
        "stat_cards": stat_cards,
        "insights": insights,
        "recent_customers": recent_customers,
        "contact_completion": contact_completion,
        "address_completion": address_completion,
        "next_customer_id": next_customer_id,
        "edit_pelanggan": edit_pelanggan,
        "search_query": search_query,
        "filtered_count": len(pelanggans),
        "total_customers": total_customers
    }


@bp.route('/pelanggan', methods=['GET', 'POST'])
def pelanggan():
    search_query = request.args.get('search', '').strip()

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

    return render_template('data_pelanggan.html', **_build_customer_page_context(search_query=search_query))


@bp.route('/pelanggan/edit/<int:pelanggan_id>', methods=['GET', 'POST'])
def edit_pelanggan(pelanggan_id):
    search_query = request.args.get('search', '').strip()
    pelanggan = Pelanggan.query.get_or_404(pelanggan_id)

    if request.method == 'POST':
        pelanggan.nama = request.form['nama']
        pelanggan.kontak = request.form['kontak']
        pelanggan.alamat = request.form['alamat']
        db.session.commit()
        flash(f'Pelanggan {pelanggan.nama} updated successfully!', 'success')
        return redirect('/pelanggan')

    return render_template(
        'data_pelanggan.html',
        **_build_customer_page_context(edit_pelanggan=pelanggan, search_query=search_query)
    )


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
    if request.method == 'POST':
        try:
            if not request.is_json:
                return jsonify({"success": False, "message": "Content-Type harus 'application/json'"}), 415

            payload = request.get_json(silent=True) or {}

            tanggal_faktur = payload.get('tanggal_faktur')
            no_faktur = (payload.get('no_faktur') or '').strip()
            supplier_id = payload.get('supplier')
            items = payload.get('items') or []

            if not tanggal_faktur or not no_faktur or not supplier_id:
                return jsonify({"success": False, "message": "Data utama tidak lengkap."}), 400

            if Pembelian.query.filter_by(no_faktur=no_faktur).first():
                return jsonify({"success": False, "message": f"Nomor faktur {no_faktur} sudah ada."}), 400

            parsed_date = None
            try:
                parsed_date = datetime.strptime(tanggal_faktur, '%Y-%m-%d')
            except ValueError:
                return jsonify({"success": False, "message": "Format tanggal faktur tidak valid."}), 400

            try:
                supplier_id = int(supplier_id)
            except (TypeError, ValueError):
                return jsonify({"success": False, "message": "Supplier tidak valid."}), 400

            supplier = Supplier.query.get(supplier_id)
            if not supplier:
                return jsonify({"success": False, "message": "Supplier tidak ditemukan."}), 404

            if not items:
                return jsonify({"success": False, "message": "Tidak ada data barang yang dikirim."}), 400

            valid_items = []
            errors = []

            for index, item in enumerate(items, start=1):
                kode_barang = (item.get('kode_barang') or '').strip()
                nama_barang = (item.get('nama_barang') or '').strip()
                kategori = (item.get('kategori') or '').strip()

                try:
                    jumlah = int(item.get('jumlah') or 0)
                except (TypeError, ValueError):
                    jumlah = 0

                try:
                    harga_beli = float(item.get('harga_beli') or 0.0)
                except (TypeError, ValueError):
                    harga_beli = 0.0

                try:
                    diskon = float(item.get('diskon') or 0.0)
                except (TypeError, ValueError):
                    diskon = 0.0

                try:
                    pajak = float(item.get('pajak') or 0.0)
                except (TypeError, ValueError):
                    pajak = 0.0

                try:
                    harga_jual = float(item.get('harga_jual') or 0.0)
                except (TypeError, ValueError):
                    harga_jual = 0.0

                exp_date_raw = item.get('exp_date')
                exp_date = None
                if exp_date_raw:
                    try:
                        exp_date = datetime.strptime(exp_date_raw, '%Y-%m-%d')
                    except ValueError:
                        errors.append(f"Tanggal exp tidak valid pada baris {index}.")

                if not kode_barang or not nama_barang or not kategori:
                    errors.append(f"Kode, nama, dan kategori wajib diisi (baris {index}).")
                    continue

                if jumlah <= 0:
                    errors.append(f"Jumlah harus lebih dari 0 (baris {index}).")
                    continue

                diskon = max(0.0, min(diskon, 100.0))
                pajak = max(0.0, pajak)

                discount_amount = harga_beli * (diskon / 100.0)
                taxable_base = harga_beli - discount_amount
                tax_amount = taxable_base * (pajak / 100.0)
                harga_final = taxable_base + tax_amount
                total_hpp = harga_final * jumlah

                produk = Produk.query.filter_by(kode_produk=kode_barang).first()

                valid_items.append({
                    "kode_barang": kode_barang,
                    "nama_barang": nama_barang,
                    "kategori": kategori,
                    "jumlah": jumlah,
                    "harga_beli": harga_beli,
                    "diskon": diskon,
                    "pajak": pajak,
                    "harga_jual": harga_jual,
                    "exp_date": exp_date,
                    "harga_final": harga_final,
                    "total_hpp": total_hpp,
                    "produk": produk
                })

            if errors:
                return jsonify({"success": False, "message": " ".join(errors)}), 400

            if not valid_items:
                return jsonify({"success": False, "message": "Tidak ada baris barang yang valid."}), 400

            pembelian = Pembelian(
                tanggal_faktur=parsed_date,
                no_faktur=no_faktur,
                supplier_id=supplier_id
            )
            db.session.add(pembelian)
            db.session.flush()

            total_pembelian = 0.0
            total_items = 0

            for item in valid_items:
                produk = item["produk"]
                if produk:
                    produk.update_stok_dan_hpp(item["harga_final"], item["jumlah"])

                barang_pembelian = BarangPembelian(
                    pembelian_id=pembelian.id,
                    kode_barang=item["kode_barang"],
                    nama_barang=item["nama_barang"],
                    kategori=item["kategori"],
                    jumlah=item["jumlah"],
                    harga_beli=item["harga_beli"],
                    diskon=item["diskon"],
                    pajak=item["pajak"],
                    harga_jual=item["harga_jual"],
                    exp_date=item["exp_date"],
                    hpp=item["total_hpp"]
                )
                total_pembelian += item["total_hpp"]
                total_items += item["jumlah"]
                db.session.add(barang_pembelian)

            db.session.commit()

            return jsonify({
                "success": True,
                "message": "Pembelian berhasil disimpan!",
                "total_biaya": total_pembelian,
                "total_barang": total_items
            }), 200

        except Exception as exc:
            db.session.rollback()
            logging.exception('Gagal menyimpan pembelian')
            return jsonify({"success": False, "message": f"Error: {str(exc)}"}), 500

    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    supplier_payload = [
        {
            "id": supplier.id,
            "name": supplier.name,
            "contact_person": supplier.contact_person,
            "phone": supplier.phone,
            "email": supplier.email,
            "address": supplier.address
        }
        for supplier in suppliers
    ]

    supplier_lookup = {
        supplier["id"]: supplier for supplier in supplier_payload
    }

    produk_records = Produk.query.order_by(Produk.nama_produk.asc()).all()
    product_payload = [
        {
            "kode": produk.kode_produk,
            "nama": produk.nama_produk,
            "kategori": produk.kategori.name if produk.kategori else None,
            "harga_beli": float(produk.harga_beli or 0.0),
            "harga_jual": float(produk.harga or 0.0),
            "sku": produk.sku,
            "supplier": produk.supplier.name if produk.supplier else None,
        }
        for produk in produk_records
    ]

    total_invoices = Pembelian.query.count()
    total_spent = db.session.query(func.coalesce(func.sum(BarangPembelian.hpp), 0)).scalar() or 0.0
    total_items = db.session.query(func.coalesce(func.sum(BarangPembelian.jumlah), 0)).scalar() or 0
    today = datetime.utcnow().date()
    today_invoices = Pembelian.query.filter(Pembelian.tanggal_faktur == today).count()
    average_invoice = total_spent / total_invoices if total_invoices else 0.0

    purchase_stat_cards = [
        {
            "label": "Total Faktur",
            "value": total_invoices,
            "icon": "fa-file-invoice",
            "accent": "text-primary",
            "type": "count",
            "description": "Jumlah transaksi pembelian tersimpan."
        },
        {
            "label": "Total Pengeluaran",
            "value": total_spent,
            "icon": "fa-coins",
            "accent": "text-success",
            "type": "currency",
            "description": "Akumulasi biaya restock."
        },
        {
            "label": "Faktur Hari Ini",
            "value": today_invoices,
            "icon": "fa-calendar-day",
            "accent": "text-info",
            "type": "count",
            "description": "Restock yang tercatat hari ini."
        },
        {
            "label": "Rata-rata Faktur",
            "value": average_invoice,
            "icon": "fa-chart-bar",
            "accent": "text-warning",
            "type": "currency",
            "description": "Nilai rata-rata per transaksi pembelian."
        },
    ]

    purchase_insights = [
        {
            "title": "Total barang masuk",
            "value": total_items,
            "status": "info" if total_items else "secondary",
            "type": "count",
            "description": "Jumlah unit yang direstock dari seluruh faktur."
        },
        {
            "title": "Supplier aktif",
            "value": len(suppliers),
            "status": "success" if suppliers else "secondary",
            "type": "count",
            "description": "Partner pemasok yang siap memenuhi restock."
        },
        {
            "title": "Pengeluaran rata-rata",
            "value": average_invoice,
            "status": "warning" if average_invoice else "secondary",
            "type": "currency",
            "description": "Gunakan sebagai acuan budgeting pembelian."
        }
    ]

    upcoming_expiry = (
        BarangPembelian.query
        .filter(BarangPembelian.exp_date.isnot(None))
        .order_by(BarangPembelian.exp_date.asc())
        .limit(5)
        .all()
    )
    if upcoming_expiry:
        earliest = upcoming_expiry[0]
        purchase_insights.append({
            "title": "Produk mendekati kadaluarsa",
            "value": earliest.exp_date.strftime('%d %b %Y') if earliest.exp_date else '-',
            "status": "warning",
            "type": "text",
            "description": f"{earliest.nama_barang} perlu diprioritaskan."
        })

    recent_purchases = []
    recent_query = (
        Pembelian.query.order_by(Pembelian.tanggal_faktur.desc(), Pembelian.id.desc())
        .limit(5)
        .all()
    )
    for purchase in recent_query:
        total_cost = sum(barang.hpp for barang in purchase.barang)
        total_units = sum(barang.jumlah for barang in purchase.barang)
        recent_purchases.append({
            "no_faktur": purchase.no_faktur,
            "tanggal": purchase.tanggal_faktur.strftime('%d %b %Y') if purchase.tanggal_faktur else '-',
            "supplier": purchase.supplier.name if purchase.supplier else 'Tanpa supplier',
            "total": total_cost,
            "items": total_units
        })

    return render_template(
        'pembelian.html',
        supplier_payload=supplier_payload,
        supplier_lookup=supplier_lookup,
        product_payload=product_payload,
        purchase_stat_cards=purchase_stat_cards,
        purchase_insights=purchase_insights,
        recent_purchases=recent_purchases
    )


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

    pelanggan_records = Pelanggan.query.order_by(Pelanggan.nama.asc()).all()
    form.pelanggan_id.choices = [(0, 'Pilih pelanggan')] + [
        (p.id, f"{p.nama} ({p.pelanggan_id})") for p in pelanggan_records
    ]
    if form.pelanggan_id.data is None:
        form.pelanggan_id.data = 0

    produk_records = Produk.query.order_by(Produk.nama_produk.asc()).all()
    produk_payload = [
        {
            "id": produk.id,
            "name": produk.nama_produk,
            "code": produk.kode_produk,
            "price": float(produk.harga or 0.0),
            "sku": produk.sku,
            "kategori": produk.kategori.name if produk.kategori else None
        }
        for produk in produk_records
    ]

    customer_lookup = {
        pelanggan.id: {
            "name": pelanggan.nama,
            "code": pelanggan.pelanggan_id,
            "kontak": pelanggan.kontak,
            "alamat": pelanggan.alamat
        }
        for pelanggan in pelanggan_records
    }

    total_orders = Penjualan.query.count()
    total_revenue = db.session.query(func.coalesce(func.sum(Penjualan.total_harga), 0)).scalar() or 0.0
    items_sold = db.session.query(func.coalesce(func.sum(DetailPenjualan.jumlah), 0)).scalar() or 0
    today = datetime.utcnow().date()
    today_orders = Penjualan.query.filter(Penjualan.tanggal_penjualan == today).count()
    average_order = total_revenue / total_orders if total_orders else 0.0

    sales_stat_cards = [
        {
            "label": "Total Transaksi",
            "value": total_orders,
            "icon": "fa-receipt",
            "accent": "text-primary",
            "type": "count",
            "description": "Jumlah penjualan tercatat."
        },
        {
            "label": "Pendapatan",
            "value": total_revenue,
            "icon": "fa-wallet",
            "accent": "text-success",
            "type": "currency",
            "description": "Akumulasi nilai transaksi."
        },
        {
            "label": "Rata-rata Order",
            "value": average_order,
            "icon": "fa-chart-line",
            "accent": "text-info",
            "type": "currency",
            "description": "Nilai rata-rata per transaksi."
        },
        {
            "label": "Transaksi Hari Ini",
            "value": today_orders,
            "icon": "fa-calendar-day",
            "accent": "text-warning",
            "type": "count",
            "description": "Order yang tercatat pada tanggal ini."
        },
    ]

    sales_insights = [
        {
            "title": "Unit terjual",
            "value": items_sold,
            "status": "warning" if items_sold else "secondary",
            "type": "count",
            "description": "Akumulasi kuantitas produk di seluruh transaksi."
        },
        {
            "title": "Transaksi hari ini",
            "value": today_orders,
            "status": "info" if today_orders else "secondary",
            "type": "count",
            "description": "Pantau aktivitas penjualan harian."
        },
        {
            "title": "Rata-rata order",
            "value": average_order,
            "status": "success" if average_order else "secondary",
            "type": "currency",
            "description": "Indikasi nilai order rata-rata pelanggan."
        }
    ]

    top_customer = (
        db.session.query(Pelanggan.nama, func.count(Penjualan.id).label('jumlah'))
        .join(Penjualan, Penjualan.pelanggan_id == Pelanggan.id)
        .group_by(Pelanggan.id)
        .order_by(func.count(Penjualan.id).desc())
        .first()
    )
    if top_customer:
        sales_insights.append({
            "title": "Pelanggan teraktif",
            "value": top_customer.jumlah,
            "status": "success",
            "type": "count",
            "description": f"{top_customer.nama} paling sering bertransaksi."
        })

    recent_sales_query = (
        Penjualan.query.order_by(Penjualan.tanggal_penjualan.desc(), Penjualan.id.desc())
        .limit(5)
        .all()
    )
    recent_sales = [
        {
            "no_faktur": sale.no_faktur,
            "tanggal": sale.tanggal_penjualan.strftime('%d %b %Y') if sale.tanggal_penjualan else '-',
            "pelanggan": sale.pelanggan.nama if sale.pelanggan else 'Umum',
            "total": float(sale.total_harga or 0.0),
            "items": sum(detail.jumlah for detail in sale.detail_penjualan)
        }
        for sale in recent_sales_query
    ]

    if form.validate_on_submit():
        try:
            sales_id = session.get('user_id')
            if not sales_id:
                raise ValueError('Silakan login sebelum mencatat penjualan.')

            produk_id_list = request.form.getlist('produk_id[]')
            jumlah_list = request.form.getlist('jumlah[]')
            harga_list = request.form.getlist('harga[]')
            diskon_list = request.form.getlist('diskon[]')
            pajak_list = request.form.getlist('pajak[]')

            line_items = []
            errors = []

            for idx, raw_product_id in enumerate(produk_id_list):
                if not raw_product_id:
                    continue

                try:
                    product_id = int(raw_product_id)
                except (TypeError, ValueError):
                    errors.append(f"Produk tidak valid pada baris {idx + 1}.")
                    continue

                product = Produk.query.get(product_id)
                if not product:
                    errors.append(f"Produk dengan ID {product_id} tidak ditemukan (baris {idx + 1}).")
                    continue

                qty_raw = jumlah_list[idx] if idx < len(jumlah_list) else ''
                price_raw = harga_list[idx] if idx < len(harga_list) else ''
                diskon_raw = diskon_list[idx] if idx < len(diskon_list) else ''
                pajak_raw = pajak_list[idx] if idx < len(pajak_list) else ''

                try:
                    qty = int(qty_raw)
                except (TypeError, ValueError):
                    qty = 0

                if qty <= 0:
                    errors.append(f"Jumlah harus lebih dari 0 untuk {product.nama_produk}.")
                    continue

                try:
                    price = float(price_raw) if price_raw not in (None, '') else float(product.harga or 0.0)
                except (TypeError, ValueError):
                    price = float(product.harga or 0.0)

                try:
                    discount = float(diskon_raw) if diskon_raw not in (None, '') else 0.0
                except (TypeError, ValueError):
                    discount = 0.0

                try:
                    tax = float(pajak_raw) if pajak_raw not in (None, '') else 0.0
                except (TypeError, ValueError):
                    tax = 0.0

                discount = max(0.0, min(discount, 100.0))
                tax = max(0.0, tax)

                base_total = price * qty
                discount_amount = base_total * (discount / 100.0)
                taxable_base = base_total - discount_amount
                tax_amount = taxable_base * (tax / 100.0)
                line_total = taxable_base + tax_amount

                line_items.append({
                    "product": product,
                    "qty": qty,
                    "price": price,
                    "discount": discount,
                    "tax": tax,
                    "line_total": line_total
                })

            if errors:
                raise ValueError(' '.join(errors))

            if not line_items:
                raise ValueError('Tambahkan minimal satu produk dengan jumlah valid.')

            penjualan = Penjualan(
                sales_id=sales_id,
                pelanggan_id=form.pelanggan_id.data,
                total_harga=0.0
            )
            db.session.add(penjualan)
            db.session.flush()

            for item in line_items:
                detail = DetailPenjualan(
                    penjualan_id=penjualan.id,
                    produk_id=item["product"].id,
                    jumlah=item["qty"],
                    harga_satuan=item["price"],
                    diskon=item["discount"],
                    pajak=item["tax"],
                    harga_total=item["line_total"]
                )
                penjualan.total_harga += item["line_total"]
                db.session.add(detail)

            db.session.commit()
            flash(f'Penjualan berhasil disimpan (total Rp {penjualan.total_harga:,.0f}).', 'success')
            return redirect(url_for('main.penjualan'))

        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'warning')
        except Exception as e:
            db.session.rollback()
            logging.exception('Gagal menyimpan penjualan')
            flash(f'Error: {str(e)}', 'danger')

    return render_template(
        'penjualan.html',
        form=form,
        produk_list=produk_records,
        produk_payload=produk_payload,
        sales_stat_cards=sales_stat_cards,
        sales_insights=sales_insights,
        recent_sales=recent_sales,
        customer_lookup=customer_lookup
    )

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
