from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    flash,
    url_for,
    session,
    g,
    jsonify,
    current_app,
)
from functools import wraps
from urllib.parse import urlparse, urljoin
import shutil
from collections import defaultdict
import secrets
import json
from datetime import datetime, timedelta
import logging
from io import BytesIO
import math
import os
import re
from importlib import util
from pathlib import Path
_psutil_spec = util.find_spec("psutil")
psutil = __import__("psutil") if _psutil_spec else None

import pandas as pd
from flask import make_response
from sqlalchemy import or_, and_, func, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import joinedload
from sqlalchemy.engine.url import make_url
from werkzeug.security import generate_password_hash, check_password_hash

from app import csrf
from app.forms import SalesForm
from app.models import (
    User,
    db,
    Supplier,
    Satuan,
    Kategori,
    Produk,
    Pelanggan,
    Pembelian,
    BarangPembelian,
    Penjualan,
    DetailPenjualan,
    PasswordResetToken,
    PriceLevel,
    ProductPriceLevel,
    PriceLevelCost,
    PriceChange,
    StockOpnameSession,
    StockOpnameItem,
    AccountingSetting,
    AccountingPeriod,
    Account,
    JournalEntry,
    JournalLine,
)

bp = Blueprint("main", __name__)

INDONESIAN_MONTHS = [
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
]

ROLE_ADMIN = "admin"
ROLE_KASIR = "kasir"
ROLE_SALES = "sales"
ROLE_GUDANG = "gudang"
ALL_ROLES = {ROLE_ADMIN, ROLE_KASIR, ROLE_SALES, ROLE_GUDANG}
ALL_ROLE_CHOICES = (ROLE_ADMIN, ROLE_KASIR, ROLE_SALES, ROLE_GUDANG)
INVENTORY_ROLES = (ROLE_ADMIN, ROLE_GUDANG)
SALES_ROLES = (ROLE_ADMIN, ROLE_KASIR, ROLE_SALES)
ADMIN_ONLY = (ROLE_ADMIN,)


def _is_safe_redirect_target(target: str) -> bool:
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def _accepts_json():
    return (
        request.path.startswith("/api/")
        or request.is_json
        or (request.accept_mimetypes and request.accept_mimetypes.accept_json)
    )


def _auth_required_response():
    if _accepts_json():
        return jsonify({"error": "Authentication required"}), 401

    flash("Silakan login untuk mengakses halaman tersebut.", "warning")
    if request.method == "GET":
        next_target = request.full_path or request.path
    else:
        next_target = request.referrer or request.path
    if not _is_safe_redirect_target(next_target):
        next_target = url_for("main.dashboard")
    return redirect(url_for("main.login", next=next_target))


def _forbidden_response(allowed_roles):
    if _accepts_json():
        return (
            jsonify(
                {
                    "error": "Forbidden",
                    "allowed_roles": sorted(r for r in allowed_roles),
                }
            ),
            403,
        )

    flash("Anda tidak memiliki akses ke halaman tersebut.", "danger")
    return redirect(url_for("main.dashboard"))


def get_current_user():
    if hasattr(g, "_current_user"):
        return g._current_user

    user = None
    user_id = session.get("user_id")
    if user_id:
        user = User.query.get(user_id)
        if user:
            session["username"] = user.username
            session["role"] = user.role
            session["email"] = user.email

    if not user:
        session.pop("user_id", None)
        session.pop("username", None)
        session.pop("role", None)
        session.pop("email", None)

    g._current_user = user
    return user


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not get_current_user():
            return _auth_required_response()
        return view_func(*args, **kwargs)

    return wrapped_view


def roles_required(*allowed_roles, allow_admin=True):
    allowed_set = {role.lower() for role in allowed_roles if role}

    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(*args, **kwargs):
            user = get_current_user()
            if not user:
                return _auth_required_response()

            user_role = (user.role or "").lower()
            if allow_admin and user_role == ROLE_ADMIN:
                return view_func(*args, **kwargs)

            if allowed_set and user_role in allowed_set:
                return view_func(*args, **kwargs)

            return _forbidden_response(allowed_set or ALL_ROLES)

        return wrapped_view

    return decorator


def _safe_next_url(default_endpoint="main.dashboard", candidate=None):
    target = candidate or request.args.get("next")
    if target and _is_safe_redirect_target(target):
        return target
    return url_for(default_endpoint)


def _normalize_price_value(raw_value):
    if raw_value in (None, "", "null"):
        return None
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    try:
        value = str(raw_value).strip()
    except Exception:
        return None
    if not value:
        return None
    cleaned = value.replace("Rp", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        if cleaned.find(",") > cleaned.find("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except Exception:
        try:
            return float(value)
        except Exception:
            return None


def _build_price_level_entries(payload, level_lookup):
    payload = payload or []
    normalized_entries = []
    seen = set()
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            level_id = int(row.get("level_id"))
        except (TypeError, ValueError):
            continue
        if level_id in seen or level_id not in level_lookup:
            continue
        price_value = _normalize_price_value(row.get("price"))
        if price_value is None:
            continue
        seen.add(level_id)
        normalized_entries.append(
            {
                "level_id": level_id,
                "price": price_value,
            }
        )
    return normalized_entries


def _sync_product_price_levels(
    product, payload, level_lookup, normalized_entries=None
):
    normalized_entries = (
        normalized_entries
        if normalized_entries is not None
        else _build_price_level_entries(payload, level_lookup)
    )

    existing_entries = {entry.level_id: entry for entry in product.level_prices}
    keep_ids = set()

    for entry in normalized_entries:
        level_id = entry["level_id"]
        keep_ids.add(level_id)
        record = existing_entries.get(level_id)
        if record:
            record.price = entry["price"]
        else:
            record = ProductPriceLevel(
                product_id=product.id,
                level_id=level_id,
                price=entry["price"],
            )
            db.session.add(record)

    for level_id, record in list(existing_entries.items()):
        if level_id not in keep_ids:
            db.session.delete(record)

    db.session.flush()

    default_entry = None
    if product.level_prices:
        retail_level_id = next(
            (
                level_id
                for level_id in keep_ids
                if level_lookup.get(level_id)
                and (level_lookup[level_id].name or "").lower() == "retail"
            ),
            None,
        )
        if retail_level_id is not None:
            default_entry = next(
                (
                    entry
                    for entry in product.level_prices
                    if entry.level_id == retail_level_id
                ),
                None,
            )
        if not default_entry:
            default_entry = product.level_prices[0]

    product.harga = float(default_entry.price) if default_entry else 0.0


def _create_password_reset_token(user, ttl_hours=1):
    PasswordResetToken.query.filter_by(user_id=user.id, used=False).update(
        {"used": True}
    )
    token_value = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
    reset_token = PasswordResetToken(
        user_id=user.id, token=token_value, expires_at=expires_at
    )
    db.session.add(reset_token)
    db.session.commit()
    return reset_token


def _get_valid_reset_token(token_value):
    if not token_value:
        return None
    token = PasswordResetToken.query.filter_by(token=token_value).first()
    if (
        not token
        or token.used
        or token.expires_at < datetime.utcnow()
        or not token.user
    ):
        return None
    return token


def _parse_int_param(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_float_param(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date_param(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _build_sales_filters(args):
    search_query = (args.get("search") or "").strip()
    pelanggan_id = _parse_int_param(args.get("pelanggan"))
    sales_id = _parse_int_param(args.get("sales"))
    start_date = _parse_date_param(args.get("start_date"))
    end_date = _parse_date_param(args.get("end_date"))
    min_total = _parse_float_param(args.get("min_total"))
    max_total = _parse_float_param(args.get("max_total"))

    filters = []
    if search_query:
        like = f"%{search_query}%"
        filters.append(
            or_(
                Penjualan.no_faktur.ilike(like),
                Penjualan.pelanggan.has(Pelanggan.nama.ilike(like)),
                Penjualan.sales.has(User.username.ilike(like)),
            )
        )

    if pelanggan_id:
        filters.append(Penjualan.pelanggan_id == pelanggan_id)

    if sales_id:
        filters.append(Penjualan.sales_id == sales_id)

    if start_date:
        filters.append(Penjualan.tanggal_penjualan >= start_date)

    if end_date:
        filters.append(Penjualan.tanggal_penjualan <= end_date)

    expr = Penjualan.total_harga - func.coalesce(Penjualan.marketplace_cost_total, 0)
    if min_total is not None:
        filters.append(expr >= min_total)

    if max_total is not None:
        filters.append(expr <= max_total)

    return {
        "filters": filters,
        "search_query": search_query,
        "pelanggan_id": pelanggan_id,
        "sales_id": sales_id,
        "start_date": start_date,
        "end_date": end_date,
        "min_total": min_total,
        "max_total": max_total,
    }


def _format_date_id(date_value):
    if not date_value:
        return "-"
    try:
        month_label = INDONESIAN_MONTHS[date_value.month - 1]
    except IndexError:
        month_label = date_value.strftime("%b")
    return f"{date_value.day:02d} {month_label} {date_value.year}"


def _clean_import_str(value):
    if pd.isna(value):
        return None
    value = str(value).strip()
    return value or None


def _clean_import_int(value):
    if pd.isna(value) or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_import_float(value):
    if pd.isna(value) or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_import_date(value):
    if pd.isna(value) or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def _perform_produk_import(df, progress_cb=None):
    required_columns = [
        "Kode Produk",
        "SKU",
        "Nama Produk",
        "Satuan ID",
        "Kategori ID",
        "Supplier ID",
        "Berat",
        "Stok Minimal",
        "Tanggal Expired",
    ]
    if not all(column in df.columns for column in required_columns):
        raise ValueError(
            "Format file tidak valid! Pastikan semua kolom yang diperlukan ada."
        )

    created_count = 0
    updated_count = 0
    skipped_notes = []

    total_rows = len(df.index) or 1

    kode_set = set()
    satuan_ids = set()
    kategori_ids = set()
    supplier_ids = set()

    for _, row in df.iterrows():
        kode_val = _clean_import_str(row.get("Kode Produk"))
        if kode_val:
            kode_set.add(kode_val)
        satuan_val = _clean_import_int(row.get("Satuan ID"))
        kategori_val = _clean_import_int(row.get("Kategori ID"))
        supplier_val = _clean_import_int(row.get("Supplier ID"))
        if satuan_val:
            satuan_ids.add(satuan_val)
        if kategori_val:
            kategori_ids.add(kategori_val)
        if supplier_val:
            supplier_ids.add(supplier_val)

    existing_products = (
        Produk.query.filter(Produk.kode_produk.in_(list(kode_set))).all()
        if kode_set
        else []
    )
    product_by_code = {p.kode_produk: p for p in existing_products}
    sku_lookup = {p.sku: p.id for p in existing_products if p.sku}

    satuan_map = (
        {s.id: s for s in Satuan.query.filter(Satuan.id.in_(list(satuan_ids))).all()}
        if satuan_ids
        else {}
    )
    kategori_map = (
        {
            k.id: k
            for k in Kategori.query.filter(Kategori.id.in_(list(kategori_ids))).all()
        }
        if kategori_ids
        else {}
    )
    supplier_map = (
        {
            s.id: s
            for s in Supplier.query.filter(Supplier.id.in_(list(supplier_ids))).all()
        }
        if supplier_ids
        else {}
    )

    def report_progress(value, message):
        if progress_cb:
            progress_cb(value, message)

    report_progress(5, "Memeriksa kolom dan menyiapkan data...")

    for idx, row in df.iterrows():
        row_number = idx + 2  # +2 karena header di baris pertama
        kode_produk = _clean_import_str(row.get("Kode Produk"))
        if not kode_produk:
            skipped_notes.append(f"Baris {row_number}: Kode Produk kosong.")
            continue

        sku = _clean_import_str(row.get("SKU"))
        nama_produk = _clean_import_str(row.get("Nama Produk"))
        satuan_id = _clean_import_int(row.get("Satuan ID"))
        kategori_id = _clean_import_int(row.get("Kategori ID"))
        supplier_id = _clean_import_int(row.get("Supplier ID"))
        berat = _clean_import_float(row.get("Berat"))
        stok_minimal = _clean_import_int(row.get("Stok Minimal"))
        tanggal_expired = _clean_import_date(row.get("Tanggal Expired"))

        progress_value = 10 + int(((idx + 1) / total_rows) * 80)
        report_progress(progress_value, f"Memproses baris {row_number}")

        existing_produk = product_by_code.get(kode_produk)
        if existing_produk:
            changes = []

            if sku and sku != existing_produk.sku:
                owner_id = sku_lookup.get(sku)
                if owner_id and owner_id != existing_produk.id:
                    skipped_notes.append(
                        f"Baris {row_number}: SKU {sku} sudah dipakai produk lain."
                    )
                else:
                    existing_produk.sku = sku
                    changes.append("SKU")
                    sku_lookup[sku] = existing_produk.id

            if nama_produk and nama_produk != existing_produk.nama_produk:
                existing_produk.nama_produk = nama_produk
                changes.append("Nama Produk")

            if satuan_id:
                satuan = satuan_map.get(satuan_id)
                if satuan:
                    existing_produk.satuan_id = satuan_id
                    changes.append("Satuan")
                else:
                    skipped_notes.append(
                        f"Baris {row_number}: Satuan ID {satuan_id} tidak ditemukan."
                    )

            if kategori_id:
                kategori = kategori_map.get(kategori_id)
                if kategori:
                    existing_produk.kategori_id = kategori_id
                    changes.append("Kategori")
                else:
                    skipped_notes.append(
                        f"Baris {row_number}: Kategori ID {kategori_id} tidak ditemukan."
                    )

            if supplier_id:
                supplier = supplier_map.get(supplier_id)
                if supplier:
                    existing_produk.supplier_id = supplier_id
                    changes.append("Supplier")
                else:
                    skipped_notes.append(
                        f"Baris {row_number}: Supplier ID {supplier_id} tidak ditemukan."
                    )

            if berat is not None:
                existing_produk.berat = berat
                changes.append("Berat")

            if stok_minimal is not None:
                existing_produk.stok_minimal = stok_minimal
                changes.append("Stok Minimal")

            if tanggal_expired is not None:
                existing_produk.tanggal_expired = tanggal_expired
                changes.append("Tanggal Expired")

            if changes:
                updated_count += 1

            continue

        if not nama_produk:
            skipped_notes.append(
                f"Baris {row_number}: Nama Produk kosong untuk kode {kode_produk}."
            )
            continue

        satuan = satuan_map.get(satuan_id) if satuan_id else None
        kategori = kategori_map.get(kategori_id) if kategori_id else None
        supplier = supplier_map.get(supplier_id) if supplier_id else None

        if not satuan or not kategori or not supplier:
            skipped_notes.append(
                f"Baris {row_number}: Satuan/Kategori/Supplier tidak valid untuk {kode_produk}."
            )
            continue

        if sku:
            if sku in sku_lookup:
                skipped_notes.append(
                    f"Baris {row_number}: SKU {sku} sudah dipakai produk lain."
                )
                sku = None
            else:
                sku_lookup[sku] = -1

        produk = Produk(
            kode_produk=kode_produk,
            sku=sku,
            nama_produk=nama_produk,
            satuan_id=satuan.id,
            kategori_id=kategori.id,
            supplier_id=supplier.id,
            berat=berat if berat is not None else 0.0,
            stok_minimal=stok_minimal if stok_minimal is not None else 0,
            tanggal_expired=tanggal_expired,
        )
        db.session.add(produk)
        created_count += 1

    report_progress(92, "Menulis data ke database...")
    db.session.commit()
    report_progress(100, "Import selesai")

    return {
        "created": created_count,
        "updated": updated_count,
        "skipped_notes": skipped_notes,
    }


@bp.route("/")
def index():
    stats = {
        "produk": Produk.query.count(),
        "penjualan": Penjualan.query.count(),
        "pembelian": Pembelian.query.count(),
        "pelanggan": Pelanggan.query.count(),
        "supplier": Supplier.query.count(),
    }

    recent_sales = (
        Penjualan.query.order_by(Penjualan.tanggal_penjualan.desc()).limit(5).all()
    )
    recent_purchases = (
        Pembelian.query.order_by(Pembelian.tanggal_faktur.desc()).limit(5).all()
    )

    if session.get("user_id"):
        quick_links = [
            {
                "title": "Mulai Penjualan",
                "subtitle": "Catat transaksi baru",
                "icon": "fa-cash-register",
                "url": url_for("main.penjualan"),
                "tag": "Transaksi",
            },
            {
                "title": "Tambah Produk",
                "subtitle": "Kelola inventori",
                "icon": "fa-box-open",
                "url": url_for("main.produk"),
                "tag": "Inventori",
            },
            {
                "title": "Kelola Supplier",
                "subtitle": "Bangun relasi pemasok",
                "icon": "fa-truck",
                "url": url_for("main.supplier"),
                "tag": "Relasi",
            },
            {
                "title": "Data Pelanggan",
                "subtitle": "Lihat daftar pelanggan",
                "icon": "fa-users",
                "url": url_for("main.pelanggan"),
                "tag": "CRM",
            },
        ]
    else:
        quick_links = [
            {
                "title": "Masuk ke akun",
                "subtitle": "Lihat fitur lengkap aplikasi",
                "icon": "fa-sign-in-alt",
                "url": url_for("main.login"),
                "tag": "Akses",
            },
            {
                "title": "Buat akun baru",
                "subtitle": "Mulai kelola penjualan secara digital",
                "icon": "fa-user-plus",
                "url": url_for("main.register"),
                "tag": "Daftar",
            },
            {
                "title": "Jelajahi fitur",
                "subtitle": "Kenali kemampuan POS lebih dekat",
                "icon": "fa-info-circle",
                "url": url_for("main.about"),
                "tag": "Panduan",
            },
            {
                "title": "Hubungi tim",
                "subtitle": "Siap bantu setup pertama Anda",
                "icon": "fa-headset",
                "url": url_for("main.about"),
                "tag": "Dukungan",
            },
        ]

    return render_template(
        "index.html",
        stats=stats,
        recent_sales=recent_sales,
        recent_purchases=recent_purchases,
        quick_links=quick_links,
    )


@bp.route("/about")
def about():
    return render_template("about.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username:
            flash("Username wajib diisi.", "danger")
            return render_template("register.html")

        # Validasi password
        if password != confirm_password:
            flash("Passwords do not match!", "danger")
            return render_template("register.html")

        existing_username = (
            User.query.filter(func.lower(User.username) == username.lower()).first()
            if username
            else None
        )
        if existing_username:
            flash(
                "Username is already registered. Please use a different username.",
                "danger",
            )
            return render_template("register.html")

        # Periksa apakah email sudah ada
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash(
                "Email is already registered. Please use a different email.", "danger"
            )
            return render_template("register.html")

        # Hash password dan simpan ke database
        hashed_password = generate_password_hash(
            password, method="pbkdf2:sha256", salt_length=8
        )
        new_user = User(username=username, email=email, password=hashed_password)

        db.session.add(new_user)
        db.session.commit()

        flash("Registration successful! Please log in.", "success")
        return redirect("/login")

    return render_template("register.html")


@bp.route("/dashboard")
@login_required
@roles_required(*ALL_ROLE_CHOICES)
def dashboard():
    username = session.get("username")
    today = datetime.utcnow().date()
    now = datetime.utcnow()
    month_start = now.replace(day=1).date()

    net_expr = Penjualan.total_harga - func.coalesce(Penjualan.marketplace_cost_total, 0)
    total_net_revenue = (
        db.session.query(func.coalesce(func.sum(net_expr), 0)).scalar() or 0
    )
    total_marketplace_cost = (
        db.session.query(func.coalesce(func.sum(Penjualan.marketplace_cost_total), 0)).scalar()
        or 0
    )
    total_transactions = Penjualan.query.count()
    average_ticket = total_net_revenue / total_transactions if total_transactions else 0

    today_sales = Penjualan.query.filter(Penjualan.tanggal_penjualan == today).all()
    today_revenue = sum(sale.net_revenue for sale in today_sales)
    today_transactions = len(today_sales)

    month_sales = Penjualan.query.filter(
        Penjualan.tanggal_penjualan >= month_start
    ).all()
    month_revenue = sum(sale.net_revenue for sale in month_sales)
    month_transactions = len(month_sales)

    monthly_sales_map = {}
    for sale in Penjualan.query.order_by(Penjualan.tanggal_penjualan.asc()):
        if sale.tanggal_penjualan:
            key = (sale.tanggal_penjualan.year, sale.tanggal_penjualan.month)
        monthly_sales_map[key] = monthly_sales_map.get(key, 0) + sale.net_revenue

    monthly_trend = []
    for (year, month), amount in sorted(monthly_sales_map.items())[-6:]:
        label = datetime(year=year, month=month, day=1).strftime("%b %Y")
        monthly_trend.append({"label": label, "amount": amount})

    top_products_raw = (
        db.session.query(
            Produk.nama_produk.label("name"),
            func.sum(DetailPenjualan.jumlah).label("units"),
            func.sum(DetailPenjualan.harga_total).label("revenue"),
        )
        .join(Produk, Produk.id == DetailPenjualan.produk_id)
        .group_by(Produk.id)
        .order_by(func.sum(DetailPenjualan.jumlah).desc())
        .limit(5)
        .all()
    )
    top_products = [
        {
            "name": row.name,
            "units": int(row.units or 0),
            "revenue": float(row.revenue or 0),
        }
        for row in top_products_raw
    ]

    low_stock_products = (
        Produk.query.filter(
            Produk.stok_minimal.isnot(None),
            Produk.stok_minimal > 0,
            Produk.stok_lama <= Produk.stok_minimal,
        )
        .order_by(Produk.stok_lama.asc())
        .limit(5)
        .all()
    )

    dashboard_summary = {
        "total_net_revenue": total_net_revenue,
        "total_marketplace_cost": total_marketplace_cost,
        "total_transactions": total_transactions,
        "average_ticket": average_ticket,
        "today_net_revenue": today_revenue,
        "today_transactions": today_transactions,
        "month_net_revenue": month_revenue,
        "month_transactions": month_transactions,
        "customer_count": Pelanggan.query.count(),
        "product_count": Produk.query.count(),
    }

    return render_template(
        "dashboard.html",
        username=username,
        summary=dashboard_summary,
        monthly_trend=monthly_trend,
        top_products=top_products,
        low_stock_products=low_stock_products,
    )


@bp.route("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect("/login")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(_safe_next_url())

    next_value = request.args.get("next")
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        next_value = request.form.get("next") or next_value

        # Cari pengguna di database
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            session["user_id"] = user.id
            session["username"] = user.username
            session["role"] = user.role
            session["email"] = user.email
            flash("Login successful!", "success")
            return redirect(_safe_next_url(candidate=next_value))
        else:
            flash("Invalid email or password.", "danger")

    return render_template("login.html", next=next_value)


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if session.get("user_id"):
        flash("Anda sudah masuk ke sistem.", "info")
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email_input = request.form.get("email", "").strip()
        if not email_input:
            flash("Masukkan email yang terdaftar.", "warning")
            return redirect(url_for("main.forgot_password"))

        user = User.query.filter(func.lower(User.email) == email_input.lower()).first()
        if user:
            reset_token = _create_password_reset_token(user)
            reset_link = url_for(
                "main.reset_password", token=reset_token.token, _external=True
            )
            flash(
                "Gunakan tautan berikut untuk mengatur ulang password (sementara ditampilkan untuk pengujian): "
                f"{reset_link}",
                "info",
            )
        flash("Jika email terdaftar, tautan reset password telah dikirim.", "success")
        return redirect(url_for("main.login"))

    return render_template("forgot_password.html")


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if session.get("user_id"):
        flash("Keluar dari akun terlebih dahulu untuk reset password.", "info")
        return redirect(url_for("main.dashboard"))

    reset_token = _get_valid_reset_token(token)
    if not reset_token:
        flash("Token reset password tidak valid atau sudah kedaluwarsa.", "danger")
        return redirect(url_for("main.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not password or not confirm_password:
            flash("Password dan konfirmasi wajib diisi.", "warning")
            return redirect(url_for("main.reset_password", token=token))
        if len(password) < 8:
            flash("Password minimal 8 karakter.", "warning")
            return redirect(url_for("main.reset_password", token=token))
        if password != confirm_password:
            flash("Konfirmasi password tidak cocok.", "warning")
            return redirect(url_for("main.reset_password", token=token))

        reset_token.user.password = generate_password_hash(
            password, method="pbkdf2:sha256", salt_length=8
        )
        reset_token.mark_used()
        db.session.commit()
        flash("Password berhasil diperbarui. Silakan login kembali.", "success")
        return redirect(url_for("main.login"))

    return render_template("reset_password.html", token=token)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = User.query.get(session["user_id"])

    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]

        # Update username and email
        user.username = username
        user.email = email

        # Update password if provided
        if password:
            hashed_password = generate_password_hash(
                password, method="pbkdf2:sha256", salt_length=8
            )
            user.password = hashed_password

        # Commit changes to the database
        db.session.commit()
        flash("Profile updated successfully!", "success")
        return redirect("/profile")

    return render_template("profile.html", username=user.username, email=user.email)


def _build_supplier_page_context(
    edit_supplier=None, search_query="", page=1, per_page=10
):
    base_query = Supplier.query.order_by(Supplier.name.asc())
    if search_query:
        like = f"%{search_query}%"
        base_query = base_query.filter(
            or_(
                Supplier.name.ilike(like),
                Supplier.email.ilike(like),
                Supplier.contact_person.ilike(like),
                Supplier.phone.ilike(like),
            )
        )

    pagination = base_query.paginate(page=page, per_page=per_page, error_out=False)
    suppliers = pagination.items

    total_suppliers = Supplier.query.count()
    contact_complete = Supplier.query.filter(
        Supplier.phone.isnot(None), Supplier.phone != ""
    ).count()
    email_complete = Supplier.query.filter(
        Supplier.email.isnot(None), Supplier.email != ""
    ).count()
    website_complete = Supplier.query.filter(
        Supplier.website.isnot(None), Supplier.website != ""
    ).count()
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
            "description": "Partner pemasok yang siap dihubungi.",
        },
        {
            "label": "Kontak Lengkap",
            "value": contact_complete,
            "icon": "fa-phone-alt",
            "accent": "text-success",
            "type": "count",
            "description": "Supplier dengan nomor telepon tercatat.",
        },
        {
            "label": "Punya Website",
            "value": website_complete,
            "icon": "fa-globe",
            "accent": "text-info",
            "type": "count",
            "description": "Supplier yang menyediakan alamat website.",
        },
        {
            "label": "Faktur Pembelian",
            "value": purchase_count,
            "icon": "fa-file-invoice",
            "accent": "text-warning",
            "type": "count",
            "description": "Jumlah transaksi pembelian tercatat.",
        },
    ]

    supplier_insights = [
        {
            "title": "Perlu nomor kontak",
            "value": contact_missing,
            "status": "warning" if contact_missing else "success",
            "type": "count",
            "description": "Lengkapi nomor telepon untuk respons cepat.",
        },
        {
            "title": "Perlu email",
            "value": email_missing,
            "status": "info" if email_missing else "success",
            "type": "count",
            "description": "Email memudahkan pengiriman PO dan faktur.",
        },
        {
            "title": "Memiliki website",
            "value": website_complete,
            "status": "success" if website_complete else "secondary",
            "type": "count",
            "description": "Website membantu akses katalog pemasok.",
        },
    ]

    top_supplier = (
        db.session.query(Supplier.name, func.count(Pembelian.id).label("jumlah"))
        .join(Pembelian, Pembelian.supplier_id == Supplier.id)
        .group_by(Supplier.id)
        .order_by(func.count(Pembelian.id).desc())
        .first()
    )
    if top_supplier:
        supplier_insights.append(
            {
                "title": "Partner teraktif",
                "value": top_supplier.jumlah,
                "status": "success",
                "type": "count",
                "description": f"{top_supplier.name} paling sering memasok.",
            }
        )

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
            "website": supplier.website,
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
        total_units = sum(item.jumlah or 0 for item in purchase.barang)
        total_cost = sum(item.hpp or 0.0 for item in purchase.barang)
        recent_purchases.append(
            {
                "no_faktur": purchase.no_faktur,
                "tanggal": (
                    purchase.tanggal_faktur.strftime("%d %b %Y")
                    if purchase.tanggal_faktur
                    else "-"
                ),
                "supplier": (
                    purchase.supplier.name if purchase.supplier else "Tanpa supplier"
                ),
                "items": total_units,
                "total": total_cost,
            }
        )

    return {
        "suppliers": suppliers,
        "pagination": pagination,
        "filtered_count": pagination.total,
        "page": page,
        "per_page": per_page,
        "supplier_payload": supplier_payload,
        "supplier_stat_cards": supplier_stat_cards,
        "supplier_insights": supplier_insights,
        "recent_purchases": recent_purchases,
        "search_query": search_query,
        "edit_supplier": edit_supplier,
    }


@bp.route("/supplier", methods=["GET", "POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def supplier():
    search_query = request.args.get("search", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    per_page = max(5, min(per_page, 50))

    if request.method == "POST":
        # Ambil data dari formulir
        name = request.form["name"].strip()
        address = request.form["address"].strip()
        phone = request.form["phone"].strip()
        bank_name = request.form.get("bank_name", "").strip()
        bank_account = request.form["bank_account"].strip()
        account_name = request.form["account_name"].strip()
        contact_person = request.form["contact_person"].strip()
        email_input = request.form.get("email", "").strip()
        email = email_input or None
        website = request.form["website"].strip() or None

        required_fields = {
            "Nama Supplier": name,
            "Alamat": address,
            "Nomor Telepon": phone,
            "Nama Bank": bank_name,
            "No. Rekening Bank": bank_account,
            "Nama Rekening": account_name,
            "Kontak Person": contact_person,
        }
        missing_fields = [
            label for label, value in required_fields.items() if not value
        ]
        if missing_fields:
            flash(f"Kolom berikut wajib diisi: {', '.join(missing_fields)}.", "warning")
            return redirect(url_for("main.supplier", search=search_query, page=page))

        if email:
            existing_supplier = Supplier.query.filter_by(email=email).first()
            if existing_supplier:
                flash("Email supplier sudah terdaftar.", "warning")
                return redirect(url_for("main.supplier"))

        # Simpan ke database
        new_supplier = Supplier(
            name=name,
            address=address,
            phone=phone,
            bank_name=bank_name or None,
            bank_account=bank_account,
            account_name=account_name,
            contact_person=contact_person,
            email=email,
            website=website,
        )

        db.session.add(new_supplier)
        db.session.commit()
        flash("Supplier added successfully!", "success")
        return redirect(url_for("main.supplier"))

    return render_template(
        "supplier.html",
        **_build_supplier_page_context(
            search_query=search_query, page=page, per_page=per_page
        ),
    )


@bp.route("/supplier/edit/<int:supplier_id>", methods=["GET", "POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def edit_supplier(supplier_id):
    search_query = request.args.get("search", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    per_page = max(5, min(per_page, 50))
    supplier = Supplier.query.get_or_404(supplier_id)

    if request.method == "POST":
        supplier.name = request.form["name"].strip()
        supplier.address = request.form["address"].strip()
        supplier.phone = request.form["phone"].strip()
        supplier.bank_name = request.form.get("bank_name", "").strip() or None
        supplier.bank_account = request.form["bank_account"].strip()
        supplier.account_name = request.form["account_name"].strip()
        supplier.contact_person = request.form["contact_person"].strip()
        email_input = request.form.get("email", "").strip()
        email = email_input or None
        supplier.website = request.form["website"].strip() or None

        required_fields = {
            "Nama Supplier": supplier.name,
            "Alamat": supplier.address,
            "Nomor Telepon": supplier.phone,
            "Nama Bank": supplier.bank_name,
            "No. Rekening Bank": supplier.bank_account,
            "Nama Rekening": supplier.account_name,
            "Kontak Person": supplier.contact_person,
        }
        missing_fields = [
            label for label, value in required_fields.items() if not value
        ]
        if missing_fields:
            flash(f"Kolom berikut wajib diisi: {', '.join(missing_fields)}.", "warning")
            return redirect(
                url_for(
                    "main.edit_supplier",
                    supplier_id=supplier_id,
                    search=search_query,
                    page=page,
                )
            )

        if email:
            existing = Supplier.query.filter(
                Supplier.email == email, Supplier.id != supplier.id
            ).first()
            if existing:
                flash("Email supplier sudah digunakan oleh supplier lain.", "warning")
                return redirect(url_for("main.edit_supplier", supplier_id=supplier_id))

        supplier.email = email

        db.session.commit()
        flash("Supplier updated successfully!", "success")
        return redirect(url_for("main.supplier", search=search_query, page=page))

    return render_template(
        "supplier.html",
        **_build_supplier_page_context(
            edit_supplier=supplier,
            search_query=search_query,
            page=page,
            per_page=per_page,
        ),
    )


@bp.route("/supplier/delete/<int:supplier_id>", methods=["POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def delete_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    linked_products = Produk.query.filter_by(supplier_id=supplier.id).count()
    linked_purchases = Pembelian.query.filter_by(supplier_id=supplier.id).count()
    if linked_products or linked_purchases:
        flash(
            "Supplier tidak dapat dihapus karena masih dipakai pada produk atau faktur pembelian.",
            "warning",
        )
        return redirect(url_for("main.supplier"))
    db.session.delete(supplier)
    db.session.commit()
    flash("Supplier deleted successfully!", "success")
    return redirect("/supplier")


@bp.route("/supplier/<int:supplier_id>", methods=["GET"])
@login_required
@roles_required(*INVENTORY_ROLES)
def supplier_detail(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    return render_template("supplier_detail.html", supplier=supplier)


@bp.route("/supplier/export", methods=["GET"])
@login_required
@roles_required(*INVENTORY_ROLES)
def export_suppliers():
    suppliers = Supplier.query.all()

    def _normalize_phone(value):
        if not value:
            return ""
        v = str(value).replace(" ", "").replace("-", "")
        if v.startswith("+62"):
            v = "0" + v[3:]
        elif v.startswith("62"):
            v = "0" + v[2:]
        elif not v.startswith("0"):
            v = "0" + v
        return v

    # Data untuk Excel
    data = [
        {
            "Nama Supplier": supplier.name,
            "Alamat": supplier.address,
            "No Telp": _normalize_phone(supplier.phone),
            "Nama Bank": supplier.bank_name or "",
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
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    output.seek(0)

    # Buat respons Flask
    response = make_response(output.read())
    response.headers["Content-Disposition"] = "attachment; filename=suppliers.xlsx"
    response.headers["Content-Type"] = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return response


@bp.route("/laporan/supplier", methods=["GET"])
@login_required
@roles_required(*INVENTORY_ROLES)
def laporan_supplier():
    search_query = (request.args.get("search") or "").strip()
    base_query = Supplier.query.order_by(Supplier.name.asc())
    if search_query:
        like = f"%{search_query}%"
        base_query = base_query.filter(
            or_(
                Supplier.name.ilike(like),
                Supplier.contact_person.ilike(like),
                Supplier.phone.ilike(like),
                Supplier.email.ilike(like),
                Supplier.bank_account.ilike(like),
                Supplier.bank_name.ilike(like),
            )
        )
    suppliers = base_query.all()
    total = Supplier.query.count()
    return render_template(
        "laporan_supplier.html",
        suppliers=suppliers,
        total=total,
        search_query=search_query,
    )


@bp.route("/supplier/import", methods=["POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def import_suppliers():
    if "file" not in request.files:
        flash("No file uploaded!", "danger")
        return redirect("/supplier")

    file = request.files["file"]

    if file.filename == "":
        flash("No selected file!", "danger")
        return redirect("/supplier")

    # Baca file Excel menggunakan pandas
    try:
        df = pd.read_excel(file)
    except Exception as e:
        flash(f"Error reading file: {e}", "danger")
        return redirect("/supplier")

    # Validasi kolom yang diperlukan
    required_columns = [
        "Nama Supplier",
        "Alamat",
        "No Telp",
        "Nama Bank",
        "No Rekening Bank",
        "Nama Rekening",
        "Kontak Person",
        "Email",
        "Website",
    ]
    if not all(column in df.columns for column in required_columns):
        flash("Invalid file format! Missing required columns.", "danger")
        return redirect("/supplier")

    # Simpan data ke database
    def _clean_cell(value):
        if pd.isna(value):
            return ""
        return str(value).strip()

    def _normalize_phone(value):
        value = (value or "").strip()
        if not value:
            return ""
        digits = re.sub(r"\\D", "", value)
        if digits.startswith("62"):
            digits = digits[2:]
        if not digits.startswith("0"):
            digits = "0" + digits
        return digits

    def _normalize_bank_account(value):
        value = (value or "").strip()
        if not value:
            return ""
        digits = re.sub(r"\\D", "", value)
        return digits.lstrip("0") or digits

    created_count = 0
    updated_count = 0
    skipped = 0
    existing_bank_map = {}
    for s in Supplier.query.all():
        key = _normalize_bank_account(s.bank_account)
        if key:
            existing_bank_map.setdefault(key, s)

    for _, row in df.iterrows():
        name = _clean_cell(row["Nama Supplier"])
        address = _clean_cell(row["Alamat"])
        phone_raw = _clean_cell(row["No Telp"])
        phone = _normalize_phone(phone_raw)
        bank_name = _clean_cell(row["Nama Bank"])
        bank_account = _clean_cell(row["No Rekening Bank"])
        bank_account_key = _normalize_bank_account(bank_account)
        account_name = _clean_cell(row["Nama Rekening"])
        contact_person = _clean_cell(row["Kontak Person"])
        email_value = _clean_cell(row["Email"])
        website_value = _clean_cell(row["Website"]) or None
        email = email_value or None
        phone_key = _normalize_phone(phone_raw)

        if not all([name, address, phone_key, bank_name, bank_account, account_name, contact_person]):
            flash(
                f'Data supplier "{name or "-"}" tidak lengkap dan dilewati.', "warning"
            )
            continue

        existing = None
        candidate_queries = []
        if bank_account_key and bank_account_key in existing_bank_map:
            existing = existing_bank_map[bank_account_key]
        if not existing and bank_account:
            candidate_queries.append(Supplier.query.filter_by(bank_account=bank_account))
        if email:
            candidate_queries.append(Supplier.query.filter_by(email=email))
        if phone_key:
            candidate_queries.append(Supplier.query.filter(Supplier.phone.in_([phone_key, phone_raw])))
        if name:
            candidate_queries.append(Supplier.query.filter(func.lower(Supplier.name) == name.lower()))

        for q in candidate_queries:
            if existing:
                break
            existing = q.first()

        if existing:
            existing.name = name or existing.name
            existing.address = address or existing.address
            existing.phone = phone_key or existing.phone
            existing.bank_name = bank_name or existing.bank_name
            existing.bank_account = bank_account or existing.bank_account
            existing.account_name = account_name or existing.account_name
            existing.contact_person = contact_person or existing.contact_person
            existing.email = email or existing.email
            existing.website = website_value or existing.website
            updated_count += 1
            if bank_account_key:
                existing_bank_map[bank_account_key] = existing
            continue

        supplier = Supplier(
            name=name,
            address=address,
            phone=phone_key,
            bank_name=bank_name,
            bank_account=bank_account,
            account_name=account_name,
            contact_person=contact_person,
            email=email,
            website=website_value,
        )
        db.session.add(supplier)
        if bank_account_key:
            existing_bank_map[bank_account_key] = supplier
        created_count += 1

    db.session.commit()
    message_parts = []
    if created_count:
        message_parts.append(f"{created_count} supplier baru")
    if updated_count:
        message_parts.append(f"{updated_count} supplier diupdate")
    summary = ", ".join(message_parts) if message_parts else "Tidak ada perubahan"
    flash(f"Import supplier selesai: {summary}.", "success")
    return redirect("/supplier")


# Route to fetch supplier data
@bp.route("/api/suppliers", methods=["GET"])
@login_required
@roles_required(*INVENTORY_ROLES)
def get_suppliers():
    try:
        kategori_id = request.args.get("kategori_id", type=int)
        search_term = (request.args.get("q") or "").strip().lower()
        limit = request.args.get("limit", type=int) or 10
        limit = max(1, min(limit, 30))

        query = Supplier.query
        if kategori_id:
            query = (
                query.join(Produk, Produk.supplier_id == Supplier.id)
                .filter(Produk.kategori_id == kategori_id)
                .distinct()
            )
        if search_term:
            like = f"%{search_term}%"
            query = query.filter(
                or_(
                    func.lower(Supplier.name).like(like),
                    func.lower(Supplier.contact_person).like(like),
                    func.lower(Supplier.phone).like(like),
                    func.lower(Supplier.email).like(like),
                )
            )
        suppliers = query.order_by(Supplier.name.asc()).limit(limit).all()
        suppliers_data = [
            {
                "id": supplier.id,
                "name": supplier.name,
                "contact_person": supplier.contact_person,
                "phone": supplier.phone,
                "email": supplier.email,
                "address": supplier.address,
                "website": supplier.website,
                "bank_name": supplier.bank_name,
                "bank_account": supplier.bank_account,
            }
            for supplier in suppliers
        ]
        return jsonify({"suppliers": suppliers_data}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/satuan", methods=["GET", "POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def satuan():
    if request.method == "POST":
        # Ambil data dari formulir
        name = request.form["satuan"]

        # Simpan ke database
        new_satuan = Satuan(name=name)
        db.session.add(new_satuan)
        db.session.commit()
        flash("Satuan added successfully!", "success")
        return redirect("/satuan")

    # Ambil semua data satuan untuk ditampilkan
    satuans = Satuan.query.all()
    return render_template("data_satuan.html", satuans=satuans)


@bp.route("/satuan/edit/<int:satuan_id>", methods=["GET", "POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def edit_satuan(satuan_id):
    satuan = Satuan.query.get_or_404(satuan_id)

    if request.method == "POST":
        # Ambil data dari formulir dan perbarui database
        satuan.name = request.form["satuan"]
        db.session.commit()
        flash("Satuan updated successfully!", "success")
        return redirect("/satuan")

    # Kirim data satuan ke template untuk diisi di formulir
    satuans = Satuan.query.all()
    return render_template("data_satuan.html", edit_satuan=satuan, satuans=satuans)


@bp.route("/satuan/delete/<int:satuan_id>", methods=["POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def delete_satuan(satuan_id):
    satuan = Satuan.query.get_or_404(satuan_id)
    if Produk.query.filter_by(satuan_id=satuan.id).count():
        flash(
            "Tidak dapat menghapus satuan karena masih digunakan oleh produk.",
            "warning",
        )
        return redirect(url_for("main.satuan"))
    db.session.delete(satuan)
    db.session.commit()
    flash("Satuan deleted successfully!", "success")
    return redirect("/satuan")


@bp.route("/kategori", methods=["GET", "POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def kategori():
    if request.method == "POST":
        # Ambil data dari formulir
        name = request.form["kategori"]

        # Simpan ke database
        new_kategori = Kategori(name=name)
        db.session.add(new_kategori)
        db.session.commit()
        flash("Kategori added successfully!", "success")
        return redirect("/kategori")

    # Ambil semua data kategori untuk ditampilkan
    kategoris = Kategori.query.all()
    return render_template("data_kategori.html", kategoris=kategoris)


@bp.route("/kategori/edit/<int:kategori_id>", methods=["GET", "POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def edit_kategori(kategori_id):
    kategori = Kategori.query.get_or_404(kategori_id)

    if request.method == "POST":
        # Ambil data dari formulir dan perbarui di database
        kategori.name = request.form["kategori"]
        db.session.commit()
        flash("Kategori updated successfully!", "success")
        return redirect("/kategori")

    # Kirim data kategori yang akan diedit ke template
    kategoris = Kategori.query.all()
    return render_template(
        "data_kategori.html", edit_kategori=kategori, kategoris=kategoris
    )


@bp.route("/kategori/delete/<int:kategori_id>", methods=["POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def delete_kategori(kategori_id):
    kategori = Kategori.query.get_or_404(kategori_id)
    if Produk.query.filter_by(kategori_id=kategori.id).count():
        flash(
            "Tidak dapat menghapus kategori karena masih digunakan oleh produk.",
            "warning",
        )
        return redirect(url_for("main.kategori"))
    db.session.delete(kategori)
    db.session.commit()
    flash("Kategori deleted successfully!", "success")
    return redirect("/kategori")


@bp.route("/produk", methods=["GET", "POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def produk():
    satuans = Satuan.query.all()
    kategoris = Kategori.query.all()
    suppliers = Supplier.query.all()
    price_levels = PriceLevel.query.order_by(PriceLevel.name.asc()).all()
    price_level_lookup = {level.id: level for level in price_levels}

    # Ambil parameter pencarian dan filter
    search_query = request.args.get("search", "").strip()
    kategori_filter = request.args.get("kategori", "").strip()
    supplier_filter = request.args.get("supplier", "").strip()

    # Jika pengguna mengklik tombol edit
    produk_id = request.args.get("edit")
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
            return datetime.strptime(value, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    def _shape_price_levels_for_prefill(entries):
        shaped = []
        for entry in entries or []:
            try:
                level_id = int(entry.get("level_id"))
            except (TypeError, ValueError):
                continue
            level = price_level_lookup.get(level_id)
            shaped.append(
                {
                    "level_id": level_id,
                    "level_name": level.name if level else "",
                    "price": entry.get("price", 0),
                }
            )
        return shaped

    def _store_prefill(form_data, normalized_price_entries=None, focus_field=None):
        snapshot = {
            "kode_produk": (form_data.get("kode_produk") or "").strip(),
            "sku": (form_data.get("sku") or "").strip(),
            "barcode": (form_data.get("barcode") or "").strip(),
            "nama_produk": (form_data.get("nama_produk") or "").strip(),
            "satuan": (form_data.get("satuan") or "").strip(),
            "kategori": (form_data.get("kategori") or "").strip(),
            "supplier": (form_data.get("supplier") or "").strip(),
            "berat": (form_data.get("berat") or "").strip(),
            "stok_minimal": (form_data.get("stok_minimal") or "").strip(),
            "tanggal_expired": (form_data.get("tanggal_expired") or "").strip(),
            "price_levels": _shape_price_levels_for_prefill(
                normalized_price_entries or []
            ),
        }
        session["produk_form_prefill"] = {
            "snapshot": snapshot,
            "focus_field": focus_field,
        }

    if request.method == "POST":
        if not produk_to_edit:
            produk_id_form = request.form.get("produk_id")
            if produk_id_form:
                produk_to_edit = Produk.query.get(produk_id_form)

        redirect_target = (
            url_for("main.produk", edit=produk_to_edit.id)
            if produk_to_edit
            else url_for("main.produk")
        )

        kode_produk = request.form.get("kode_produk", "").strip()
        nama_produk = request.form.get("nama_produk", "").strip()
        satuan_id = _parse_int(request.form.get("satuan"))
        kategori_id = _parse_int(request.form.get("kategori"))
        supplier_id = _parse_int(request.form.get("supplier"))
        sku = request.form.get("sku", "").strip() or None
        barcode = request.form.get("barcode", "").strip() or None
        berat = _parse_float(request.form.get("berat"))
        stok_minimal = _parse_int(request.form.get("stok_minimal"), default=0)
        tanggal_expired = _parse_date(request.form.get("tanggal_expired"))
        raw_price_payload = (request.form.get("price_level_payload") or "").strip()
        price_level_payload = []

        if raw_price_payload:
            try:
                parsed_payload = json.loads(raw_price_payload)
            except (TypeError, ValueError):
                _store_prefill(
                    request.form,
                    normalized_price_entries=[],
                    focus_field="kode_produk",
                )
                flash(
                    "Format level harga tidak valid. Muat ulang halaman lalu coba lagi.",
                    "danger",
                )
                return redirect(redirect_target)
            if isinstance(parsed_payload, list):
                price_level_payload = parsed_payload
            else:
                _store_prefill(
                    request.form,
                    normalized_price_entries=[],
                    focus_field="kode_produk",
                )
                flash("Format level harga tidak dikenali.", "danger")
                return redirect(redirect_target)

        if not price_levels:
            _store_prefill(
                request.form,
                normalized_price_entries=[],
                focus_field="kode_produk",
            )
            flash(
                "Belum ada level harga. Buat level terlebih dahulu di menu Level Harga.",
                "warning",
            )
            return redirect(redirect_target)

        normalized_price_entries = _build_price_level_entries(
            price_level_payload, price_level_lookup
        )

        if not normalized_price_entries:
            _store_prefill(
                request.form,
                normalized_price_entries=[],
                focus_field="price_level_value",
            )
            flash(
                "Tambahkan minimal satu level harga dengan nilai rupiah yang valid.",
                "warning",
            )
            return redirect(redirect_target)

        retail_level = next(
            (
                level
                for level in price_levels
                if (level.name or "").strip().lower() == "retail"
            ),
            None,
        )

        if retail_level and not any(
            entry["level_id"] == retail_level.id for entry in normalized_price_entries
        ):
            _store_prefill(
                request.form,
                normalized_price_entries=normalized_price_entries,
                focus_field="price_level_value",
            )
            flash(
                "Isi harga untuk level Retail agar dapat menjadi harga default kasir.",
                "warning",
            )
            return redirect(redirect_target)

        if (
            not kode_produk
            or not nama_produk
            or not satuan_id
            or not kategori_id
            or not supplier_id
        ):
            missing_field = None
            for field_name, value in [
                ("kode_produk", kode_produk),
                ("nama_produk", nama_produk),
                ("satuan", satuan_id),
                ("kategori", kategori_id),
                ("supplier", supplier_id),
            ]:
                if not value:
                    missing_field = field_name
                    break
            _store_prefill(
                request.form,
                normalized_price_entries=normalized_price_entries,
                focus_field=missing_field or "kode_produk",
            )
            flash("Pastikan semua field wajib diisi.", "warning")
            return redirect(url_for("main.produk"))

        try:
            if produk_to_edit:
                existing = Produk.query.filter(
                    Produk.kode_produk == kode_produk, Produk.id != produk_to_edit.id
                ).first()
                if existing:
                    _store_prefill(
                        request.form,
                        normalized_price_entries=normalized_price_entries,
                        focus_field="kode_produk",
                    )
                    flash(f"Kode produk {kode_produk} sudah digunakan.", "warning")
                    return redirect(url_for("main.produk", edit=produk_to_edit.id))

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
                _sync_product_price_levels(
                    produk_to_edit,
                    price_level_payload,
                    price_level_lookup,
                    normalized_entries=normalized_price_entries,
                )
                db.session.commit()
                session.pop("produk_form_prefill", None)
                flash("Produk updated successfully!", "success")
            else:
                existing = Produk.query.filter_by(kode_produk=kode_produk).first()
                if existing:
                    _store_prefill(
                        request.form,
                        normalized_price_entries=normalized_price_entries,
                        focus_field="kode_produk",
                    )
                    flash(f"Kode produk {kode_produk} sudah digunakan.", "warning")
                    return redirect(url_for("main.produk"))

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
                    tanggal_expired=tanggal_expired,
                )
                db.session.add(new_produk)
                db.session.flush()
                _sync_product_price_levels(
                    new_produk,
                    price_level_payload,
                    price_level_lookup,
                    normalized_entries=normalized_price_entries,
                )
                db.session.commit()
                session.pop("produk_form_prefill", None)
                flash("Produk added successfully!", "success")

        except IntegrityError as exc:
            db.session.rollback()
            _store_prefill(
                request.form,
                normalized_price_entries=normalized_price_entries,
                focus_field="kode_produk",
            )
            flash(f"Gagal menyimpan produk: {str(exc.orig)}", "danger")
        except Exception as exc:
            db.session.rollback()
            logging.exception("Gagal menyimpan produk")
            _store_prefill(
                request.form,
                normalized_price_entries=normalized_price_entries,
                focus_field="kode_produk",
            )
            flash(f"Error: {str(exc)}", "danger")

        return redirect("/produk")

    # Logika pencarian dan filter
    query = Produk.query
    if search_query:
        query = query.filter(
            or_(
                Produk.nama_produk.ilike(f"%{search_query}%"),
                Produk.kode_produk.ilike(f"%{search_query}%"),
                Produk.sku.ilike(f"%{search_query}%"),
                Produk.barcode.ilike(f"%{search_query}%"),
            )
        )
    if kategori_filter:
        query = query.filter(Produk.kategori_id == kategori_filter)
    if supplier_filter:
        query = query.filter(Produk.supplier_id == supplier_filter)

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    per_page = max(5, min(per_page, 50))

    base_query = (
        query.options(
            joinedload(Produk.satuan),
            joinedload(Produk.kategori),
            joinedload(Produk.supplier),
        )
        .order_by(Produk.nama_produk.asc())
    )
    pagination = base_query.paginate(page=page, per_page=per_page, error_out=False)
    produks = pagination.items

    product_ids = [produk.id for produk in produks]
    product_price_levels_map = defaultdict(list)
    if product_ids:
        level_rows = (
            ProductPriceLevel.query.options(
                joinedload(ProductPriceLevel.level)
            )
            .join(PriceLevel)
            .filter(ProductPriceLevel.product_id.in_(product_ids))
            .order_by(PriceLevel.name.asc())
            .all()
        )
        for row in level_rows:
            product_price_levels_map[row.product_id].append(
                {
                    "level_id": row.level_id,
                    "level_name": row.level.name if row.level else "Level",
                    "price": row.price,
                }
            )

    product_price_levels = {
        product_id: sorted(
            entries,
            key=lambda item: (item["level_name"] or "").lower(),
        )
        for product_id, entries in product_price_levels_map.items()
    }
    price_updates = {}
    if product_ids:
        try:
            _ensure_table(PriceChange)
            latest_changes = (
                PriceChange.query.filter(PriceChange.product_id.in_(product_ids))
                .order_by(PriceChange.product_id.asc(), PriceChange.created_at.desc())
                .all()
            )
            for change in latest_changes:
                if change.product_id not in price_updates:
                    price_updates[change.product_id] = {
                        "new_price": change.new_price,
                        "updated_at": change.created_at,
                        "user": change.user.username if change.user else None,
                    }
        except Exception:
            price_updates = {}

    total_produk = pagination.total
    total_kategori = len(kategoris)
    total_suppliers = len(suppliers)
    stok_threshold_missing = Produk.query.filter(
        or_(Produk.stok_minimal.is_(None), Produk.stok_minimal <= 0)
    ).count()
    expiry_tracked = Produk.query.filter(Produk.tanggal_expired.isnot(None)).count()
    no_barcode = Produk.query.filter(
        or_(Produk.barcode.is_(None), Produk.barcode == "")
    ).count()

    prefill_state = session.pop("produk_form_prefill", None)
    prefill_data = (prefill_state or {}).get("snapshot")
    focus_field = (prefill_state or {}).get("focus_field")

    edit_price_levels = []
    if prefill_data and prefill_data.get("price_levels"):
        edit_price_levels = prefill_data.get("price_levels") or []
    elif produk_to_edit:
        edit_price_levels = [
            {
                "level_id": entry.level_id,
                "level_name": entry.level.name if entry.level else "",
                "price": entry.price,
            }
            for entry in sorted(
                produk_to_edit.level_prices,
                key=lambda record: (
                    (record.level.name or "").lower() if record.level else ""
                ),
            )
        ]

    stat_cards = [
        {
            "label": "Produk Aktif",
            "value": total_produk,
            "icon": "fa-box-open",
            "accent": "text-primary",
            "description": "Item tersedia di katalog",
        },
        {
            "label": "Kategori",
            "value": total_kategori,
            "icon": "fa-tags",
            "accent": "text-success",
            "description": "Kelompok produk yang digunakan",
        },
        {
            "label": "Supplier Terhubung",
            "value": total_suppliers,
            "icon": "fa-truck",
            "accent": "text-warning",
            "description": "Relasi pemasok tersimpan",
        },
        {
            "label": "Kadaluarsa Dipantau",
            "value": expiry_tracked,
            "icon": "fa-hourglass-half",
            "accent": "text-danger",
            "description": "Produk memiliki tanggal expired",
        },
    ]

    health_insights = [
        {
            "title": "Butuh target stok",
            "value": stok_threshold_missing,
            "status": "warning" if stok_threshold_missing else "success",
            "description": "Produk belum memiliki batas stok minimal. Atur angka untuk menghindari kehabisan.",
        },
        {
            "title": "Belum ada barcode",
            "value": no_barcode,
            "status": "info" if no_barcode else "success",
            "description": "Lengkapi barcode agar proses penjualan kasir lebih cepat.",
        },
        {
            "title": "Tanggal expired tercatat",
            "value": expiry_tracked,
            "status": "success" if expiry_tracked else "secondary",
            "description": "Pantau masa kadaluarsa barang sensitif dan atur promo lebih awal.",
        },
    ]

    expiring_products = (
        Produk.query.filter(Produk.tanggal_expired.isnot(None))
        .order_by(Produk.tanggal_expired.asc())
        .limit(5)
        .all()
    )

    product_import_schema = [
        {
            "column": "Kode Produk",
            "required": True,
            "description": "Kode unik setiap barang (maks. 50 karakter).",
        },
        {"column": "SKU", "required": False, "description": "Kode internal opsional."},
        {
            "column": "Nama Produk",
            "required": True,
            "description": "Nama barang sesuai katalog.",
        },
        {
            "column": "Satuan ID",
            "required": True,
            "description": "ID dari master Data Satuan.",
        },
        {
            "column": "Kategori ID",
            "required": True,
            "description": "ID dari master Data Kategori.",
        },
        {
            "column": "Supplier ID",
            "required": True,
            "description": "ID pemasok terkait.",
        },
        {
            "column": "Berat",
            "required": False,
            "description": "Dalam kilogram, gunakan titik untuk desimal.",
        },
        {
            "column": "Stok Minimal",
            "required": False,
            "description": "Batas stok untuk peringatan restock.",
        },
        {
            "column": "Tanggal Expired",
            "required": False,
            "description": "Format YYYY-MM-DD, kosongkan jika tidak perlu.",
        },
    ]

    price_levels_context = [
        {"id": level.id, "name": level.name or "", "description": level.description or ""}
        for level in price_levels
    ]

    pagination_args = {
        key: value
        for key, value in request.args.to_dict().items()
        if key not in {"page", "ajax"}
    }
    if request.args.get("ajax") == "1":
        return render_template(
            "partials/product_table.html",
            produks=produks,
            pagination=pagination,
            pagination_args=pagination_args,
            price_updates=price_updates,
            product_price_levels=product_price_levels,
        )

    return render_template(
        "data_produk.html",
        produks=produks,
        satuans=satuans,
        kategoris=kategoris,
        suppliers=suppliers,
        price_levels=price_levels,
        price_levels_context=price_levels_context,
        stat_cards=stat_cards,
        health_insights=health_insights,
        expiring_products=expiring_products,
        edit_produk=produk_to_edit,
        edit_price_levels=edit_price_levels,
        product_price_levels=product_price_levels,
        product_import_schema=product_import_schema,
        price_updates=price_updates,
        pagination=pagination,
        page=page,
        per_page=per_page,
        pagination_args=pagination_args,
        prefill_data=prefill_data,
        focus_field=focus_field,
    )


@bp.route("/produk/<int:produk_id>/json", methods=["GET"])
@login_required
@roles_required(*ALL_ROLE_CHOICES)
def produk_data(produk_id):
    produk = (
        Produk.query.options(
            joinedload(Produk.satuan),
            joinedload(Produk.kategori),
            joinedload(Produk.supplier),
            joinedload(Produk.level_prices).joinedload(ProductPriceLevel.level),
        )
        .get_or_404(produk_id)
    )

    def _format_price_entries(entries):
        sorted_entries = sorted(
            entries,
            key=lambda record: (
                (record.level.name or "").lower() if record.level else ""
            ),
        )
        result = []
        for entry in sorted_entries:
            result.append(
                {
                    "level_id": entry.level_id,
                    "level_name": (entry.level.name if entry.level else ""),
                    "price": float(entry.price or 0),
                }
            )
        return result

    payload = {
        "id": produk.id,
        "kode_produk": produk.kode_produk,
        "sku": produk.sku,
        "barcode": produk.barcode,
        "nama_produk": produk.nama_produk,
        "satuan_id": produk.satuan_id,
        "kategori_id": produk.kategori_id,
        "supplier_id": produk.supplier_id,
        "berat": float(produk.berat) if produk.berat is not None else None,
        "stok_minimal": produk.stok_minimal,
        "tanggal_expired": produk.tanggal_expired.strftime("%Y-%m-%d")
        if produk.tanggal_expired
        else None,
        "price_levels": _format_price_entries(produk.level_prices),
    }
    return jsonify(payload)


@bp.route("/akun", methods=["GET", "POST"])
@login_required
@roles_required(*ADMIN_ONLY)
def akun():
    _ensure_table(Account)
    if request.method == "POST":
        code = (request.form.get("code") or "").strip().upper()
        name = (request.form.get("name") or "").strip()
        acc_type = (request.form.get("type") or "").strip().lower()
        parent_id = request.form.get("parent_id")
        is_active = request.form.get("is_active", "1") == "1"

        valid_types = {"asset", "liability", "equity", "income", "expense"}
        if not code or not name or acc_type not in valid_types:
            flash("Kode, nama, dan tipe akun wajib diisi.", "warning")
            return redirect(url_for("main.akun"))
        if Account.query.filter_by(code=code).first():
            flash(f"Kode akun {code} sudah digunakan.", "warning")
            return redirect(url_for("main.akun"))

        parent = None
        if parent_id:
            try:
                parent = Account.query.get(int(parent_id))
            except (TypeError, ValueError):
                parent = None

        account = Account(
            code=code,
            name=name,
            type=acc_type,
            parent=parent,
            is_active=is_active,
        )
        db.session.add(account)
        db.session.commit()
        flash("Akun berhasil ditambahkan.", "success")
        return redirect(url_for("main.akun"))

    accounts = Account.query.order_by(Account.code.asc()).all()
    type_labels = {
        "asset": "Aset",
        "liability": "Liabilitas",
        "equity": "Ekuitas",
        "income": "Pendapatan",
        "expense": "Beban",
    }
    summary = defaultdict(int)
    for account in accounts:
        summary[account.type] += 1

    summary_cards = [
        {
            "label": type_labels.get(acc_type, acc_type.title()),
            "value": summary.get(acc_type, 0),
            "icon": icon,
            "accent": accent,
        }
        for acc_type, icon, accent in [
            ("asset", "fa-piggy-bank", "text-primary"),
            ("liability", "fa-balance-scale", "text-warning"),
            ("equity", "fa-university", "text-success"),
            ("income", "fa-chart-line", "text-info"),
            ("expense", "fa-receipt", "text-danger"),
        ]
    ]

    return render_template(
        "akun.html",
        accounts=accounts,
        summary_cards=summary_cards,
        type_labels=type_labels,
    )


@bp.route("/pengaturan-akuntansi", methods=["GET", "POST"])
@login_required
@roles_required(*ADMIN_ONLY)
def accounting_settings():
    _ensure_table(AccountingSetting)
    accounts = Account.query.order_by(Account.code.asc()).all()
    settings = _get_accounting_setting()
    auto_filter = JournalEntry.memo.ilike("Auto COGS%")

    if request.method == "POST":
        inventory_account_id = _parse_int_param(request.form.get("inventory_account"))
        cogs_account_id = _parse_int_param(request.form.get("cogs_account"))
        errors = []

        if inventory_account_id:
            if not Account.query.get(inventory_account_id):
                errors.append("Akun persediaan tidak ditemukan.")

        if cogs_account_id:
            if not Account.query.get(cogs_account_id):
                errors.append("Akun COGS tidak ditemukan.")

        if errors:
            for message in errors:
                flash(message, "warning")
            return redirect(url_for("main.accounting_settings"))

        if not settings:
            settings = AccountingSetting()

        settings.inventory_account_id = inventory_account_id
        settings.cogs_account_id = cogs_account_id
        settings.updated_by = session.get("user_id")
        settings.updated_at = datetime.utcnow()

        db.session.add(settings)
        db.session.commit()
        flash("Pengaturan COGS otomatis berhasil disimpan.", "success")
        return redirect(url_for("main.accounting_settings"))

    auto_count = JournalEntry.query.filter(auto_filter).count()
    auto_total_amount = (
        db.session.query(func.coalesce(func.sum(JournalLine.debit), 0))
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .filter(auto_filter)
        .scalar()
        or 0.0
    )
    recent_entries = (
        JournalEntry.query.options(joinedload(JournalEntry.lines).joinedload(JournalLine.account))
        .filter(auto_filter)
        .order_by(JournalEntry.date.desc(), JournalEntry.id.desc())
        .limit(5)
        .all()
    )
    recent_auto = [
        {
            "reference": entry.reference,
            "date_label": _format_date_id(entry.date),
            "memo": entry.memo or "Auto COGS",
            "amount": sum(line.debit for line in entry.lines),
        }
        for entry in recent_entries
    ]

    return render_template(
        "accounting_settings.html",
        accounts=accounts,
        settings=settings,
        auto_total_amount=auto_total_amount,
        auto_count=auto_count,
        recent_auto=recent_auto,
    )


@bp.route("/tutup-buku", methods=["GET", "POST"])
@login_required
@roles_required(*ADMIN_ONLY)
def close_books():
    today = datetime.utcnow().date()
    open_period = (
        AccountingPeriod.query.filter_by(status="open")
        .order_by(AccountingPeriod.start_date.desc())
        .first()
    )
    if open_period:
        default_start = open_period.start_date
        default_end = open_period.end_date
    else:
        first_day = today.replace(day=1)
        prev_month_end = first_day - timedelta(days=1)
        default_start = prev_month_end.replace(day=1)
        default_end = prev_month_end

    start_date = _parse_date_param(request.args.get("start_date")) or default_start
    end_date = _parse_date_param(request.args.get("end_date")) or default_end
    summary = _build_period_metrics(start_date, end_date)

    open_periods = (
        AccountingPeriod.query.filter(AccountingPeriod.status == "open")
        .order_by(AccountingPeriod.start_date.desc())
        .all()
    )
    recent_closed = (
        AccountingPeriod.query.filter(AccountingPeriod.status == "closed")
        .order_by(AccountingPeriod.closed_at.desc())
        .limit(5)
        .all()
    )

    warning_message = None
    if summary and summary["difference"] != 0:
        warning_message = (
            f"Rekonsiliasi menunjukkan selisih Rp "
            f"{('{:,.0f}'.format(abs(summary['difference']))).replace(',', '.')} "
            f"antara nilai persediaan dan HPP."
        )

    if request.method == "POST":
        label = (request.form.get("label") or "").strip()
        description = (request.form.get("description") or "").strip()
        form_start = _parse_date_param(request.form.get("start_date"))
        form_end = _parse_date_param(request.form.get("end_date"))
        if not form_start or not form_end:
            flash("Tanggal awal dan akhir periode wajib diisi.", "warning")
        else:
            try:
                _close_accounting_period(label, form_start, form_end, session.get("user_id"), description or None)
                db.session.commit()
                flash(f"Periode {label or form_start.strftime('%b %Y')} berhasil ditutup.", "success")
                return redirect(
                    url_for(
                        "main.close_books",
                        start_date=form_start.strftime("%Y-%m-%d"),
                        end_date=form_end.strftime("%Y-%m-%d"),
                    )
                )
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "warning")
            except Exception as exc:
                db.session.rollback()
                logging.exception("Gagal menutup periode")
                flash(f"Gagal menutup periode: {str(exc)}", "danger")
        start_date = form_start or start_date
        end_date = form_end or end_date
        summary = _build_period_metrics(start_date, end_date)
        if summary and summary["difference"] != 0:
            warning_message = (
                f"Rekonsiliasi menunjukkan selisih Rp "
                f"{('{:,.0f}'.format(abs(summary['difference']))).replace(',', '.')} "
                f"antara nilai persediaan dan HPP."
            )

    selected_range = {
        "start_date": start_date.strftime("%Y-%m-%d") if start_date else "",
        "end_date": end_date.strftime("%Y-%m-%d") if end_date else "",
    }

    return render_template(
        "accounting_close.html",
        open_periods=open_periods,
        recent_closed=recent_closed,
        summary=summary,
        selected_range=selected_range,
        warning_message=warning_message,
    )


@bp.route("/status", methods=["GET"])
@login_required
@roles_required(*ADMIN_ONLY)
def status():
    metrics = _collect_system_metrics()
    return render_template("server_status.html", metrics=metrics)


@bp.route("/jurnal", methods=["GET", "POST"])
@login_required
@roles_required(*ADMIN_ONLY)
def jurnal():
    _ensure_table(Account)
    _ensure_table(JournalEntry)
    _ensure_table(JournalLine)

    if request.method == "POST":
        if not request.is_json:
            return jsonify({"success": False, "message": "Gunakan JSON payload."}), 415
        payload = request.get_json(silent=True) or {}
        lines = payload.get("lines") or []
        if not lines or len(lines) < 2:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Minimal dua baris jurnal (debit/kredit).",
                    }
                ),
                400,
            )

        date_value = _parse_date_param(payload.get("date")) or datetime.utcnow().date()
        memo = (payload.get("memo") or "").strip()
        reference = (
            payload.get("reference") or ""
        ).strip() or _generate_journal_reference()

        total_debit = 0.0
        total_credit = 0.0
        parsed_lines = []
        for idx, raw in enumerate(lines, start=1):
            account_id = raw.get("account_id")
            description = (raw.get("description") or "").strip()
            try:
                account_id = int(account_id)
            except (TypeError, ValueError):
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"Akun tidak valid (baris {idx}).",
                        }
                    ),
                    400,
                )
            account = Account.query.get(account_id)
            if not account:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"Akun ID {account_id} tidak ditemukan (baris {idx}).",
                        }
                    ),
                    400,
                )
            try:
                debit = float(raw.get("debit") or 0.0)
                credit = float(raw.get("credit") or 0.0)
            except (TypeError, ValueError):
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"Nominal tidak valid (baris {idx}).",
                        }
                    ),
                    400,
                )
            if debit < 0 or credit < 0:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"Debit/kredit tidak boleh negatif (baris {idx}).",
                        }
                    ),
                    400,
                )
            if debit == 0 and credit == 0:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"Isi salah satu debit/kredit (baris {idx}).",
                        }
                    ),
                    400,
                )
            if debit > 0 and credit > 0:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"Debit dan kredit tidak boleh diisi bersamaan (baris {idx}).",
                        }
                    ),
                    400,
                )

            total_debit += debit
            total_credit += credit
            parsed_lines.append(
                {
                    "account": account,
                    "description": description,
                    "debit": debit,
                    "credit": credit,
                }
            )

        if round(total_debit, 2) != round(total_credit, 2):
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Total debit dan kredit harus seimbang.",
                    }
                ),
                400,
            )

        entry = JournalEntry(
            reference=reference,
            date=date_value,
            memo=memo or None,
            created_by=session.get("user_id"),
        )
        db.session.add(entry)
        db.session.flush()

        for line in parsed_lines:
            db.session.add(
                JournalLine(
                    entry_id=entry.id,
                    account_id=line["account"].id,
                    description=line["description"] or None,
                    debit=line["debit"],
                    credit=line["credit"],
                )
            )
        db.session.commit()
        return jsonify(
            {
                "success": True,
                "message": "Jurnal berhasil disimpan.",
                "reference": reference,
            }
        )

    accounts = Account.query.order_by(Account.code.asc()).all()
    accounts_for_js = [
        {
            "id": account.id,
            "code": account.code,
            "name": account.name,
        }
        for account in accounts
    ]
    recent_entries = (
        JournalEntry.query.options(
            joinedload(JournalEntry.lines).joinedload(JournalLine.account)
        )
        .order_by(JournalEntry.date.desc(), JournalEntry.id.desc())
        .limit(10)
        .all()
    )
    net_expr = Penjualan.total_harga - func.coalesce(Penjualan.marketplace_cost_total, 0)
    total_net_revenue = (
        db.session.query(func.coalesce(func.sum(net_expr), 0)).scalar() or 0.0
    )
    total_marketplace_cost = (
        db.session.query(func.coalesce(func.sum(Penjualan.marketplace_cost_total), 0)).scalar()
        or 0.0
    )

    return render_template(
        "jurnal.html",
        accounts=accounts,
        accounts_for_js=accounts_for_js,
        recent_entries=recent_entries,
        default_date=datetime.utcnow().date().strftime("%Y-%m-%d"),
        net_revenue_total=total_net_revenue,
        marketplace_cost_total=total_marketplace_cost,
    )


@bp.route("/produk/edit/<int:produk_id>", methods=["GET", "POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def edit_produk(produk_id):
    produk = Produk.query.get_or_404(produk_id)

    if request.method == "POST":
        produk.kode_produk = request.form["kode_produk"]
        produk.barcode = request.form["barcode"]
        produk.nama_produk = request.form["nama_produk"]
        produk.satuan_id = request.form["satuan"]
        produk.kategori_id = request.form["kategori"]
        produk.supplier_id = request.form["supplier"]
        produk.berat = float(request.form["berat"]) if request.form["berat"] else None
        produk.stok_minimal = (
            int(request.form["stok_minimal"]) if request.form["stok_minimal"] else None
        )
        produk.tanggal_expired = (
            request.form["tanggal_expired"] if request.form["tanggal_expired"] else None
        )

        db.session.commit()
        flash("Produk updated successfully!", "success")
        return redirect("/produk")

    satuans = Satuan.query.all()
    kategoris = Kategori.query.all()
    suppliers = Supplier.query.all()
    return render_template(
        "edit_produk.html",
        produk=produk,
        satuans=satuans,
        kategoris=kategoris,
        suppliers=suppliers,
    )


@bp.route("/produk/delete/<int:produk_id>", methods=["POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def delete_produk(produk_id):
    produk = Produk.query.get_or_404(produk_id)
    try:
        db.session.delete(produk)
        db.session.commit()
        flash("Produk deleted successfully!", "success")
    except IntegrityError as exc:
        db.session.rollback()
        flash(
            "Produk tidak dapat dihapus karena masih memiliki relasi transaksi.",
            "warning",
        )
    except Exception as exc:
        db.session.rollback()
        logging.exception("Gagal menghapus produk")
        flash(f"Gagal menghapus produk: {str(exc)}", "danger")
    return redirect("/produk")


@bp.route("/produk/detail/<int:produk_id>", methods=["GET"])
@login_required
@roles_required(*ALL_ROLE_CHOICES)
def detail_produk(produk_id):
    produk = Produk.query.get_or_404(produk_id)
    return render_template("detail_produk.html", produk=produk)


@bp.route("/produk/export", methods=["GET"])
@login_required
@roles_required(*INVENTORY_ROLES)
def export_produk():
    produks = Produk.query.all()

    data = [
        {
            "Kode Produk": produk.kode_produk,
            "SKU": produk.sku or "",
            "Nama Produk": produk.nama_produk,
            "Satuan ID": produk.satuan_id,
            "Kategori ID": produk.kategori_id,
            "Supplier ID": produk.supplier_id,
            "Berat": produk.berat or "",
            "Stok Minimal": produk.stok_minimal or 0,
            "Tanggal Expired": (
                produk.tanggal_expired.strftime("%Y-%m-%d")
                if produk.tanggal_expired
                else ""
            ),
        }
        for produk in produks
    ]

    df = pd.DataFrame(data)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    output.seek(0)

    response = make_response(output.read())
    response.headers["Content-Disposition"] = "attachment; filename=produk.xlsx"
    response.headers["Content-Type"] = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return response


@bp.route("/produk/import", methods=["POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def import_produk():
    if "file" not in request.files:
        flash("Tidak ada file yang diunggah!", "danger")
        return redirect("/produk")

    file = request.files["file"]

    if file.filename == "":
        flash("File tidak dipilih!", "danger")
        return redirect("/produk")

    file_bytes = file.read()

    def build_summary_message(summary):
        status_parts = []
        if summary.get("created"):
            status_parts.append(f"{summary['created']} produk baru ditambahkan")
        if summary.get("updated"):
            status_parts.append(f"{summary['updated']} produk diperbarui")
        if not status_parts:
            status_parts.append("Tidak ada perubahan dari file import")
        return "; ".join(status_parts)

    def warn_skipped(summary):
        skipped_notes = summary.get("skipped_notes") or []
        if skipped_notes:
            detail = "; ".join(skipped_notes[:5])
            if len(skipped_notes) > 5:
                detail += f"; dan {len(skipped_notes) - 5} baris lainnya."
            return detail
        return None

    try:
        df = pd.read_excel(BytesIO(file_bytes))
    except Exception as e:
        flash(f"Gagal membaca file: {e}", "danger")
        return redirect("/produk")

    try:
        summary = _perform_produk_import(df)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect("/produk")
    except Exception as exc:
        db.session.rollback()
        logging.exception("Gagal import produk")
        flash(f"Gagal menyimpan data produk: {exc}", "danger")
        return redirect("/produk")

    flash(build_summary_message(summary), "success")
    skipped_detail = warn_skipped(summary)
    if skipped_detail:
        flash(f"Beberapa baris dilewati: {skipped_detail}", "warning")

    return redirect("/produk")


def _build_customer_page_context(
    edit_pelanggan=None, search_query="", page=1, per_page=10
):
    price_levels = PriceLevel.query.order_by(PriceLevel.name.asc()).all()
    filtered_query = Pelanggan.query.order_by(Pelanggan.id.desc())
    if search_query:
        like_pattern = f"%{search_query}%"
        filtered_query = filtered_query.filter(
            or_(
                Pelanggan.nama.ilike(like_pattern),
                Pelanggan.pelanggan_id.ilike(like_pattern),
                Pelanggan.kontak.ilike(like_pattern),
            )
        )

    pagination = filtered_query.paginate(page=page, per_page=per_page, error_out=False)
    pelanggans = pagination.items

    total_customers = Pelanggan.query.count()
    complete_contacts = Pelanggan.query.filter(
        Pelanggan.kontak.isnot(None), Pelanggan.kontak != ""
    ).count()
    complete_addresses = Pelanggan.query.filter(
        Pelanggan.alamat.isnot(None), Pelanggan.alamat != ""
    ).count()
    missing_contact = total_customers - complete_contacts
    missing_address = total_customers - complete_addresses

    unique_contacts = (
        db.session.query(func.count(func.distinct(func.lower(Pelanggan.kontak))))
        .filter(Pelanggan.kontak.isnot(None), Pelanggan.kontak != "")
        .scalar()
        or 0
    )
    duplicate_contacts = max(0, complete_contacts - unique_contacts)

    contact_completion = (
        int(round((complete_contacts / total_customers) * 100))
        if total_customers
        else 0
    )
    address_completion = (
        int(round((complete_addresses / total_customers) * 100))
        if total_customers
        else 0
    )

    stat_cards = [
        {
            "label": "Total Pelanggan",
            "value": total_customers,
            "icon": "fa-users",
            "accent": "text-primary",
            "description": "Relasi aktif tersimpan",
        },
        {
            "label": "Kontak Lengkap",
            "value": complete_contacts,
            "icon": "fa-phone-alt",
            "accent": "text-success",
            "description": f"{contact_completion}% siap dihubungi",
        },
        {
            "label": "Alamat Tercatat",
            "value": complete_addresses,
            "icon": "fa-map-marker-alt",
            "accent": "text-info",
            "description": f"{address_completion}% siap dikunjungi",
        },
        {
            "label": "Perlu Kontak",
            "value": missing_contact,
            "icon": "fa-user-clock",
            "accent": "text-warning",
            "description": "Lengkapi agar mudah follow-up",
        },
    ]

    insights = [
        {
            "title": "Pelanggan tanpa kontak",
            "value": missing_contact,
            "status": "warning" if missing_contact else "success",
            "description": "Tambahkan nomor telepon agar mudah dihubungi.",
        },
        {
            "title": "Pelanggan tanpa alamat",
            "value": missing_address,
            "status": "info" if missing_address else "success",
            "description": "Alamat penting untuk pengiriman dan layanan purna jual.",
        },
        {
            "title": "Kontak duplikat",
            "value": duplicate_contacts,
            "status": "secondary" if duplicate_contacts == 0 else "warning",
            "description": "Gunakan data unik supaya kampanye marketing lebih akurat.",
        },
    ]

    next_customer_id = Pelanggan.generate_pelanggan_id()
    recent_customers = Pelanggan.query.order_by(Pelanggan.id.desc()).limit(5).all()

    return {
        "pelanggans": pelanggans,
        "pagination": pagination,
        "filtered_count": pagination.total,
        "page": page,
        "per_page": per_page,
        "stat_cards": stat_cards,
        "insights": insights,
        "recent_customers": recent_customers,
        "contact_completion": contact_completion,
        "address_completion": address_completion,
        "next_customer_id": next_customer_id,
        "edit_pelanggan": edit_pelanggan,
        "search_query": search_query,
        "total_customers": total_customers,
        "price_levels": price_levels,
    }


@bp.route("/pelanggan", methods=["GET", "POST"])
@login_required
@roles_required(*SALES_ROLES)
def pelanggan():
    search_query = request.args.get("search", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    per_page = max(5, min(per_page, 50))

    if request.method == "POST":
        # Gunakan generate_pelanggan_id jika pelanggan_id tidak diisi
        pelanggan_id = (
            request.form.get("pelanggan_id") or Pelanggan.generate_pelanggan_id()
        )
        nama = request.form["nama"].strip()
        kontak = request.form["kontak"].strip()
        alamat = request.form["alamat"].strip()
        price_level_raw = request.form.get("price_level_id")
        price_level_obj = None
        if price_level_raw not in (None, "", "0"):
            try:
                price_level_obj = PriceLevel.query.get(int(price_level_raw))
            except (TypeError, ValueError):
                price_level_obj = None

        required_fields = {"Nama Pelanggan": nama, "Kontak": kontak, "Alamat": alamat}
        missing_fields = [
            label for label, value in required_fields.items() if not value
        ]
        if missing_fields:
            flash(f"Kolom berikut wajib diisi: {', '.join(missing_fields)}.", "warning")
            return redirect(url_for("main.pelanggan", search=search_query, page=page))

        # Tambahkan pelanggan baru
        new_pelanggan = Pelanggan(
            pelanggan_id=pelanggan_id,
            nama=nama,
            kontak=kontak,
            alamat=alamat,
            price_level=price_level_obj,
        )
        db.session.add(new_pelanggan)
        db.session.commit()
        flash("Pelanggan added successfully!", "success")
        return redirect(url_for("main.pelanggan"))

    return render_template(
        "data_pelanggan.html",
        **_build_customer_page_context(
            search_query=search_query, page=page, per_page=per_page
        ),
    )


@bp.route("/pelanggan/edit/<int:pelanggan_id>", methods=["GET", "POST"])
@login_required
@roles_required(*SALES_ROLES)
def edit_pelanggan(pelanggan_id):
    search_query = request.args.get("search", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    per_page = max(5, min(per_page, 50))
    pelanggan = Pelanggan.query.get_or_404(pelanggan_id)

    if request.method == "POST":
        nama = request.form["nama"].strip()
        kontak = request.form["kontak"].strip()
        alamat = request.form["alamat"].strip()
        price_level_raw = request.form.get("price_level_id")
        price_level_obj = None
        if price_level_raw not in (None, "", "0"):
            try:
                price_level_obj = PriceLevel.query.get(int(price_level_raw))
            except (TypeError, ValueError):
                price_level_obj = None

        if not nama or not kontak or not alamat:
            flash("Nama, kontak, dan alamat wajib diisi.", "warning")
            return redirect(
                url_for(
                    "main.edit_pelanggan",
                    pelanggan_id=pelanggan_id,
                    search=search_query,
                    page=page,
                )
            )

        pelanggan.nama = nama
        pelanggan.kontak = kontak
        pelanggan.alamat = alamat
        pelanggan.price_level = price_level_obj
        db.session.commit()
        flash(f"Pelanggan {pelanggan.nama} updated successfully!", "success")
        return redirect(url_for("main.pelanggan", search=search_query, page=page))

    return render_template(
        "data_pelanggan.html",
        **_build_customer_page_context(
            edit_pelanggan=pelanggan,
            search_query=search_query,
            page=page,
            per_page=per_page,
        ),
    )


@bp.route("/pelanggan/delete/<int:pelanggan_id>", methods=["POST"])
@login_required
@roles_required(*SALES_ROLES)
def delete_pelanggan(pelanggan_id):
    pelanggan = Pelanggan.query.get_or_404(pelanggan_id)
    if Penjualan.query.filter_by(pelanggan_id=pelanggan.id).count():
        flash(
            "Pelanggan masih memiliki riwayat transaksi dan tidak dapat dihapus.",
            "warning",
        )
        return redirect("/pelanggan")
    pelanggan_name = pelanggan.nama  # Simpan nama pelanggan untuk pesan flash
    db.session.delete(pelanggan)
    db.session.commit()
    flash(f"Pelanggan {pelanggan_name} deleted successfully!", "success")
    return redirect("/pelanggan")


@bp.route("/api/get_product", methods=["GET"])
@login_required
@roles_required(*ALL_ROLE_CHOICES)
def get_product():
    product_code = request.args.get("product_code")
    product = Produk.query.filter_by(kode_produk=product_code).first()

    if product:
        return {
            "success": True,
            "product_name": product.nama_produk,
            "category": product.kategori.name,
            "satuan": product.satuan.name,
        }
    else:
        return {"success": False, "message": "Produk tidak ditemukan."}, 404


@bp.route("/api/products", methods=["GET"])
@login_required
@roles_required(*ALL_ROLE_CHOICES)
def get_products():
    search_query = request.args.get("q", "").strip()
    products = Produk.query.options(
        joinedload(Produk.kategori), joinedload(Produk.satuan)
    )

    if search_query:
        products = products.filter(
            or_(
                Produk.nama_produk.ilike(f"%{search_query}%"),
                Produk.kode_produk.ilike(f"%{search_query}%"),
                Produk.sku.ilike(f"%{search_query}%"),
                Produk.barcode.ilike(f"%{search_query}%"),
            )
        )

    products = products.limit(50).all()  # Batasi jumlah hasil untuk performa
    product_ids = [prod.id for prod in products]

    level_entries = []
    if product_ids:
        level_entries = (
            ProductPriceLevel.query.options(joinedload(ProductPriceLevel.level))
            .filter(ProductPriceLevel.product_id.in_(product_ids))
            .all()
        )

    price_map = {}
    for entry in level_entries:
        price_map.setdefault(entry.product_id, []).append(
            {
                "level_id": entry.level_id,
                "level_name": entry.level.name if entry.level else "",
                "price": entry.price,
            }
        )

    product_list = []
    for product in products:
        product_list.append(
            {
                "id": product.id,
                "kode_produk": product.kode_produk,
                "nama_produk": product.nama_produk,
                "sku": product.sku,
                "barcode": product.barcode,
                "kategori": (
                    product.kategori.name if product.kategori else "Tidak dikategorikan"
                ),
                "satuan": product.satuan.name if product.satuan else "",
                "price_levels": sorted(
                    price_map.get(product.id, []),
                    key=lambda item: (item.get("level_name") or "").lower(),
                ),
            }
        )

    return {"products": product_list}


@bp.route("/api/pelanggan/suggest", methods=["GET"])
@login_required
@roles_required(*SALES_ROLES)
def pelanggan_suggest():
    term = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 8, type=int)
    page = max(1, page)
    per_page = max(5, min(per_page, 20))

    if not term:
        return {
            "customers": [],
            "page": page,
            "per_page": per_page,
            "total": 0,
            "has_next": False,
        }

    like = f"%{term}%"
    base_query = (
        Pelanggan.query.options(joinedload(Pelanggan.price_level))
        .filter(
            or_(
                Pelanggan.nama.ilike(like),
                Pelanggan.pelanggan_id.ilike(like),
                Pelanggan.kontak.ilike(like),
            )
        )
        .order_by(Pelanggan.nama.asc())
    )
    pagination = base_query.paginate(page=page, per_page=per_page, error_out=False)
    customers = pagination.items

    payload = [
        {
            "id": customer.id,
            "pelanggan_id": customer.pelanggan_id,
            "nama": customer.nama,
            "kontak": customer.kontak,
            "price_level": customer.price_level.name if customer.price_level else "",
        }
        for customer in customers
    ]
    return {
        "customers": payload,
        "page": page,
        "per_page": per_page,
        "total": pagination.total,
        "has_next": bool(pagination.has_next),
    }


@bp.route("/api/price_level_costs", methods=["GET"])
@login_required
@roles_required(*INVENTORY_ROLES)
def get_price_level_costs():
    level_id = request.args.get("level_id")
    try:
        level_id_int = int(level_id)
    except (TypeError, ValueError):
        return {"costs": []}

    costs = (
        PriceLevelCost.query.filter_by(level_id=level_id_int, is_active=True)
        .order_by(PriceLevelCost.name.asc())
        .all()
    )
    payload = [
        {
            "id": cost.id,
            "name": cost.name,
            "type": cost.type,
            "value": cost.value,
        }
        for cost in costs
    ]
    return {"costs": payload}


@bp.route("/pembelian", methods=["GET", "POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def pembelian():
    if request.method == "POST":
        try:
            if not request.is_json:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "Content-Type harus 'application/json'",
                        }
                    ),
                    415,
                )

            payload = request.get_json(silent=True) or {}

            tanggal_faktur = payload.get("tanggal_faktur")
            no_faktur = (payload.get("no_faktur") or "").strip()
            supplier_id = payload.get("supplier")
            items = payload.get("items") or []
            jenis_pembayaran = (payload.get("jenis_pembayaran") or "Tunai").strip()
            allowed_payments = {"Tunai", "Tempo", "Transfer"}

            if not tanggal_faktur or not no_faktur or not supplier_id:
                return (
                    jsonify({"success": False, "message": "Data utama tidak lengkap."}),
                    400,
                )

            if jenis_pembayaran not in allowed_payments:
                return (
                    jsonify(
                        {"success": False, "message": "Jenis pembayaran tidak valid."}
                    ),
                    400,
                )

            if Pembelian.query.filter_by(no_faktur=no_faktur).first():
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"Nomor faktur {no_faktur} sudah ada.",
                        }
                    ),
                    400,
                )

            parsed_date = None
            try:
                parsed_date = datetime.strptime(tanggal_faktur, "%Y-%m-%d").date()
            except ValueError:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "Format tanggal faktur tidak valid.",
                        }
                    ),
                    400,
                )

            try:
                supplier_id = int(supplier_id)
            except (TypeError, ValueError):
                return (
                    jsonify({"success": False, "message": "Supplier tidak valid."}),
                    400,
                )

            supplier = Supplier.query.get(supplier_id)
            if not supplier:
                return (
                    jsonify({"success": False, "message": "Supplier tidak ditemukan."}),
                    404,
                )

            locked_period_for_purchase = _get_locked_period_for_date(parsed_date)
            if locked_period_for_purchase:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"Periode {locked_period_for_purchase.label} sudah ditutup; tidak bisa menyimpan pembelian.",
                        }
                    ),
                    400,
                )

            if not items:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "Tidak ada data barang yang dikirim.",
                        }
                    ),
                    400,
                )

            valid_items = []
            errors = []

            for index, item in enumerate(items, start=1):
                kode_barang = (item.get("kode_barang") or "").strip()
                nama_barang = (item.get("nama_barang") or "").strip()
                kategori = (item.get("kategori") or "").strip()

                try:
                    jumlah = int(item.get("jumlah") or 0)
                except (TypeError, ValueError):
                    jumlah = 0

                try:
                    harga_beli = float(item.get("harga_beli") or 0.0)
                except (TypeError, ValueError):
                    harga_beli = 0.0

                try:
                    diskon = float(item.get("diskon") or 0.0)
                except (TypeError, ValueError):
                    diskon = 0.0

                try:
                    pajak = float(item.get("pajak") or 0.0)
                except (TypeError, ValueError):
                    pajak = 0.0

                try:
                    harga_jual = float(item.get("harga_jual") or 0.0)
                except (TypeError, ValueError):
                    harga_jual = 0.0

                exp_date_raw = item.get("exp_date")
                exp_date = None
                if exp_date_raw:
                    try:
                        exp_date = datetime.strptime(exp_date_raw, "%Y-%m-%d")
                    except ValueError:
                        errors.append(f"Tanggal exp tidak valid pada baris {index}.")

                if not kode_barang or not nama_barang or not kategori:
                    errors.append(
                        f"Kode, nama, dan kategori wajib diisi (baris {index})."
                    )
                    continue

                if jumlah <= 0:
                    errors.append(f"Jumlah harus lebih dari 0 (baris {index}).")
                    continue

                diskon = max(0.0, min(diskon, 100.0))
                pajak = max(0.0, pajak)

                discount_amount = harga_beli * (diskon / 100.0)
                net_cost = max(harga_beli - discount_amount, 0.0)
                tax_amount = net_cost * (pajak / 100.0)
                harga_final = net_cost + tax_amount
                total_hpp = net_cost * jumlah  # HPP tanpa memasukkan pajak

                produk = Produk.query.filter_by(kode_produk=kode_barang).first()
                if not produk:
                    errors.append(
                        f"Produk dengan kode {kode_barang} tidak ditemukan (baris {index})."
                    )
                    continue

                valid_items.append(
                    {
                        "kode_barang": kode_barang,
                        "nama_barang": nama_barang,
                        "kategori": kategori,
                        "jumlah": jumlah,
                        "harga_beli": harga_beli,
                        "diskon": diskon,
                        "pajak": pajak,
                        "harga_jual": harga_jual,
                        "exp_date": exp_date,
                        "harga_final": harga_final,  # tetap simpan harga akhir termasuk pajak bila perlu dilaporkan
                        "total_hpp": total_hpp,
                        "produk": produk,
                        "cost_basis": net_cost,
                    }
                )

            if errors:
                return jsonify({"success": False, "message": " ".join(errors)}), 400

            if not valid_items:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "Tidak ada baris barang yang valid.",
                        }
                    ),
                    400,
                )

            pembelian = Pembelian(
                tanggal_faktur=parsed_date,
                no_faktur=no_faktur,
                supplier_id=supplier_id,
                jenis_pembayaran=jenis_pembayaran,
            )
            db.session.add(pembelian)
            db.session.flush()

            total_pembelian = 0.0
            total_items = 0

            for item in valid_items:
                produk = item["produk"]
                if produk:
                    produk.update_stok_dan_hpp(item["cost_basis"], item["jumlah"])

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
                    hpp=item["total_hpp"],
                )
                total_pembelian += item["total_hpp"]
                total_items += item["jumlah"]
                db.session.add(barang_pembelian)

            db.session.commit()

            return (
                jsonify(
                    {
                        "success": True,
                        "message": "Pembelian berhasil disimpan!",
                        "total_biaya": total_pembelian,
                        "total_barang": total_items,
                    }
                ),
                200,
            )

        except Exception as exc:
            db.session.rollback()
            logging.exception("Gagal menyimpan pembelian")
            return jsonify({"success": False, "message": f"Error: {str(exc)}"}), 500

    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    supplier_payload = [
        {
            "id": supplier.id,
            "name": supplier.name,
            "contact_person": supplier.contact_person,
            "phone": supplier.phone,
            "email": supplier.email,
            "address": supplier.address,
        }
        for supplier in suppliers
    ]

    supplier_lookup = {supplier["id"]: supplier for supplier in supplier_payload}

    produk_records = Produk.query.order_by(Produk.nama_produk.asc()).all()
    level_price_entries_penjualan = ProductPriceLevel.query.all()
    level_price_map = {}
    for entry in level_price_entries_penjualan:
        level_price_map.setdefault(entry.product_id, {})[entry.level_id] = float(
            entry.price or 0.0
        )
    price_levels = PriceLevel.query.order_by(PriceLevel.name.asc()).all()
    product_payload = [
        {
            "id": produk.id,
            "kode": produk.kode_produk,
            "nama": produk.nama_produk,
            "kategori": produk.kategori.name if produk.kategori else None,
            "harga_beli": float(produk.harga_beli or 0.0),
            "harga_jual": float(produk.harga or 0.0),
            "sku": produk.sku,
            "supplier": produk.supplier.name if produk.supplier else None,
            "satuan": produk.satuan.name if produk.satuan else None,
            "stok": produk.stok_lama,
            "stok_minimal": produk.stok_minimal,
        }
        for produk in produk_records
    ]

    total_invoices = Pembelian.query.count()
    total_spent = (
        db.session.query(func.coalesce(func.sum(BarangPembelian.hpp), 0)).scalar()
        or 0.0
    )
    total_items = (
        db.session.query(func.coalesce(func.sum(BarangPembelian.jumlah), 0)).scalar()
        or 0
    )
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
            "description": "Jumlah transaksi pembelian tersimpan.",
        },
        {
            "label": "Total Pengeluaran",
            "value": total_spent,
            "icon": "fa-coins",
            "accent": "text-success",
            "type": "currency",
            "description": "Akumulasi biaya restock.",
        },
        {
            "label": "Faktur Hari Ini",
            "value": today_invoices,
            "icon": "fa-calendar-day",
            "accent": "text-info",
            "type": "count",
            "description": "Restock yang tercatat hari ini.",
        },
        {
            "label": "Rata-rata Faktur",
            "value": average_invoice,
            "icon": "fa-chart-bar",
            "accent": "text-warning",
            "type": "currency",
            "description": "Nilai rata-rata per transaksi pembelian.",
        },
    ]

    purchase_insights = [
        {
            "title": "Total barang masuk",
            "value": total_items,
            "status": "info" if total_items else "secondary",
            "type": "count",
            "description": "Jumlah unit yang direstock dari seluruh faktur.",
        },
        {
            "title": "Supplier aktif",
            "value": len(suppliers),
            "status": "success" if suppliers else "secondary",
            "type": "count",
            "description": "Partner pemasok yang siap memenuhi restock.",
        },
        {
            "title": "Pengeluaran rata-rata",
            "value": average_invoice,
            "status": "warning" if average_invoice else "secondary",
            "type": "currency",
            "description": "Gunakan sebagai acuan budgeting pembelian.",
        },
    ]

    upcoming_expiry = (
        BarangPembelian.query.filter(BarangPembelian.exp_date.isnot(None))
        .order_by(BarangPembelian.exp_date.asc())
        .limit(5)
        .all()
    )
    if upcoming_expiry:
        earliest = upcoming_expiry[0]
        purchase_insights.append(
            {
                "title": "Produk mendekati kadaluarsa",
                "value": (
                    earliest.exp_date.strftime("%d %b %Y") if earliest.exp_date else "-"
                ),
                "status": "warning",
                "type": "text",
                "description": f"{earliest.nama_barang} perlu diprioritaskan.",
            }
        )

    recent_purchases = []
    recent_query = (
        Pembelian.query.order_by(Pembelian.tanggal_faktur.desc(), Pembelian.id.desc())
        .limit(5)
        .all()
    )
    for purchase in recent_query:
        total_cost = sum(barang.hpp for barang in purchase.barang)
        total_units = sum(barang.jumlah for barang in purchase.barang)
        recent_purchases.append(
            {
                "no_faktur": purchase.no_faktur,
                "tanggal": (
                    purchase.tanggal_faktur.strftime("%d %b %Y")
                    if purchase.tanggal_faktur
                    else "-"
                ),
                "supplier": (
                    purchase.supplier.name if purchase.supplier else "Tanpa supplier"
                ),
                "total": total_cost,
                "items": total_units,
            }
        )

    return render_template(
        "pembelian.html",
        supplier_payload=supplier_payload,
        supplier_lookup=supplier_lookup,
        product_payload=product_payload,
        purchase_stat_cards=purchase_stat_cards,
        purchase_insights=purchase_insights,
        recent_purchases=recent_purchases,
    )


@bp.route("/check_no_faktur", methods=["POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def check_no_faktur():
    try:
        # Pastikan request dalam format JSON
        if not request.is_json:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Content-Type harus 'application/json'",
                    }
                ),
                415,
            )

        # Ambil data dari request
        data = request.json
        no_faktur = data.get("no_faktur")

        if not no_faktur:
            return (
                jsonify({"success": False, "message": "Nomor faktur tidak diberikan."}),
                400,
            )

        # Cek apakah nomor faktur sudah ada
        existing_pembelian = Pembelian.query.filter_by(no_faktur=no_faktur).first()
        if existing_pembelian:
            return (
                jsonify(
                    {
                        "success": True,
                        "available": False,
                        "exists": True,
                        "message": f"Nomor faktur {no_faktur} sudah ada.",
                    }
                ),
                200,
            )

        # Jika tidak ada
        return (
            jsonify(
                {
                    "success": True,
                    "available": True,
                    "exists": False,
                    "message": "Nomor faktur tersedia.",
                }
            ),
            200,
        )

    except Exception as e:
        print("Error:", str(e))
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500


@bp.route("/penjualan", methods=["GET", "POST"])
@login_required
@roles_required(*SALES_ROLES)
def penjualan():
    form = SalesForm()

    pelanggan_records = Pelanggan.query.order_by(Pelanggan.nama.asc()).all()
    form.pelanggan_id.choices = [(0, "Pilih pelanggan")] + [
        (p.id, f"{p.nama} ({p.pelanggan_id})") for p in pelanggan_records
    ]
    if form.pelanggan_id.data is None:
        form.pelanggan_id.data = 0

    produk_records = Produk.query.order_by(Produk.nama_produk.asc()).all()
    level_price_entries_penjualan = ProductPriceLevel.query.all()
    level_price_map = {}
    for entry in level_price_entries_penjualan:
        level_price_map.setdefault(entry.product_id, {})[entry.level_id] = float(
            entry.price or 0.0
        )
    produk_payload = [
        {
            "id": produk.id,
            "name": produk.nama_produk,
            "code": produk.kode_produk,
            "price": float(produk.harga or 0.0),
            "sku": produk.sku,
            "kategori": produk.kategori.name if produk.kategori else None,
            "level_prices": level_price_map.get(produk.id, {}),
            "stok": produk.stok_lama,
            "stok_minimal": produk.stok_minimal,
            "hpp": float(produk.harga_lama or produk.harga_beli or 0.0),
            "last_cost": float(produk.harga_beli or 0.0),
            "harga_beli": float(produk.harga_beli or 0.0),
        }
        for produk in produk_records
    ]

    settings = _get_accounting_setting()

    customer_lookup = {
        pelanggan.id: {
            "name": pelanggan.nama,
            "code": pelanggan.pelanggan_id,
            "kontak": pelanggan.kontak,
            "alamat": pelanggan.alamat,
            "price_level_id": pelanggan.price_level_id,
            "price_level_name": (
                pelanggan.price_level.name if pelanggan.price_level else None
            ),
        }
        for pelanggan in pelanggan_records
    }

    # Load available price levels for use in the sales UI (if needed)
    price_levels = PriceLevel.query.order_by(PriceLevel.name.asc()).all()

    total_orders = Penjualan.query.count()
    total_revenue = (
        db.session.query(func.coalesce(func.sum(Penjualan.total_harga), 0)).scalar()
        or 0.0
    )
    items_sold = (
        db.session.query(func.coalesce(func.sum(DetailPenjualan.jumlah), 0)).scalar()
        or 0
    )
    today = datetime.utcnow().date()
    today_orders = Penjualan.query.filter(Penjualan.tanggal_penjualan == today).count()
    average_order = total_revenue / total_orders if total_orders else 0.0

    sale_date_display = _format_date_id(today)
    draft_invoice = f"F{datetime.utcnow().strftime('%Y%m%d%H%M')}"
    sales_operator = session.get("username") or "Sales"

    sales_stat_cards = [
        {
            "label": "Total Transaksi",
            "value": total_orders,
            "icon": "fa-receipt",
            "accent": "text-primary",
            "type": "count",
            "description": "Jumlah penjualan tercatat.",
        },
        {
            "label": "Pendapatan",
            "value": total_revenue,
            "icon": "fa-wallet",
            "accent": "text-success",
            "type": "currency",
            "description": "Akumulasi nilai transaksi.",
        },
        {
            "label": "Rata-rata Order",
            "value": average_order,
            "icon": "fa-chart-line",
            "accent": "text-info",
            "type": "currency",
            "description": "Nilai rata-rata per transaksi.",
        },
        {
            "label": "Transaksi Hari Ini",
            "value": today_orders,
            "icon": "fa-calendar-day",
            "accent": "text-warning",
            "type": "count",
            "description": "Order yang tercatat pada tanggal ini.",
        },
    ]

    sales_insights = [
        {
            "title": "Unit terjual",
            "value": items_sold,
            "status": "warning" if items_sold else "secondary",
            "type": "count",
            "description": "Akumulasi kuantitas produk di seluruh transaksi.",
        },
        {
            "title": "Transaksi hari ini",
            "value": today_orders,
            "status": "info" if today_orders else "secondary",
            "type": "count",
            "description": "Pantau aktivitas penjualan harian.",
        },
        {
            "title": "Rata-rata order",
            "value": average_order,
            "status": "success" if average_order else "secondary",
            "type": "currency",
            "description": "Indikasi nilai order rata-rata pelanggan.",
        },
    ]

    top_customer = (
        db.session.query(Pelanggan.nama, func.count(Penjualan.id).label("jumlah"))
        .join(Penjualan, Penjualan.pelanggan_id == Pelanggan.id)
        .group_by(Pelanggan.id)
        .order_by(func.count(Penjualan.id).desc())
        .first()
    )
    if top_customer:
        sales_insights.append(
            {
                "title": "Pelanggan teraktif",
                "value": top_customer.jumlah,
                "status": "success",
                "type": "count",
                "description": f"{top_customer.nama} paling sering bertransaksi.",
            }
        )

    recent_sales_query = (
        Penjualan.query.order_by(
            Penjualan.tanggal_penjualan.desc(), Penjualan.id.desc()
        )
        .limit(5)
        .all()
    )
    recent_sales = [
        {
            "no_faktur": sale.no_faktur,
            "tanggal": (
                sale.tanggal_penjualan.strftime("%d %b %Y")
                if sale.tanggal_penjualan
                else "-"
            ),
            "pelanggan": sale.pelanggan.nama if sale.pelanggan else "Umum",
            "total": float(sale.total_harga or 0.0),
            "items": sum(detail.jumlah for detail in sale.detail_penjualan),
        }
        for sale in recent_sales_query
    ]

    if form.validate_on_submit():
        try:
            sales_id = session.get("user_id")
            if not sales_id:
                raise ValueError("Silakan login sebelum mencatat penjualan.")

            if not form.pelanggan_id.data or form.pelanggan_id.data == 0:
                raise ValueError("Pilih pelanggan sebelum menyimpan transaksi.")

            customer_exists = Pelanggan.query.get(form.pelanggan_id.data)
            if not customer_exists:
                raise ValueError("Pelanggan tidak ditemukan. Pilih pelanggan yang valid.")

            locked_period = _get_locked_period_for_date(today)
            if locked_period:
                raise ValueError(
                    f"Periode {locked_period.label} sudah ditutup; tidak bisa mencatat penjualan baru."
                )

            produk_id_list = request.form.getlist("produk_id[]")
            jumlah_list = request.form.getlist("jumlah[]")
            harga_list = request.form.getlist("harga[]")
            diskon_list = request.form.getlist("diskon[]")
            pajak_list = request.form.getlist("pajak[]")

            line_items = []
            errors = []
            reserved_stock = defaultdict(int)

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
                    errors.append(
                        f"Produk dengan ID {product_id} tidak ditemukan (baris {idx + 1})."
                    )
                    continue

                available_stock = (product.stok_lama or 0) - reserved_stock[product.id]
                if available_stock < 0:
                    available_stock = 0

                qty_raw = jumlah_list[idx] if idx < len(jumlah_list) else ""
                price_raw = harga_list[idx] if idx < len(harga_list) else ""
                diskon_raw = diskon_list[idx] if idx < len(diskon_list) else ""
                pajak_raw = pajak_list[idx] if idx < len(pajak_list) else ""

                try:
                    qty = int(qty_raw)
                except (TypeError, ValueError):
                    qty = 0

                if qty <= 0:
                    errors.append(
                        f"Jumlah harus lebih dari 0 untuk {product.nama_produk}."
                    )
                    continue

                if qty > available_stock:
                    errors.append(
                        f"Stok {product.nama_produk} tidak mencukupi. Sisa {available_stock}, diminta {qty}."
                    )
                    continue

                try:
                    price = (
                        float(price_raw)
                        if price_raw not in (None, "")
                        else float(product.harga or 0.0)
                    )
                except (TypeError, ValueError):
                    price = float(product.harga or 0.0)

                try:
                    discount = (
                        float(diskon_raw) if diskon_raw not in (None, "") else 0.0
                    )
                except (TypeError, ValueError):
                    discount = 0.0

                try:
                    tax = float(pajak_raw) if pajak_raw not in (None, "") else 0.0
                except (TypeError, ValueError):
                    tax = 0.0

                discount = max(0.0, min(discount, 100.0))
                tax = max(0.0, tax)

                base_total = price * qty
                discount_amount = base_total * (discount / 100.0)
                taxable_base = base_total - discount_amount
                tax_amount = taxable_base * (tax / 100.0)
                line_total = taxable_base + tax_amount

                line_items.append(
                    {
                        "product": product,
                        "qty": qty,
                        "price": price,
                        "discount": discount,
                        "tax": tax,
                        "line_total": line_total,
                        "stock_before": available_stock,
                    }
                )
                reserved_stock[product.id] += qty

            if errors:
                raise ValueError(" ".join(errors))

            if not line_items:
                raise ValueError("Tambahkan minimal satu produk dengan jumlah valid.")

            hpp_total = _calculate_line_items_hpp(line_items)
            if hpp_total <= 0:
                hpp_total = 0.0

            price_level_id_raw = request.form.get("price_level_id")
            marketplace_cost_total_raw = request.form.get("marketplace_cost_total", "0")
            marketplace_cost_details_raw = request.form.get("marketplace_cost_details", "[]")
            try:
                price_level_id_value = int(price_level_id_raw)
            except (TypeError, ValueError):
                price_level_id_value = None
            try:
                marketplace_cost_total_value = float(marketplace_cost_total_raw)
            except (TypeError, ValueError):
                marketplace_cost_total_value = 0.0
            marketplace_cost_details_value = (
                marketplace_cost_details_raw
                if isinstance(marketplace_cost_details_raw, str)
                else str(marketplace_cost_details_raw)
            )
            if not marketplace_cost_details_value:
                marketplace_cost_details_value = "[]"

            penjualan = Penjualan(
                sales_id=sales_id,
                pelanggan_id=form.pelanggan_id.data,
                total_harga=0.0,
                price_level_id=price_level_id_value,
                marketplace_cost_total=marketplace_cost_total_value,
                marketplace_cost_details=marketplace_cost_details_value,
            )
            penjualan.no_faktur = _generate_invoice_number()
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
                    harga_total=item["line_total"],
                )
                penjualan.total_harga += item["line_total"]
                current_stock = item["product"].stok_lama or 0
                item["product"].stok_lama = max(0, current_stock - item["qty"])
                db.session.add(detail)

            if (
                settings
                and settings.inventory_account_id
                and settings.cogs_account_id
                and hpp_total > 0
            ):
                _record_auto_cogs_journal(
                    penjualan,
                    hpp_total,
                    settings,
                    user_id=sales_id,
                )

            db.session.commit()
            flash(
                f"Penjualan berhasil disimpan (total Rp {penjualan.total_harga:,.0f}).",
                "success",
            )
            return redirect(url_for("main.penjualan"))

        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
        except Exception as e:
            db.session.rollback()
            logging.exception("Gagal menyimpan penjualan")
            flash(f"Error: {str(e)}", "danger")

    return render_template(
        "penjualan.html",
        form=form,
        produk_list=produk_records,
        produk_payload=produk_payload,
        sales_stat_cards=sales_stat_cards,
        sales_insights=sales_insights,
        recent_sales=recent_sales,
        customer_lookup=customer_lookup,
        sales_operator=sales_operator,
        draft_invoice=draft_invoice,
        sale_date_display=sale_date_display,
        price_levels=price_levels,
    )


@bp.route("/data_penjualan")
@login_required
@roles_required(*SALES_ROLES)
def data_penjualan():
    filter_payload = _build_sales_filters(request.args)
    filters = filter_payload["filters"]
    sort_option = request.args.get("sort", "date_desc")
    per_page = request.args.get("per_page", type=int) or 10
    per_page = max(5, min(per_page, 50))
    page = request.args.get("page", type=int) or 1
    if page < 1:
        page = 1

    def apply_filters(query):
        return query.filter(*filters) if filters else query

    def build_filtered_query(base_query):
        return base_query.filter(*filters) if filters else base_query

    net_expr = Penjualan.total_harga - func.coalesce(Penjualan.marketplace_cost_total, 0)
    sort_map = {
        "date_asc": Penjualan.tanggal_penjualan.asc(),
        "date_desc": Penjualan.tanggal_penjualan.desc(),
        "total_asc": net_expr.asc(),
        "total_desc": net_expr.desc(),
    }
    order_clause = sort_map.get(sort_option, Penjualan.tanggal_penjualan.desc())

    total_records = (
        apply_filters(db.session.query(func.count(Penjualan.id))).scalar() or 0
    )
    total_pages = max(1, (total_records + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * per_page

    base_query = apply_filters(
        Penjualan.query.options(
            joinedload(Penjualan.pelanggan),
            joinedload(Penjualan.sales),
            joinedload(Penjualan.detail_penjualan).joinedload(DetailPenjualan.produk),
        )
    )

    penjualan_records = (
        base_query.order_by(order_clause, Penjualan.id.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    total_revenue = (
        apply_filters(
            db.session.query(func.coalesce(func.sum(net_expr), 0))
        ).scalar()
        or 0.0
    )
    average_order = total_revenue / total_records if total_records else 0.0
    items_sold = (
        apply_filters(
            db.session.query(func.coalesce(func.sum(DetailPenjualan.jumlah), 0)).join(
                Penjualan, DetailPenjualan.penjualan_id == Penjualan.id
            )
        ).scalar()
        or 0
    )
    distinct_customers = (
        apply_filters(
            db.session.query(func.count(func.distinct(Penjualan.pelanggan_id)))
        ).scalar()
        or 0
    )
    total_marketplace_costs = (
        apply_filters(
            db.session.query(func.coalesce(func.sum(Penjualan.marketplace_cost_total), 0))
        ).scalar()
        or 0.0
    )
    today = datetime.utcnow().date()
    today_revenue = (
        apply_filters(
            db.session.query(func.coalesce(func.sum(net_expr), 0))
        )
        .filter(Penjualan.tanggal_penjualan == today)
        .scalar()
        or 0.0
    )

    net_sum_sales = func.coalesce(func.sum(net_expr), 0).label("total")
    top_sales_raw = (
        build_filtered_query(
            db.session.query(
                User.username.label("name"),
                func.count(Penjualan.id).label("orders"),
                net_sum_sales,
            )
            .join(User, Penjualan.sales_id == User.id)
            .group_by(User.id)
            .order_by(net_sum_sales.desc())
        )
        .limit(5)
        .all()
    )
    net_sum_customers = func.coalesce(func.sum(net_expr), 0).label("total")
    top_customers_raw = (
        build_filtered_query(
            db.session.query(
                Pelanggan.nama.label("name"),
                func.count(Penjualan.id).label("orders"),
                net_sum_customers,
            )
            .join(Pelanggan, Penjualan.pelanggan_id == Pelanggan.id)
            .group_by(Pelanggan.id)
            .order_by(net_sum_customers.desc())
        )
        .limit(5)
        .all()
    )
    top_products_raw = (
        build_filtered_query(
            db.session.query(
                Produk.nama_produk.label("name"),
                func.sum(DetailPenjualan.jumlah).label("qty"),
                func.coalesce(func.sum(DetailPenjualan.harga_total), 0).label("total"),
            )
            .join(DetailPenjualan, DetailPenjualan.produk_id == Produk.id)
            .join(Penjualan, DetailPenjualan.penjualan_id == Penjualan.id)
            .group_by(Produk.id)
            .order_by(func.sum(DetailPenjualan.jumlah).desc())
        )
        .limit(5)
        .all()
    )
    daily_summary_raw = (
        build_filtered_query(
            db.session.query(
                Penjualan.tanggal_penjualan.label("date"),
                func.count(Penjualan.id).label("orders"),
                func.coalesce(func.sum(net_expr), 0).label("total"),
            )
            .group_by(Penjualan.tanggal_penjualan)
            .order_by(Penjualan.tanggal_penjualan.desc())
        )
        .limit(7)
        .all()
    )

    top_sales = [
        {"name": row.name, "orders": row.orders, "total": row.total}
        for row in top_sales_raw
    ]
    top_customers = [
        {"name": row.name, "orders": row.orders, "total": row.total}
        for row in top_customers_raw
    ]
    top_products = [
        {"name": row.name, "qty": row.qty, "total": row.total}
        for row in top_products_raw
    ]
    daily_summary = [
        {
            "date": row.date,
            "label": _format_date_id(row.date),
            "orders": row.orders,
            "total": row.total,
        }
        for row in daily_summary_raw
    ]

    filter_active = any(
        [
            filter_payload["search_query"],
            filter_payload["pelanggan_id"],
            filter_payload["sales_id"],
            filter_payload["start_date"],
            filter_payload["end_date"],
            filter_payload["min_total"] is not None,
            filter_payload["max_total"] is not None,
        ]
    )

    def _date_value_to_str(value):
        return value.strftime("%Y-%m-%d") if value else ""

    filter_values = {
        "search": filter_payload["search_query"],
        "pelanggan": filter_payload["pelanggan_id"] or "",
        "sales": filter_payload["sales_id"] or "",
        "start_date": _date_value_to_str(filter_payload["start_date"]),
        "end_date": _date_value_to_str(filter_payload["end_date"]),
        "min_total": (
            filter_payload["min_total"]
            if filter_payload["min_total"] is not None
            else ""
        ),
        "max_total": (
            filter_payload["max_total"]
            if filter_payload["max_total"] is not None
            else ""
        ),
    }

    if filter_payload["start_date"] and filter_payload["end_date"]:
        range_label = f"{_format_date_id(filter_payload['start_date'])} - {_format_date_id(filter_payload['end_date'])}"
    elif filter_payload["start_date"]:
        range_label = f"Mulai {_format_date_id(filter_payload['start_date'])}"
    elif filter_payload["end_date"]:
        range_label = f"Sampai {_format_date_id(filter_payload['end_date'])}"
    else:
        range_label = "Semua tanggal"

    stats_cards = [
        {
            "label": "Pendapatan Bersih",
            "value": total_revenue,
            "icon": "fa-wallet",
            "accent": "text-success",
            "type": "currency",
            "description": "Setelah biaya marketplace.",
        },
        {
            "label": "Biaya Marketplace",
            "value": total_marketplace_costs,
            "icon": "fa-coins",
            "accent": "text-danger",
            "type": "currency",
            "description": "Komisi, cashback, dan bebas ongkir.",
        },
        {
            "label": "Rata-rata Order",
            "value": average_order,
            "icon": "fa-divide",
            "accent": "text-info",
            "type": "currency",
            "description": "Nilai rata-rata per faktur.",
        },
        {
            "label": "Item Terjual",
            "value": items_sold,
            "icon": "fa-cubes",
            "accent": "text-warning",
            "description": "Akumulasi kuantitas produk.",
        },
    ]

    insight_cards = [
        {
            "title": "Pelanggan unik",
            "value": distinct_customers,
            "description": "Jumlah pelanggan berbeda dalam hasil filter.",
        },
        {
            "title": "Pendapatan hari ini",
            "value": today_revenue,
            "type": "currency",
            "description": "Nilai bersih transaksi hari ini.",
        },
        {
            "title": "Rentang tanggal",
            "value": range_label,
            "type": "text",
            "description": "Periode data yang sedang dianalisis.",
        },
    ]

    sales_options = User.query.order_by(User.username.asc()).all()
    customer_options = Pelanggan.query.order_by(Pelanggan.nama.asc()).all()

    query_args = request.args.to_dict(flat=True)
    query_args.pop("page", None)
    base_args = query_args.copy()

    prev_url = (
        url_for("main.data_penjualan", page=page - 1, **base_args) if page > 1 else None
    )
    next_url = (
        url_for("main.data_penjualan", page=page + 1, **base_args)
        if page < total_pages
        else None
    )

    page_window_start = max(1, page - 2)
    page_window_end = min(total_pages, page + 2)
    page_links = [
        {
            "number": number,
            "url": url_for("main.data_penjualan", page=number, **base_args),
            "current": number == page,
        }
        for number in range(page_window_start, page_window_end + 1)
    ]
    pagination = {
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "total_records": total_records,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "base_args": base_args,
        "prev_url": prev_url,
        "next_url": next_url,
        "page_links": page_links,
    }

    return render_template(
        "data_penjualan.html",
        penjualan_records=penjualan_records,
        stats_cards=stats_cards,
        insight_cards=insight_cards,
        top_sales=top_sales,
        top_customers=top_customers,
        top_products=top_products,
        daily_summary=daily_summary,
        filter_values=filter_values,
        sort_option=sort_option,
        per_page=per_page,
        pagination=pagination,
        filter_active=filter_active,
        sales_options=sales_options,
        customer_options=customer_options,
        format_date=_format_date_id,
    )


@bp.route("/laporan/laba-rugi")
@login_required
@roles_required(*ADMIN_ONLY)
def laporan_laba_rugi():
    today = datetime.utcnow().date()
    default_start = today.replace(day=1)
    start_date = _parse_date_param(request.args.get("start_date")) or default_start
    end_date = _parse_date_param(request.args.get("end_date")) or today
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    sales_records = (
        Penjualan.query.options(
            joinedload(Penjualan.detail_penjualan).joinedload(DetailPenjualan.produk)
        )
        .filter(Penjualan.tanggal_penjualan >= start_date)
        .filter(Penjualan.tanggal_penjualan <= end_date)
        .order_by(Penjualan.tanggal_penjualan.asc())
        .all()
    )

    totals = {
        "revenue": 0.0,
        "cogs": 0.0,
        "gross": 0.0,
        "discount": 0.0,
        "tax": 0.0,
        "marketplace_costs": 0.0,
        "orders": len(sales_records),
        "units": 0,
    }
    daily_map = defaultdict(lambda: {"revenue": 0.0, "gross": 0.0})
    monthly_map = defaultdict(lambda: {"revenue": 0.0, "gross": 0.0})
    product_map = defaultdict(
        lambda: {"name": "Produk dihapus", "units": 0, "revenue": 0.0, "gross": 0.0}
    )

    for sale in sales_records:
        sale_date = sale.tanggal_penjualan or today
        month_key = (sale_date.year, sale_date.month)
        invoice_revenue = 0.0
        for detail in sale.detail_penjualan:
            qty = detail.jumlah or 0
            price = detail.harga_satuan or 0.0
            discount_pct = detail.diskon or 0.0
            tax_pct = detail.pajak or 0.0
            base_amount = price * qty
            discount_value = base_amount * (discount_pct / 100.0)
            taxable = base_amount - discount_value
            tax_value = taxable * (tax_pct / 100.0)
            product_cost = 0.0
            if detail.produk:
                product_cost = (
                    detail.produk.harga_lama
                    or detail.produk.harga_beli
                    or detail.produk.harga
                    or 0.0
                )
            cost_value = product_cost * qty
            gross_value = taxable - cost_value

            totals["units"] += qty
            totals["revenue"] += taxable
            totals["discount"] += discount_value
            totals["tax"] += tax_value
            totals["cogs"] += cost_value
            totals["gross"] += gross_value

            invoice_revenue += taxable

            daily_map[sale_date]["revenue"] += taxable
            daily_map[sale_date]["gross"] += gross_value
            monthly_map[month_key]["revenue"] += taxable
            monthly_map[month_key]["gross"] += gross_value

            product_key = detail.produk.id if detail.produk else f"detail-{detail.id}"
            if detail.produk:
                product_map[product_key]["name"] = detail.produk.nama_produk
            product_map[product_key]["units"] += qty
            product_map[product_key]["revenue"] += taxable
            product_map[product_key]["gross"] += gross_value

        cost_total = float(sale.marketplace_cost_total or 0.0)
        totals["marketplace_costs"] += cost_total
        totals["revenue"] -= cost_total
        daily_map[sale_date]["revenue"] -= cost_total
        monthly_map[month_key]["revenue"] -= cost_total

    margin_percent = (
        (totals["gross"] / totals["revenue"]) * 100 if totals["revenue"] else 0.0
    )
    average_order = totals["revenue"] / totals["orders"] if totals["orders"] else 0.0

    daily_points = [
        {
            "date": date_key.isoformat(),
            "label": _format_date_id(date_key),
            "revenue": round(values["revenue"], 2),
            "gross": round(values["gross"], 2),
        }
        for date_key, values in sorted(daily_map.items())
    ]

    monthly_breakdown = [
        {
            "label": datetime(year=year, month=month, day=1).strftime("%b %Y"),
            "revenue": values["revenue"],
            "gross": values["gross"],
        }
        for (year, month), values in sorted(monthly_map.items())
    ]

    top_products = sorted(
        product_map.values(), key=lambda item: item["gross"], reverse=True
    )[:5]

    summary_cards = [
        {
            "label": "Penjualan Bersih",
            "value": totals["revenue"],
            "icon": "fa-coins",
            "accent": "text-primary",
            "subtitle": "Setelah diskon & biaya marketplace",
        },
        {
            "label": "Biaya Marketplace",
            "value": totals["marketplace_costs"],
            "icon": "fa-coins",
            "accent": "text-danger",
            "subtitle": "Komisi, cashback, bebas ongkir",
        },
        {
            "label": "HPP",
            "value": totals["cogs"],
            "icon": "fa-boxes",
            "accent": "text-secondary",
            "subtitle": "Total biaya barang",
        },
        {
            "label": "Laba Kotor",
            "value": totals["gross"],
            "icon": "fa-chart-line",
            "accent": "text-success",
            "subtitle": f"Margin {margin_percent:.1f}%",
        },
        {
            "label": "Pajak Dipungut",
            "value": totals["tax"],
            "icon": "fa-file-invoice-dollar",
            "accent": "text-info",
            "subtitle": "Belum disetor",
        },
    ]

    insight_cards = [
        {
            "title": "Rata-rata Order",
            "value": average_order,
            "type": "currency",
            "description": "Nilai penjualan bersih per transaksi.",
        },
        {
            "title": "Total Transaksi",
            "value": totals["orders"],
            "type": "count",
            "description": "Jumlah faktur pada periode ini.",
        },
        {
            "title": "Item Terjual",
            "value": totals["units"],
            "type": "count",
            "description": "Agregasi kuantitas dari seluruh penjualan.",
        },
        {
            "title": "Diskon Diberikan",
            "value": totals["discount"],
            "type": "currency",
            "description": "Total nilai potongan harga.",
        },
    ]

    range_label = f"{_format_date_id(start_date)} - {_format_date_id(end_date)}"
    filter_values = {
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
    }

    return render_template(
        "laporan_laba_rugi.html",
        summary_cards=summary_cards,
        insight_cards=insight_cards,
        top_products=top_products,
        daily_points=daily_points,
        monthly_breakdown=monthly_breakdown,
        totals=totals,
        margin_percent=margin_percent,
        average_order=average_order,
        range_label=range_label,
        filter_values=filter_values,
    )


@bp.route("/laporan/pembelian")
@login_required
@roles_required(*INVENTORY_ROLES)
def laporan_pembelian():
    today = datetime.utcnow().date()
    default_start = today.replace(day=1)
    start_date = _parse_date_param(request.args.get("start_date")) or default_start
    end_date = _parse_date_param(request.args.get("end_date")) or today
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    purchase_query = (
        Pembelian.query.options(
            joinedload(Pembelian.barang),
            joinedload(Pembelian.supplier),
        )
        .filter(Pembelian.tanggal_faktur >= start_date)
        .filter(Pembelian.tanggal_faktur <= end_date)
        .order_by(Pembelian.tanggal_faktur.asc(), Pembelian.id.asc())
    )
    purchase_records = purchase_query.all()

    totals = {
        "spend": 0.0,
        "discount": 0.0,
        "tax": 0.0,
        "units": 0,
        "invoices": len(purchase_records),
    }
    daily_map = defaultdict(lambda: {"spent": 0.0, "units": 0})
    monthly_map = defaultdict(lambda: {"spent": 0.0, "units": 0})
    supplier_map = defaultdict(
        lambda: {"name": "Tanpa supplier", "spent": 0.0, "units": 0, "invoices": 0}
    )

    largest_invoice = {"amount": 0.0, "supplier": "Tanpa supplier", "date": "-"}

    for purchase in purchase_records:
        invoice_total = 0.0
        invoice_units = 0
        invoice_date = purchase.tanggal_faktur or today
        month_key = (invoice_date.year, invoice_date.month)

        for item in purchase.barang:
            qty = item.jumlah or 0
            unit_price = item.harga_beli or 0.0
            discount_pct = item.diskon or 0.0
            tax_pct = item.pajak or 0.0

            base_total = unit_price * qty
            discount_value = base_total * (discount_pct / 100.0)
            taxable_total = base_total - discount_value
            tax_value = taxable_total * (tax_pct / 100.0)
            final_total = taxable_total + tax_value

            totals["spend"] += final_total
            totals["discount"] += discount_value
            totals["tax"] += tax_value
            totals["units"] += qty

            invoice_total += final_total
            invoice_units += qty

        daily_map[invoice_date]["spent"] += invoice_total
        daily_map[invoice_date]["units"] += invoice_units
        monthly_map[month_key]["spent"] += invoice_total
        monthly_map[month_key]["units"] += invoice_units

        supplier_key = purchase.supplier_id or f"anon-{purchase.id}"
        supplier_entry = supplier_map[supplier_key]
        if purchase.supplier:
            supplier_entry["name"] = purchase.supplier.name
        supplier_entry["spent"] += invoice_total
        supplier_entry["units"] += invoice_units
        supplier_entry["invoices"] += 1

        if invoice_total > largest_invoice["amount"]:
            largest_invoice["amount"] = invoice_total
            largest_invoice["supplier"] = (
                purchase.supplier.name if purchase.supplier else "Tanpa supplier"
            )
            largest_invoice["date"] = _format_date_id(invoice_date)

    average_invoice = (
        totals["spend"] / totals["invoices"] if totals["invoices"] else 0.0
    )
    active_suppliers = len([entry for entry in supplier_map.values() if entry["spent"]])

    daily_points = [
        {
            "date": date_key.isoformat(),
            "label": _format_date_id(date_key),
            "spent": round(values["spent"], 2),
        }
        for date_key, values in sorted(daily_map.items())
    ]

    monthly_breakdown = [
        {
            "label": datetime(year=year, month=month, day=1).strftime("%b %Y"),
            "spent": values["spent"],
            "units": values["units"],
        }
        for (year, month), values in sorted(monthly_map.items())
    ]

    top_suppliers = sorted(
        supplier_map.values(), key=lambda entry: entry["spent"], reverse=True
    )[:5]

    summary_cards = [
        {
            "label": "Total Pengeluaran",
            "value": totals["spend"],
            "icon": "fa-coins",
            "accent": "text-primary",
            "subtitle": "Nilai faktur bersih",
        },
        {
            "label": "Diskon Diterima",
            "value": totals["discount"],
            "icon": "fa-percentage",
            "accent": "text-success",
            "subtitle": "Potongan supplier",
        },
        {
            "label": "Pajak Dibayar",
            "value": totals["tax"],
            "icon": "fa-file-invoice-dollar",
            "accent": "text-warning",
            "subtitle": "PPN pembelian",
        },
        {
            "label": "Barang Direstock",
            "value": totals["units"],
            "icon": "fa-boxes",
            "accent": "text-info",
            "subtitle": "Total unit masuk",
        },
    ]

    insight_cards = [
        {
            "title": "Rata-rata Faktur",
            "value": average_invoice,
            "type": "currency",
            "description": "Pengeluaran rata-rata per transaksi.",
        },
        {
            "title": "Supplier aktif",
            "value": active_suppliers,
            "type": "count",
            "description": "Partner yang memasok periode ini.",
        },
        {
            "title": "Faktur terbesar",
            "value": largest_invoice["amount"],
            "type": "currency",
            "description": f"{largest_invoice['supplier']} • {largest_invoice['date']}",
        },
        {
            "title": "Jumlah faktur",
            "value": totals["invoices"],
            "type": "count",
            "description": "Banyaknya transaksi pembelian.",
        },
    ]

    filter_values = {
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
    }
    range_label = f"{_format_date_id(start_date)} - {_format_date_id(end_date)}"

    return render_template(
        "laporan_pembelian.html",
        summary_cards=summary_cards,
        insight_cards=insight_cards,
        top_suppliers=top_suppliers,
        daily_points=daily_points,
        monthly_breakdown=monthly_breakdown,
        totals=totals,
        average_invoice=average_invoice,
        active_suppliers=active_suppliers,
        largest_invoice=largest_invoice,
        range_label=range_label,
        filter_values=filter_values,
    )


def _product_cost_basis(product):
    return float(product.harga_lama or product.harga_beli or product.harga or 0.0)


def _get_locked_period_for_date(date_value):
    if not date_value:
        return None
    return (
        AccountingPeriod.query.filter(
            AccountingPeriod.is_locked == True,
            AccountingPeriod.start_date <= date_value,
            AccountingPeriod.end_date >= date_value,
        )
        .order_by(AccountingPeriod.start_date.desc())
        .first()
    )


def _build_period_metrics(start_date, end_date):
    if not start_date or not end_date:
        return None
    if start_date > end_date:
        return None

    sales_total = (
        db.session.query(func.coalesce(func.sum(Penjualan.total_harga), 0.0))
        .filter(Penjualan.tanggal_penjualan >= start_date)
        .filter(Penjualan.tanggal_penjualan <= end_date)
        .scalar()
        or 0.0
    )

    purchase_total = (
        db.session.query(func.coalesce(func.sum(BarangPembelian.hpp), 0.0))
        .join(Pembelian, BarangPembelian.pembelian)
        .filter(Pembelian.tanggal_faktur >= start_date)
        .filter(Pembelian.tanggal_faktur <= end_date)
        .scalar()
        or 0.0
    )

    hpp_total = (
        db.session.query(
            func.coalesce(
                func.sum(
                    DetailPenjualan.jumlah
                    * func.coalesce(Produk.harga_lama, Produk.harga_beli, 0.0)
                ),
                0.0,
            )
        )
        .join(Produk, DetailPenjualan.produk)
        .join(Penjualan, DetailPenjualan.penjualan)
        .filter(Penjualan.tanggal_penjualan >= start_date)
        .filter(Penjualan.tanggal_penjualan <= end_date)
        .scalar()
        or 0.0
    )

    inventory_value = (
        db.session.query(
            func.coalesce(
                func.sum(
                    Produk.stok_lama
                    * func.coalesce(Produk.harga_lama, Produk.harga_beli, 0.0)
                ),
                0.0,
            )
        )
        .scalar()
        or 0.0
    )

    net_income = round(sales_total - hpp_total, 2)

    return {
        "sales_total": round(sales_total, 2),
        "purchase_total": round(purchase_total, 2),
        "hpp_total": round(hpp_total, 2),
        "inventory_value": round(inventory_value, 2),
        "net_income": net_income,
        "difference": round(inventory_value - hpp_total, 2),
    }


def _close_accounting_period(label, start_date, end_date, user_id, description=None):
    if not label:
        raise ValueError("Label periode wajib diisi.")
    if not start_date or not end_date:
        raise ValueError("Tanggal awal dan akhir periode wajib diisi.")
    if start_date > end_date:
        raise ValueError("Tanggal awal tidak boleh melewati tanggal akhir.")

    overlap_closed = AccountingPeriod.query.filter(
        AccountingPeriod.start_date <= end_date,
        AccountingPeriod.end_date >= start_date,
        AccountingPeriod.is_locked == True,
    ).first()
    if overlap_closed:
        raise ValueError(f"Periode {overlap_closed.label} sudah ditutup.")

    period = AccountingPeriod.query.filter(
        AccountingPeriod.start_date == start_date,
        AccountingPeriod.end_date == end_date,
        AccountingPeriod.status == "open",
    ).first()

    if not period:
        period = AccountingPeriod(
            label=label,
            start_date=start_date,
            end_date=end_date,
            description=description,
            created_by=user_id,
        )
        db.session.add(period)
        db.session.flush()

    period.label = label
    period.status = "closed"
    period.description = description or period.description
    period.is_locked = True
    period.closed_by = user_id
    period.closed_at = datetime.utcnow()

    sales = (
        Penjualan.query.filter(Penjualan.tanggal_penjualan >= start_date)
        .filter(Penjualan.tanggal_penjualan <= end_date)
        .all()
    )
    for sale in sales:
        sale.accounting_period_id = period.id
        sale.is_locked = True

    purchases = (
        Pembelian.query.filter(Pembelian.tanggal_faktur >= start_date)
        .filter(Pembelian.tanggal_faktur <= end_date)
        .all()
    )
    for purchase in purchases:
        purchase.accounting_period_id = period.id
        purchase.is_locked = True

    journals = (
        JournalEntry.query.filter(JournalEntry.date >= start_date)
        .filter(JournalEntry.date <= end_date)
        .all()
    )
    for journal in journals:
        journal.accounting_period_id = period.id
        journal.is_locked = True

    summary = _build_period_metrics(start_date, end_date)
    if not summary:
        summary = {
            "sales_total": 0.0,
            "hpp_total": 0.0,
            "net_income": 0.0,
        }
    income_account = Account.query.filter_by(type="income", is_active=True).order_by(Account.code).first()
    expense_account = Account.query.filter_by(type="expense", is_active=True).order_by(Account.code).first()
    equity_account = Account.query.filter_by(type="equity", is_active=True).order_by(Account.code).first()

    net_income = summary.get("net_income", 0.0)
    closing_entry = None
    if income_account and (expense_account or equity_account):
        closing_entry = JournalEntry(
            reference=_generate_journal_reference(),
            date=end_date,
            memo=f"Penutupan periode {label}",
            created_by=user_id,
            accounting_period_id=period.id,
            is_locked=True,
        )
        db.session.add(closing_entry)
        db.session.flush()

        description = f"Rekap penutupan periode {label}"
        if summary["sales_total"] > 0 and income_account:
            db.session.add(
                JournalLine(
                    entry_id=closing_entry.id,
                    account_id=income_account.id,
                    debit=summary["sales_total"],
                    credit=0.0,
                    description=description,
                )
            )

        if summary["hpp_total"] > 0 and expense_account:
            db.session.add(
                JournalLine(
                    entry_id=closing_entry.id,
                    account_id=expense_account.id,
                    debit=0.0,
                    credit=summary["hpp_total"],
                    description=description,
                )
            )

        if net_income != 0 and equity_account:
            if net_income > 0:
                db.session.add(
                    JournalLine(
                        entry_id=closing_entry.id,
                        account_id=equity_account.id,
                        debit=0.0,
                        credit=net_income,
                        description="Laba bersih periode ditutup",
                    )
                )
            else:
                db.session.add(
                    JournalLine(
                        entry_id=closing_entry.id,
                        account_id=equity_account.id,
                        debit=abs(net_income),
                        credit=0.0,
                        description="Rugi bersih periode ditutup",
                    )
                )
    else:
        logging.warning("Kredit penutupan tidak lengkap: pastikan ada akun income/expense/equity aktif.")

    return period


def _ensure_table(model):
    try:
        engine = db.session.get_bind()
        model.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass


def _generate_stock_reference():
    base = f"SO{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    candidate = base
    counter = 1
    while StockOpnameSession.query.filter_by(reference=candidate).first():
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def _generate_journal_reference():
    base = f"JV{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    candidate = base
    counter = 1
    while JournalEntry.query.filter_by(reference=candidate).first():
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def _generate_invoice_number(prefix="F"):
    """
    Generate unique invoice number using timestamp with microseconds and fallback counter.
    """
    base = f"{prefix}{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
    candidate = base
    counter = 1
    while Penjualan.query.filter_by(no_faktur=candidate).first():
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def _get_accounting_setting():
    _ensure_table(AccountingSetting)
    return AccountingSetting.query.first()


def _calculate_line_items_hpp(line_items):
    total = 0.0
    for item in line_items:
        product = item.get("product")
        if not product:
            continue
        cost_basis = float(
            product.harga_lama
            or product.harga_beli
            or product.harga
            or 0.0
        )
        total += cost_basis * (item.get("qty") or 0)
    return round(total, 2)


def _record_auto_cogs_journal(penjualan, amount, settings, user_id=None):
    if (
        not settings
        or not settings.inventory_account_id
        or not settings.cogs_account_id
        or amount <= 0
    ):
        return None

    entry = JournalEntry(
        reference=_generate_journal_reference(),
        date=penjualan.tanggal_penjualan or datetime.utcnow().date(),
        memo=f"Auto COGS – Penjualan {penjualan.no_faktur}",
        created_by=user_id,
    )
    db.session.add(entry)
    db.session.flush()

    description = f"HPP otomatis untuk invoice {penjualan.no_faktur}"
    db.session.add(
        JournalLine(
            entry_id=entry.id,
            account_id=settings.cogs_account_id,
            debit=amount,
            credit=0.0,
            description=description,
        )
    )
    db.session.add(
        JournalLine(
            entry_id=entry.id,
            account_id=settings.inventory_account_id,
            debit=0.0,
            credit=amount,
            description=description,
        )
    )
    return entry


def _resolve_sqlite_path():
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    if not uri.startswith("sqlite:"):
        return None
    trimmed = uri.split("sqlite://")[1]
    if trimmed.startswith("/"):
        trimmed = trimmed[1:]
    return os.path.abspath(trimmed)


def _collect_system_metrics():
    metrics = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "environment": current_app.config.get("FLASK_ENV", "production"),
    }

    db_info = {
        "engine": None,
        "name": None,
        "host": None,
        "path": None,
        "size": None,
    }
    base_dir = current_app.instance_path

    db_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    url_obj = None
    try:
        url_obj = make_url(db_uri)
        db_info.update(
            {
                "engine": url_obj.get_backend_name(),
                "name": url_obj.database,
                "host": url_obj.host,
            }
        )
    except Exception:
        url_obj = None

    db_path = _resolve_sqlite_path()
    if url_obj and url_obj.get_backend_name().startswith("sqlite"):
        if db_path and os.path.exists(db_path):
            db_info["path"] = db_path
            db_info["size"] = os.path.getsize(db_path)
            base_dir = os.path.dirname(db_path) or base_dir
    elif url_obj:
        db_info["size"] = _fetch_remote_db_size(url_obj)

    metrics["database"] = db_info

    if not os.path.exists(base_dir):
        base_dir = os.getcwd()

    try:
        disk = shutil.disk_usage(base_dir)
        metrics["disk"] = {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
        }
    except Exception:
        metrics["disk"] = {"total": None, "used": None, "free": None}

    if psutil:
        vm = psutil.virtual_memory()
        metrics["memory"] = {
            "total": vm.total,
            "available": vm.available,
            "percent": vm.percent,
        }
        metrics["cpu"] = {
            "count": psutil.cpu_count(logical=True),
            "percent": psutil.cpu_percent(interval=0.1),
            "load_avg": os.getloadavg() if hasattr(os, "getloadavg") else None,
        }
        process = psutil.Process()
        mem_info = process.memory_full_info()
        metrics["process_memory"] = {
            "rss": mem_info.rss,
            "uss": getattr(mem_info, "uss", None),
        }
    else:
        metrics["memory"] = None
        metrics["cpu"] = {
            "count": os.cpu_count(),
            "percent": None,
            "load_avg": os.getloadavg() if hasattr(os, "getloadavg") else None,
        }
        metrics["process_memory"] = None

    return metrics


def _fetch_remote_db_size(url_obj):
    backend = url_obj.get_backend_name() if url_obj else None
    if backend == "postgresql":
        query = text("SELECT pg_database_size(current_database())")
    elif backend == "mysql":
        query = text(
            "SELECT SUM(data_length + index_length) "
            "FROM information_schema.tables WHERE table_schema = DATABASE()"
        )
    else:
        return None

    try:
        result = db.session.execute(query).scalar()
        return int(result) if result is not None else None
    except Exception:
        return None


@bp.route("/update-harga", methods=["GET", "POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def update_harga():
    if request.method == "POST":
        if not request.is_json:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Content-Type harus application/json.",
                    }
                ),
                415,
            )

        payload = request.get_json(silent=True) or {}
        items = payload.get("items") or []
        if not isinstance(items, list) or not items:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Kirim minimal satu produk yang akan diperbarui.",
                    }
                ),
                400,
            )

        errors = []
        updated_rows = []
        now = datetime.utcnow()
        inspector = inspect(db.session.get_bind())
        price_log_available = inspector.has_table("price_change")
        for index, item in enumerate(items, start=1):
            product_id = item.get("product_id")
            new_price_raw = item.get("new_price")
            reason = (item.get("reason") or "").strip()

            try:
                product_id = int(product_id)
            except (TypeError, ValueError):
                errors.append(f"Produk pada baris {index} tidak valid.")
                continue

            try:
                new_price = float(new_price_raw)
            except (TypeError, ValueError):
                errors.append(f"Harga baru tidak valid (baris {index}).")
                continue

            if new_price <= 0:
                errors.append(f"Harga harus lebih besar dari 0 (baris {index}).")
                continue

            product = Produk.query.get(product_id)
            if not product:
                errors.append(f"Produk dengan ID {product_id} tidak ditemukan.")
                continue

            old_price = float(product.harga or 0.0)
            if math.isclose(old_price, new_price, rel_tol=0.0, abs_tol=0.005):
                continue

            cost_basis = _product_cost_basis(product)
            margin_before = old_price - cost_basis
            margin_after = new_price - cost_basis

            product.harga = new_price
            if price_log_available:
                price_change = PriceChange(
                    product_id=product.id,
                    user_id=session.get("user_id"),
                    old_price=old_price,
                    new_price=new_price,
                    margin_before=margin_before,
                    margin_after=margin_after,
                    reason=reason or None,
                    created_at=now,
                )
                db.session.add(price_change)
            updated_rows.append(
                {
                    "product_id": product.id,
                    "name": product.nama_produk,
                    "old_price": old_price,
                    "new_price": new_price,
                    "margin_after": margin_after,
                }
            )

        if errors:
            db.session.rollback()
            return jsonify({"success": False, "message": " ".join(errors)}), 400

        if not updated_rows:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Tidak ada harga yang berubah dari nilai sebelumnya.",
                    }
                ),
                400,
            )

        db.session.commit()
        return jsonify(
            {
                "success": True,
                "message": (
                    f"{len(updated_rows)} harga berhasil diperbarui."
                    + (
                        " (Catatan: histori harga belum aktif, jalankan migrasi.)"
                        if not price_log_available
                        else ""
                    )
                ),
                "updated": updated_rows,
            }
        )

    products = (
        Produk.query.options(
            joinedload(Produk.kategori),
            joinedload(Produk.supplier),
        )
        .order_by(Produk.nama_produk.asc())
        .all()
    )
    product_rows = []
    for product in products:
        cost_basis = _product_cost_basis(product)
        current_price = float(product.harga or 0.0)
        margin_value = current_price - cost_basis
        margin_pct = (margin_value / cost_basis * 100) if cost_basis else 0.0
        product_rows.append(
            {
                "id": product.id,
                "code": product.kode_produk,
                "name": product.nama_produk,
                "sku": product.sku or "-",
                "kategori": (
                    product.kategori.name if product.kategori else "Tanpa kategori"
                ),
                "supplier": (
                    product.supplier.name if product.supplier else "Tanpa supplier"
                ),
                "cost": cost_basis,
                "price": current_price,
                "margin_value": margin_value,
                "margin_percent": margin_pct,
            }
        )

    inspector = inspect(db.session.get_bind())
    price_change_ready = inspector.has_table("price_change")
    recent_changes = []
    if price_change_ready:
        try:
            recent_changes = (
                PriceChange.query.options(
                    joinedload(PriceChange.product),
                    joinedload(PriceChange.user),
                )
                .order_by(PriceChange.created_at.desc())
                .limit(10)
                .all()
            )
        except OperationalError:
            db.session.rollback()
            price_change_ready = False

    return render_template(
        "update_harga.html",
        products=product_rows,
        recent_changes=recent_changes,
        price_change_ready=price_change_ready,
    )


@bp.route("/stok-opname", methods=["GET", "POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def stok_opname():
    if request.method == "POST":
        if not request.is_json:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Content-Type harus application/json.",
                    }
                ),
                415,
            )
        payload = request.get_json(silent=True) or {}
        items = payload.get("items") or []
        if not items:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Tambahkan minimal satu produk untuk stock opname.",
                    }
                ),
                400,
            )
        location = (payload.get("location") or "").strip()
        note = (payload.get("note") or "").strip()
        reference = (
            payload.get("reference") or ""
        ).strip() or _generate_stock_reference()

        opname_session = StockOpnameSession(
            reference=reference,
            location=location or None,
            note=note or None,
            status="completed",
            created_by=session.get("user_id"),
            created_at=datetime.utcnow(),
            finalized_at=datetime.utcnow(),
        )
        db.session.add(opname_session)
        adjustments = []
        errors = []
        for index, item in enumerate(items, start=1):
            product_id = item.get("product_id")
            counted_raw = item.get("counted_qty")
            item_note = (item.get("note") or "").strip()
            try:
                product_id = int(product_id)
            except (TypeError, ValueError):
                errors.append(f"Produk tidak valid pada baris {index}.")
                continue
            try:
                counted_qty = int(counted_raw)
            except (TypeError, ValueError):
                errors.append(f"Jumlah fisik tidak valid (baris {index}).")
                continue
            if counted_qty < 0:
                errors.append(f"Jumlah fisik tidak boleh negatif (baris {index}).")
                continue
            product = Produk.query.get(product_id)
            if not product:
                errors.append(f"Produk dengan ID {product_id} tidak ditemukan.")
                continue
            system_qty = int(product.stok_lama or 0)
            difference = counted_qty - system_qty
            product.stok_lama = counted_qty
            opname_item = StockOpnameItem(
                session=opname_session,
                product_id=product.id,
                system_qty=system_qty,
                counted_qty=counted_qty,
                difference_qty=difference,
                note=item_note or None,
            )
            db.session.add(opname_item)
            adjustments.append(
                {
                    "product_id": product.id,
                    "name": product.nama_produk,
                    "system_qty": system_qty,
                    "counted_qty": counted_qty,
                    "difference": difference,
                }
            )
        if errors:
            db.session.rollback()
            return jsonify({"success": False, "message": " ".join(errors)}), 400
        if not adjustments:
            db.session.rollback()
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Tidak ada baris valid yang diproses.",
                    }
                ),
                400,
            )
        db.session.commit()
        plus = sum(item["difference"] for item in adjustments if item["difference"] > 0)
        minus = sum(
            item["difference"] for item in adjustments if item["difference"] < 0
        )
        return jsonify(
            {
                "success": True,
                "reference": reference,
                "message": "Stock opname berhasil disimpan dan stok diperbarui.",
                "summary": {
                    "rows": len(adjustments),
                    "plus": plus,
                    "minus": minus,
                },
            }
        )

    products = Produk.query.order_by(Produk.nama_produk.asc()).all()
    product_payload = [
        {
            "id": product.id,
            "code": product.kode_produk,
            "name": product.nama_produk,
            "sku": product.sku or "-",
            "kategori": product.kategori.name if product.kategori else "Tanpa kategori",
            "stock": int(product.stok_lama or 0),
        }
        for product in products
    ]
    inspector = inspect(db.session.get_bind())
    opname_ready = inspector.has_table("stock_opname_session")
    sessions = []
    if opname_ready:
        try:
            sessions = (
                StockOpnameSession.query.options(
                    joinedload(StockOpnameSession.user),
                    joinedload(StockOpnameSession.items).joinedload(
                        StockOpnameItem.product
                    ),
                )
                .order_by(StockOpnameSession.created_at.desc())
                .limit(5)
                .all()
            )
        except OperationalError:
            db.session.rollback()
            opname_ready = False
    session_payload = []
    for opname in sessions:
        diff_total = sum(item.difference_qty for item in opname.items)
        item_count = len(opname.items)
        session_payload.append(
            {
                "reference": opname.reference,
                "created_at": (
                    _format_date_id(opname.created_at.date())
                    if opname.created_at
                    else "-"
                ),
                "user": opname.user.username if opname.user else "System",
                "location": opname.location or "-",
                "status": opname.status.title() if opname.status else "-",
                "item_count": item_count,
                "diff_total": diff_total,
            }
        )
    stats = {
        "product_count": len(products),
        "session_count": StockOpnameSession.query.count() if opname_ready else 0,
        "last_reference": session_payload[0]["reference"] if session_payload else None,
    }
    return render_template(
        "stok_opname.html",
        product_payload=product_payload,
        sessions=session_payload,
        stats=stats,
        opname_ready=opname_ready,
    )


@bp.route("/laporan/stok-opname")
@login_required
@roles_required(*INVENTORY_ROLES)
def laporan_stok_opname():
    start_date = _parse_date_param(request.args.get("start_date"))
    end_date = _parse_date_param(request.args.get("end_date"))
    today = datetime.utcnow().date()
    if not start_date or not end_date:
        end_date = today
        start_date = today.replace(day=1)
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    try:
        _ensure_table(StockOpnameSession)
        _ensure_table(StockOpnameItem)
        opname_ready = True
    except Exception:
        opname_ready = False

    sessions = []
    if opname_ready:
        sessions = (
            StockOpnameSession.query.options(
                joinedload(StockOpnameSession.items).joinedload(
                    StockOpnameItem.product
                ),
                joinedload(StockOpnameSession.user),
            )
            .filter(
                StockOpnameSession.created_at
                >= datetime.combine(start_date, datetime.min.time())
            )
            .filter(
                StockOpnameSession.created_at
                <= datetime.combine(end_date, datetime.max.time())
            )
            .order_by(StockOpnameSession.created_at.desc())
            .all()
        )

    totals = {
        "sessions": len(sessions),
        "items": 0,
        "over": 0,
        "short": 0,
    }
    daily_map = defaultdict(lambda: {"count": 0, "over": 0, "short": 0})
    product_variances = defaultdict(lambda: {"name": "", "diff": 0})

    for session in sessions:
        session_date = session.created_at.date() if session.created_at else today
        diff = sum(item.difference_qty for item in session.items)
        totals["items"] += len(session.items)
        for item in session.items:
            difference = item.difference_qty or 0
            if difference > 0:
                totals["over"] += difference
                daily_map[session_date]["over"] += difference
            elif difference < 0:
                totals["short"] += difference
                daily_map[session_date]["short"] += difference
            product = item.product
            key = item.product_id
            if key not in product_variances and product:
                product_variances[key]["name"] = product.nama_produk
            product_variances[key]["diff"] += difference
        daily_map[session_date]["count"] += 1

    daily_points = [
        {
            "date": date.isoformat(),
            "label": _format_date_id(date),
            "sessions": values["count"],
            "over": values["over"],
            "short": values["short"],
        }
        for date, values in sorted(daily_map.items())
    ]

    top_variances = sorted(
        product_variances.values(), key=lambda entry: abs(entry["diff"]), reverse=True
    )[:5]

    summary_cards = [
        {
            "label": "Total Sesi",
            "value": totals["sessions"],
            "icon": "fa-clipboard-check",
            "accent": "text-primary",
            "subtitle": "Rentang dipilih",
        },
        {
            "label": "Item Dihitung",
            "value": totals["items"],
            "icon": "fa-boxes",
            "accent": "text-success",
            "subtitle": "Total baris opname",
        },
        {
            "label": "Selisih +",
            "value": totals["over"],
            "icon": "fa-plus-circle",
            "accent": "text-info",
            "subtitle": "Penambahan stok",
        },
        {
            "label": "Selisih -",
            "value": totals["short"],
            "icon": "fa-minus-circle",
            "accent": "text-danger",
            "subtitle": "Pengurangan stok",
        },
    ]

    recent_sessions = [
        {
            "reference": session.reference,
            "date": (
                _format_date_id(session.created_at.date())
                if session.created_at
                else "-"
            ),
            "user": session.user.username if session.user else "System",
            "location": session.location or "-",
            "items": len(session.items),
            "diff": sum(item.difference_qty for item in session.items),
        }
        for session in sessions[:5]
    ]

    range_label = f"{_format_date_id(start_date)} - {_format_date_id(end_date)}"
    filter_values = {
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
    }

    return render_template(
        "laporan_stok_opname.html",
        summary_cards=summary_cards,
        daily_points=daily_points,
        top_variances=top_variances,
        recent_sessions=recent_sessions,
        totals=totals,
        range_label=range_label,
        filter_values=filter_values,
        opname_ready=opname_ready,
    )


@bp.route("/laporan/stok-barang")
@login_required
@roles_required(*INVENTORY_ROLES)
def laporan_stok_barang():
    search_query = (request.args.get("search") or "").strip()
    kategori_filter = request.args.get("kategori")
    supplier_filter = request.args.get("supplier")

    query = Produk.query.options(
        joinedload(Produk.kategori),
        joinedload(Produk.supplier),
        joinedload(Produk.satuan),
    )
    if search_query:
        like = f"%{search_query}%"
        query = query.filter(
            or_(
                Produk.nama_produk.ilike(like),
                Produk.kode_produk.ilike(like),
                Produk.sku.ilike(like),
            )
        )
    if kategori_filter:
        query = query.filter(Produk.kategori_id == kategori_filter)
    if supplier_filter:
        query = query.filter(Produk.supplier_id == supplier_filter)

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 15, type=int)
    per_page = max(5, min(per_page, 100))

    base_query = query.order_by(Produk.nama_produk.asc())
    pagination = base_query.paginate(page=page, per_page=per_page, error_out=False)
    products = pagination.items
    total_products = pagination.total
    total_stock = 0
    total_value = 0.0
    total_sell_value = 0.0

    low_stock_items = []
    category_map = defaultdict(lambda: {"label": "Tanpa kategori", "stock": 0})

    product_rows = []
    for product in products:
        stock = int(product.stok_lama or 0)
        cost = _product_cost_basis(product)
        price = float(product.harga or 0.0)
        total_products = len(products)
        total_stock += stock
        total_value += stock * cost
        total_sell_value += stock * price
        minimal = int(product.stok_minimal or 0)
        low_stock = minimal > 0 and stock <= minimal
        if low_stock:
            low_stock_items.append(
                {
                    "name": product.nama_produk,
                    "code": product.kode_produk,
                    "stock": stock,
                    "minimal": minimal,
                    "supplier": (
                        product.supplier.name if product.supplier else "Tanpa supplier"
                    ),
                }
            )
        category_name = product.kategori.name if product.kategori else "Tanpa kategori"
        category_entry = category_map[category_name]
        category_entry["label"] = category_name
        category_entry["stock"] += stock

        product_rows.append(
            {
                "id": product.id,
                "name": product.nama_produk,
                "code": product.kode_produk,
                "sku": product.sku or "-",
                "kategori": category_name,
                "supplier": (
                    product.supplier.name if product.supplier else "Tanpa supplier"
                ),
                "stock": stock,
                "minimal": minimal,
                "cost": cost,
                "price": price,
                "value": stock * cost,
                "unit_value": stock * cost / stock if stock else cost,
            }
        )

    low_stock_items = sorted(low_stock_items, key=lambda item: item["stock"])[:5]
    category_distribution = sorted(
        category_map.values(), key=lambda entry: entry["stock"], reverse=True
    )

    summary_cards = [
        {
            "label": "Produk Ditampilkan",
            "value": total_products,
            "icon": "fa-box-open",
            "accent": "text-primary",
            "subtitle": f"Halaman {pagination.page} dari {pagination.pages}" if pagination.pages else "Sesuai filter",
        },
        {
            "label": "Total Stok (pcs)",
            "value": total_stock,
            "icon": "fa-layer-group",
            "accent": "text-success",
            "subtitle": "Jumlah unit fisik",
        },
        {
            "label": "Nilai HPP",
            "value": total_value,
            "icon": "fa-coins",
            "accent": "text-warning",
            "subtitle": "Stok × biaya",
        },
        {
            "label": "Nilai Jual",
            "value": total_sell_value,
            "icon": "fa-wallet",
            "accent": "text-info",
            "subtitle": "Potensi revenue",
        },
    ]

    filter_values = {
        "search": search_query,
        "kategori": kategori_filter or "",
        "supplier": supplier_filter or "",
    }

    kategori_options = Kategori.query.order_by(Kategori.name.asc()).all()
    supplier_options = Supplier.query.order_by(Supplier.name.asc()).all()

    return render_template(
        "laporan_stok_barang.html",
        summary_cards=summary_cards,
        products=product_rows,
        low_stock_items=low_stock_items,
        category_distribution=category_distribution,
        filter_values=filter_values,
        kategori_options=kategori_options,
        supplier_options=supplier_options,
        pagination=pagination,
        page=page,
        per_page=per_page,
        pagination_args={k: v for k, v in request.args.to_dict().items() if k != "page"},
    )


@bp.route("/api/laporan/stok-barang/suggest", methods=["GET"])
@login_required
@roles_required(*INVENTORY_ROLES)
def laporan_stok_barang_suggest():
    term = (request.args.get("q") or "").strip()
    if len(term) < 2:
        return jsonify({"products": []})

    kategori_filter = request.args.get("kategori")
    supplier_filter = request.args.get("supplier")
    like = f"%{term}%"

    query = Produk.query.options(
        joinedload(Produk.kategori),
        joinedload(Produk.supplier),
    ).filter(
        or_(
            Produk.nama_produk.ilike(like),
            Produk.kode_produk.ilike(like),
            Produk.sku.ilike(like),
        )
    )
    if kategori_filter:
        query = query.filter(Produk.kategori_id == kategori_filter)
    if supplier_filter:
        query = query.filter(Produk.supplier_id == supplier_filter)

    rows = query.order_by(Produk.nama_produk.asc()).limit(10).all()
    payload = []
    for product in rows:
        payload.append(
            {
                "id": product.id,
                "code": product.kode_produk,
                "name": product.nama_produk,
                "sku": product.sku or "-",
                "stock": int(product.stok_lama or 0),
                "kategori": product.kategori.name if product.kategori else "Tanpa kategori",
                "supplier": product.supplier.name if product.supplier else "Tanpa supplier",
            }
        )

    return jsonify({"products": payload})


@bp.route("/laporan/penjualan")
@login_required
@roles_required(*SALES_ROLES)
def laporan_penjualan_report():
    today = datetime.utcnow().date()
    default_start = today.replace(day=1)
    start_date = _parse_date_param(request.args.get("start_date")) or default_start
    end_date = _parse_date_param(request.args.get("end_date")) or today
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    search_query = (request.args.get("search") or "").strip()
    selected_sales_id = request.args.get("sales")
    selected_customer_id = request.args.get("customer")
    try:
        selected_sales_id = int(selected_sales_id) if selected_sales_id else None
    except (TypeError, ValueError):
        selected_sales_id = None
    try:
        selected_customer_id = int(selected_customer_id) if selected_customer_id else None
    except (TypeError, ValueError):
        selected_customer_id = None

    sales_query = (
        Penjualan.query.options(
            joinedload(Penjualan.detail_penjualan).joinedload(DetailPenjualan.produk),
            joinedload(Penjualan.pelanggan),
            joinedload(Penjualan.sales),
        )
        .filter(Penjualan.tanggal_penjualan >= start_date)
        .filter(Penjualan.tanggal_penjualan <= end_date)
        .order_by(Penjualan.tanggal_penjualan.asc(), Penjualan.id.asc())
    )

    if selected_sales_id:
        sales_query = sales_query.filter(Penjualan.sales_id == selected_sales_id)
    if selected_customer_id:
        sales_query = sales_query.filter(Penjualan.pelanggan_id == selected_customer_id)
    if search_query:
        like = f"%{search_query}%"
        sales_query = (
            sales_query.join(Penjualan.pelanggan)
            .join(Penjualan.sales)
            .filter(
                or_(
                    Penjualan.no_faktur.ilike(like),
                    Pelanggan.nama.ilike(like),
                    User.username.ilike(like),
                )
            )
        )
    sales_records = sales_query.all()

    totals = {
        "revenue": 0.0,
        "discount": 0.0,
        "tax": 0.0,
        "cogs": 0.0,
        "gross": 0.0,
        "marketplace_costs": 0.0,
        "orders": len(sales_records),
        "items": 0,
    }
    daily_map = defaultdict(lambda: {"revenue": 0.0, "gross": 0.0})
    monthly_map = defaultdict(lambda: {"revenue": 0.0, "gross": 0.0, "orders": 0})
    product_map = defaultdict(
        lambda: {"name": "Produk dihapus", "units": 0, "revenue": 0.0, "gross": 0.0}
    )
    customer_map = defaultdict(
        lambda: {"name": "Pelanggan umum", "orders": 0, "revenue": 0.0}
    )
    largest_invoice = {"amount": 0.0, "customer": "Pelanggan umum", "date": "-"}
    transaction_details = []

    for sale in sales_records:
        sale_date = sale.tanggal_penjualan or today
        month_key = (sale_date.year, sale_date.month)
        invoice_revenue = 0.0
        invoice_gross = 0.0
        invoice_total = 0.0
        gross_subtotal_sum = 0.0
        discount_sum = 0.0
        tax_sum = 0.0
        cost_sum = 0.0
        item_rows = []

        for detail in sale.detail_penjualan:
            qty = detail.jumlah or 0
            price = detail.harga_satuan or 0.0
            discount_pct = detail.diskon or 0.0
            tax_pct = detail.pajak or 0.0

            base_total = price * qty
            discount_value = base_total * (discount_pct / 100.0)
            taxable = base_total - discount_value
            tax_value = taxable * (tax_pct / 100.0)
            line_total = taxable + tax_value

            product_cost = 0.0
            if detail.produk:
                product_cost = (
                    detail.produk.harga_lama
                    or detail.produk.harga_beli
                    or detail.produk.harga
                    or 0.0
                )
            cost_value = product_cost * qty
            gross_value = taxable - cost_value

            totals["items"] += qty
            totals["discount"] += discount_value
            totals["tax"] += tax_value
            totals["cogs"] += cost_value
            totals["gross"] += gross_value

            invoice_revenue += taxable
            invoice_gross += gross_value
            invoice_total += line_total
            gross_subtotal_sum += base_total
            discount_sum += discount_value
            tax_sum += tax_value
            cost_sum += cost_value

            item_rows.append(
                {
                    "product_id": detail.produk.id if detail.produk else None,
                    "product_name": (
                        detail.produk.nama_produk if detail.produk else detail.produk_id
                    ),
                    "sku": detail.produk.sku if detail.produk else "-",
                    "qty": qty,
                    "unit_price": price,
                    "discount_percent": discount_pct,
                    "discount_value": discount_value,
                    "tax_percent": tax_pct,
                    "tax_value": tax_value,
                    "line_total": line_total,
                    "cost_value": cost_value,
                    "gross_value": gross_value,
                }
            )

            product_key = detail.produk.id if detail.produk else f"detail-{detail.id}"
            if detail.produk:
                product_map[product_key]["name"] = detail.produk.nama_produk
            product_map[product_key]["units"] += qty
            product_map[product_key]["revenue"] += taxable
            product_map[product_key]["gross"] += gross_value

        cost_total = float(sale.marketplace_cost_total or 0.0)
        net_invoice_revenue = max(invoice_revenue - cost_total, 0.0)
        totals["marketplace_costs"] += cost_total
        totals["revenue"] += net_invoice_revenue
        daily_map[sale_date]["revenue"] += net_invoice_revenue
        daily_map[sale_date]["gross"] += invoice_gross
        monthly_map[month_key]["revenue"] += net_invoice_revenue
        monthly_map[month_key]["gross"] += invoice_gross
        monthly_map[month_key]["orders"] += 1

        customer_key = sale.pelanggan_id or f"anon-{sale.id}"
        customer_entry = customer_map[customer_key]
        if sale.pelanggan:
            customer_entry["name"] = sale.pelanggan.nama
        customer_entry["orders"] += 1
        customer_entry["revenue"] += net_invoice_revenue

        if invoice_total > largest_invoice["amount"]:
            largest_invoice["amount"] = invoice_total
            largest_invoice["customer"] = (
                sale.pelanggan.nama if sale.pelanggan else "Pelanggan umum"
            )
            largest_invoice["date"] = _format_date_id(sale_date)
        cost_total = float(sale.marketplace_cost_total or 0.0)
        net_invoice_revenue = invoice_revenue - cost_total
        totals["marketplace_costs"] += cost_total
        totals["revenue"] -= cost_total
        daily_map[sale_date]["revenue"] -= cost_total
        monthly_map[month_key]["revenue"] -= cost_total

        net_subtotal = gross_subtotal_sum - discount_sum
        staff_name = sale.sales.username if sale.sales else "Sales"
        customer_name = sale.pelanggan.nama if sale.pelanggan else "Umum"
        customer_code = sale.pelanggan.pelanggan_id if sale.pelanggan else "-"
        price_level_name = (
            sale.pelanggan.price_level.name
            if sale.pelanggan and sale.pelanggan.price_level
            else "Harga standar"
        )
        transaction_details.append(
            {
                "id": sale.id,
                "invoice": sale.no_faktur,
                "timestamp": _format_date_id(sale_date),
                "staff": staff_name,
                "customer": {"name": customer_name, "code": customer_code},
                "items": item_rows,
                "subtotal_before_discount": gross_subtotal_sum,
                "total_discount": discount_sum,
                "net_subtotal": net_subtotal,
                "tax_total": tax_sum,
                "grand_total": net_subtotal + tax_sum,
                "shipping_fee": 0.0,
                "extra_fee": 0.0,
                "payment_method": "Belum dicatat",
                "price_level": price_level_name,
                "note": "-",
                "status": "Selesai",
                "cost_total": cost_sum,
                "marketplace_cost_total": cost_total,
                "gross_profit": net_subtotal - cost_sum,
                "net_revenue": net_invoice_revenue,
                "print_link": url_for("main.penjualan"),
            }
        )

    average_order = totals["revenue"] / totals["orders"] if totals["orders"] else 0.0
    margin_percent = (
        (totals["gross"] / totals["revenue"]) * 100 if totals["revenue"] else 0.0
    )

    daily_points = [
        {
            "date": date_key.isoformat(),
            "label": _format_date_id(date_key),
            "revenue": round(values["revenue"], 2),
            "gross": round(values["gross"], 2),
        }
        for date_key, values in sorted(daily_map.items())
    ]

    monthly_breakdown = [
        {
            "label": datetime(year=year, month=month, day=1).strftime("%b %Y"),
            "revenue": values["revenue"],
            "gross": values["gross"],
            "orders": values["orders"],
            "avg_order": (
                (values["revenue"] / values["orders"]) if values["orders"] else 0.0
            ),
        }
        for (year, month), values in sorted(monthly_map.items())
    ]

    top_products = sorted(
        product_map.values(), key=lambda entry: entry["revenue"], reverse=True
    )[:5]
    top_customers = sorted(
        customer_map.values(), key=lambda entry: entry["revenue"], reverse=True
    )[:5]

    summary_cards = [
        {
            "label": "Pendapatan Bersih",
            "value": totals["revenue"],
            "icon": "fa-wallet",
            "accent": "text-primary",
            "subtitle": "Setelah diskon & biaya marketplace",
        },
        {
            "label": "Biaya Marketplace",
            "value": totals["marketplace_costs"],
            "icon": "fa-coins",
            "accent": "text-danger",
            "subtitle": "Komisi, cashback, bebas ongkir",
        },
        {
            "label": "Laba Kotor",
            "value": totals["gross"],
            "icon": "fa-chart-line",
            "accent": "text-success",
            "subtitle": f"Margin {margin_percent:.1f}%",
        },
        {
            "label": "Transaksi",
            "value": totals["orders"],
            "icon": "fa-receipt",
            "accent": "text-info",
            "subtitle": "Jumlah faktur",
        },
    ]

    insight_cards = [
        {
            "title": "Rata-rata Order",
            "value": average_order,
            "type": "currency",
            "description": "Nilai penjualan bersih per faktur.",
        },
        {
            "title": "Barang Terjual",
            "value": totals["items"],
            "type": "count",
            "description": "Total unit yang keluar.",
        },
        {
            "title": "Diskon Diberikan",
            "value": totals["discount"],
            "type": "currency",
            "description": "Potongan harga keseluruhan.",
        },
        {
            "title": "Faktur terbesar",
            "value": largest_invoice["amount"],
            "type": "currency",
            "description": f"{largest_invoice['customer']} • {largest_invoice['date']}",
        },
    ]

    filter_values = {
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "sales": selected_sales_id or "",
        "customer": selected_customer_id or "",
        "search": search_query,
    }
    range_label = f"{_format_date_id(start_date)} - {_format_date_id(end_date)}"

    sales_options = (
        User.query.filter(User.role.in_(SALES_ROLES)).order_by(User.username.asc()).all()
    )
    customer_options = Pelanggan.query.order_by(Pelanggan.nama.asc()).all()

    return render_template(
        "laporan_penjualan.html",
        summary_cards=summary_cards,
        insight_cards=insight_cards,
        top_products=top_products,
        top_customers=top_customers,
        daily_points=daily_points,
        monthly_breakdown=monthly_breakdown,
        totals=totals,
        average_order=average_order,
        margin_percent=margin_percent,
        range_label=range_label,
        filter_values=filter_values,
        sales_options=sales_options,
        customer_options=customer_options,
        largest_invoice=largest_invoice,
        transaction_details=transaction_details,
    )


@bp.route("/api/laporan/penjualan/suggest", methods=["GET"])
@login_required
@roles_required(*SALES_ROLES)
def laporan_penjualan_suggest():
    term = (request.args.get("q") or "").strip()
    if len(term) < 2:
        return jsonify({"results": []})

    today = datetime.utcnow().date()
    default_start = today.replace(day=1)
    start_date = _parse_date_param(request.args.get("start_date")) or default_start
    end_date = _parse_date_param(request.args.get("end_date")) or today
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    like = f"%{term}%"
    results = []

    invoice_rows = (
        Penjualan.query.options(joinedload(Penjualan.pelanggan))
        .filter(Penjualan.tanggal_penjualan >= start_date)
        .filter(Penjualan.tanggal_penjualan <= end_date)
        .filter(Penjualan.no_faktur.ilike(like))
        .order_by(Penjualan.tanggal_penjualan.desc(), Penjualan.id.desc())
        .limit(6)
        .all()
    )
    for sale in invoice_rows:
        customer_name = sale.pelanggan.nama if sale.pelanggan else "Pelanggan umum"
        date_label = (
            _format_date_id(sale.tanggal_penjualan)
            if sale.tanggal_penjualan
            else "-"
        )
        results.append(
            {
                "kind": "faktur",
                "label": sale.no_faktur,
                "value": sale.no_faktur,
                "subtext": f"{date_label} • {customer_name}",
            }
        )

    customer_rows = (
        Pelanggan.query.join(Pelanggan.penjualan)
        .filter(Penjualan.tanggal_penjualan >= start_date)
        .filter(Penjualan.tanggal_penjualan <= end_date)
        .filter(Pelanggan.nama.ilike(like))
        .distinct()
        .order_by(Pelanggan.nama.asc())
        .limit(6)
        .all()
    )
    for customer in customer_rows:
        subtext_parts = [customer.pelanggan_id]
        if customer.kontak:
            subtext_parts.append(customer.kontak)
        results.append(
            {
                "kind": "pelanggan",
                "label": customer.nama,
                "value": customer.nama,
                "subtext": " • ".join([p for p in subtext_parts if p]),
            }
        )

    staff_rows = (
        User.query.join(User.penjualan)
        .filter(Penjualan.tanggal_penjualan >= start_date)
        .filter(Penjualan.tanggal_penjualan <= end_date)
        .filter(User.username.ilike(like))
        .distinct()
        .order_by(User.username.asc())
        .limit(6)
        .all()
    )
    for staff in staff_rows:
        role_label = (staff.role or "").strip()
        results.append(
            {
                "kind": "sales",
                "label": staff.username,
                "value": staff.username,
                "subtext": role_label,
            }
        )

    return jsonify({"results": results})


@bp.route("/api/get_product1", methods=["GET"])
@login_required
@roles_required(*ALL_ROLE_CHOICES)
def get_product1():
    product_id = request.args.get("product_id")
    product = Produk.query.get(product_id)

    if product:
        return jsonify(
            {
                "success": True,
                "id": product.id,
                "nama_produk": product.nama_produk,
                "kode_produk": product.kode_produk,
                "harga": product.harga,
            }
        )
    return jsonify({"success": False, "message": "Produk tidak ditemukan."}), 404


@bp.route("/sales_staff", methods=["GET", "POST"])
@login_required
@roles_required(*ADMIN_ONLY)
def sales_staff():
    role_choices = [
        {"value": ROLE_ADMIN, "label": "Admin"},
        {"value": ROLE_KASIR, "label": "Kasir"},
        {"value": ROLE_SALES, "label": "Sales"},
        {"value": ROLE_GUDANG, "label": "Gudang"},
    ]
    role_labels = {choice["value"]: choice["label"] for choice in role_choices}

    form_errors = {}
    edit_user = None
    if request.method == "GET":
        edit_id = request.args.get("edit", type=int)
        if edit_id:
            edit_user = User.query.get(edit_id)

    def _default_form_values():
        return {"username": "", "email": "", "role": ROLE_SALES}

    if request.method == "POST":
        form_values = {
            "username": (request.form.get("username", "") or "").strip(),
            "email": (request.form.get("email", "") or "").strip(),
            "role": (request.form.get("role", ROLE_SALES) or ROLE_SALES).lower(),
        }
    elif edit_user:
        form_values = {
            "username": edit_user.username or "",
            "email": edit_user.email or "",
            "role": (edit_user.role or ROLE_SALES).lower(),
        }
    else:
        form_values = _default_form_values()

    if request.method == "POST":
        username = form_values["username"]
        email = form_values["email"]
        password = request.form.get("password", "").strip()
        role = (form_values["role"] or "sales").lower()
        if role not in role_labels:
            role = "sales"
        edit_id = request.form.get("user_id")
        is_edit = bool(edit_id)
        target_user = None

        if is_edit:
            try:
                target_user = User.query.get(int(edit_id))
            except (TypeError, ValueError):
                target_user = None
            if not target_user:
                flash("Pengguna yang akan diubah tidak ditemukan.", "warning")
                return redirect(url_for("main.sales_staff"))
            edit_user = target_user

        if not username:
            form_errors["username"] = "Nama login wajib diisi."
        else:
            existing_username = (
                User.query.filter(func.lower(User.username) == username.lower())
                .filter(User.id != (target_user.id if target_user else 0))
                .first()
            )
            if existing_username:
                form_errors["username"] = "Nama login sudah digunakan."

        if not email:
            form_errors["email"] = "Email wajib diisi."
        else:
            existing_email = (
                User.query.filter(func.lower(User.email) == email.lower())
                .filter(User.id != (target_user.id if target_user else 0))
                .first()
            )
            if existing_email:
                form_errors["email"] = "Email sudah terdaftar."

        if is_edit:
            # Password opsional saat edit
            if password and len(password) < 6:
                form_errors["password"] = "Password minimal 6 karakter."
        else:
            if not password or len(password) < 6:
                form_errors["password"] = "Password minimal 6 karakter."

        if not form_errors:
            if is_edit and target_user:
                target_user.username = username
                target_user.email = email
                target_user.role = role
                if password:
                    target_user.password = generate_password_hash(
                        password, method="pbkdf2:sha256", salt_length=8
                    )
                db.session.commit()
                flash("Pengguna berhasil diperbarui.", "success")
                return redirect(url_for("main.sales_staff"))
            else:
                hashed_password = generate_password_hash(
                    password, method="pbkdf2:sha256", salt_length=8
                )
                new_user = User(
                    username=username, email=email, password=hashed_password, role=role
                )
                db.session.add(new_user)
                db.session.commit()
                flash(
                    f"Pengguna {role_labels.get(role, role)} baru berhasil ditambahkan.",
                    "success",
                )
                return redirect(url_for("main.sales_staff"))

    staff_query = (
        db.session.query(
            User,
            func.count(Penjualan.id).label("orders"),
            func.coalesce(func.sum(Penjualan.total_harga), 0).label("revenue"),
        )
        .outerjoin(Penjualan, Penjualan.sales_id == User.id)
        .filter(User.role.in_([choice["value"] for choice in role_choices]))
        .group_by(User.id)
        .order_by(User.username.asc())
    )
    staff_rows = staff_query.all()

    role_breakdown = {
        role["value"]: db.session.query(func.count(User.id))
        .filter(User.role == role["value"])
        .scalar()
        or 0
        for role in role_choices
    }
    total_staff = sum(role_breakdown.values())

    total_transactions = sum(orders for _, orders, _ in staff_rows)

    recent_sales = (
        Penjualan.query.options(
            joinedload(Penjualan.pelanggan), joinedload(Penjualan.sales)
        )
        .order_by(Penjualan.tanggal_penjualan.desc(), Penjualan.id.desc())
        .limit(5)
        .all()
    )

    stats_cards = [
        {
            "label": "Total Personel",
            "value": total_staff,
            "icon": "fa-users",
            "accent": "text-primary",
            "description": "Admin, sales, kasir, gudang aktif.",
        },
        {
            "label": "Admin",
            "value": role_breakdown.get(ROLE_ADMIN, 0),
            "icon": "fa-user-shield",
            "accent": "text-danger",
            "description": "Pengelola sistem & konfigurasi.",
        },
        {
            "label": "Sales",
            "value": role_breakdown.get("sales", 0),
            "icon": "fa-user-tie",
            "accent": "text-success",
            "description": "Tim penjualan lapangan.",
        },
        {
            "label": "Kasir",
            "value": role_breakdown.get("kasir", 0),
            "icon": "fa-cash-register",
            "accent": "text-warning",
            "description": "Operator kasir aktif.",
        },
        {
            "label": "Gudang",
            "value": role_breakdown.get(ROLE_GUDANG, 0),
            "icon": "fa-warehouse",
            "accent": "text-info",
            "description": "Pengelola stok & penerimaan barang.",
        },
        {
            "label": "Transaksi tercatat",
            "value": total_transactions,
            "icon": "fa-receipt",
            "accent": "text-info",
            "description": "Akumulasi faktur dari tim.",
        },
    ]

    staff_table = []
    for user, orders, revenue in staff_rows:
        customer_count = db.session.query(
            func.count(func.distinct(Penjualan.pelanggan_id))
        )
        customer_count = (
            customer_count.filter(Penjualan.sales_id == user.id).scalar() or 0
        )
        staff_table.append(
            {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": role_labels.get(user.role, (user.role or "").title()),
                "role_value": user.role or "",
                "orders": orders,
                "revenue": revenue,
                "customers": customer_count,
            }
        )

    return render_template(
        "sales_staff.html",
        stats_cards=stats_cards,
        staff_table=staff_table,
        role_choices=role_choices,
        form_errors=form_errors,
        form_values=form_values,
        edit_user=edit_user,
        recent_sales=recent_sales,
        role_labels=role_labels,
    )


def _build_level_price_tables(price_levels, price_entries, req_args, per_page=8):
    price_table = {}
    price_table_pages = {}

    args_dict = req_args.to_dict() if hasattr(req_args, "to_dict") else dict(req_args)

    def _build_level_page_url(level_id, page_num, fragment=False):
        params = dict(args_dict)
        params[f"page_level_{level_id}"] = page_num
        if fragment:
            params["ajax"] = "1"
            return url_for("main.harga_level_level_fragment", level_id=level_id, **params)
        return url_for("main.harga_level", **params)

    for level in price_levels:
        level_entries = [
            {
                "id": entry.id,
                "product_name": (
                    entry.produk.nama_produk if entry.produk else "Produk dihapus"
                ),
                "product_code": entry.produk.kode_produk if entry.produk else "-",
                "price": entry.price,
            }
            for entry in price_entries
            if entry.level_id == level.id
        ]

        total_entries = len(level_entries)
        total_pages = max(1, math.ceil(total_entries / per_page)) if total_entries else 1
        page_param = f"page_level_{level.id}"
        page = req_args.get(page_param, 1, type=int) if hasattr(req_args, "get") else 1
        if not isinstance(page, int):
            page = 1
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages

        start = (page - 1) * per_page
        end = start + per_page
        price_table[level.id] = level_entries[start:end]

        page_links = [
            {
                "num": num,
                "url": _build_level_page_url(level.id, num, fragment=False),
                "fragment_url": _build_level_page_url(level.id, num, fragment=True),
            }
            for num in range(1, total_pages + 1)
        ]

        price_table_pages[level.id] = {
            "page": page,
            "pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "prev_url": _build_level_page_url(level.id, page - 1, fragment=False)
            if page > 1
            else None,
            "next_url": _build_level_page_url(level.id, page + 1, fragment=False)
            if page < total_pages
            else None,
            "prev_fragment_url": _build_level_page_url(level.id, page - 1, fragment=True)
            if page > 1
            else None,
            "next_fragment_url": _build_level_page_url(level.id, page + 1, fragment=True)
            if page < total_pages
            else None,
            "links": page_links,
            "total": total_entries,
        }

    return price_table, price_table_pages


@bp.route("/harga_level", methods=["GET", "POST"])
@login_required
@roles_required(*INVENTORY_ROLES)
def harga_level():
    action = request.form.get("action") if request.method == "POST" else None
    if action == "create_level":
        name = (request.form.get("level_name") or "").strip()
        description = (request.form.get("description") or "").strip()
        if not name:
            flash("Nama level harga wajib diisi.", "warning")
        elif PriceLevel.query.filter(
            func.lower(PriceLevel.name) == name.lower()
        ).first():
            flash("Nama level sudah digunakan.", "warning")
        else:
            new_level = PriceLevel(name=name, description=description)
            db.session.add(new_level)
            db.session.commit()
            flash("Level harga baru berhasil ditambahkan.", "success")
        return redirect(url_for("main.harga_level"))

    if action == "set_price":
        level_id = request.form.get("level_id")
        product_id = request.form.get("product_id")
        price_raw = request.form.get("price")
        try:
            level_id_int = int(level_id)
            product_id_int = int(product_id)
            price_value = float(price_raw)
        except (TypeError, ValueError):
            flash("Pastikan level, produk, dan harga valid.", "warning")
            return redirect(url_for("main.harga_level"))

        if price_value < 0:
            flash("Harga tidak boleh negatif.", "warning")
            return redirect(url_for("main.harga_level"))

        level = PriceLevel.query.get(level_id_int)
        product = Produk.query.get(product_id_int)
        if not level or not product:
            flash("Level atau produk tidak ditemukan.", "warning")
            return redirect(url_for("main.harga_level"))

        entry = ProductPriceLevel.query.filter_by(
            product_id=product_id_int, level_id=level_id_int
        ).first()
        if entry:
            entry.price = price_value
        else:
            entry = ProductPriceLevel(
                product_id=product_id_int, level_id=level_id_int, price=price_value
            )
            db.session.add(entry)
        db.session.commit()
        flash(
            f"Harga khusus untuk {product.nama_produk} ({level.name}) tersimpan.",
            "success",
        )
        return redirect(url_for("main.harga_level"))

    if action == "delete_price":
        entry_id = request.form.get("entry_id")
        try:
            entry_int = int(entry_id)
        except (TypeError, ValueError):
            entry_int = None
        if entry_int:
            entry = ProductPriceLevel.query.get(entry_int)
            if entry:
                db.session.delete(entry)
                db.session.commit()
                flash("Harga khusus dihapus.", "success")
        return redirect(url_for("main.harga_level"))

    if action == "create_cost":
        level_id = request.form.get("cost_level_id")
        name = (request.form.get("cost_name") or "").strip()
        cost_type = request.form.get("cost_type") or "percent"
        value_raw = request.form.get("cost_value")
        active_flag = request.form.get("cost_active") == "1"

        try:
            level_id_int = int(level_id)
            value = float(value_raw)
        except (TypeError, ValueError):
            flash("Pastikan level dan nilai biaya valid.", "warning")
            return redirect(url_for("main.harga_level"))

        if value < 0:
            flash("Nilai biaya tidak boleh negatif.", "warning")
            return redirect(url_for("main.harga_level"))

        level = PriceLevel.query.get(level_id_int)
        if not level:
            flash("Level harga tidak ditemukan.", "warning")
            return redirect(url_for("main.harga_level"))

        new_cost = PriceLevelCost(
            level_id=level_id_int,
            name=name or "Biaya baru",
            type="percent" if cost_type not in ("nominal", "percent") else cost_type,
            value=value,
            is_active=active_flag,
        )
        db.session.add(new_cost)
        db.session.commit()
        flash("Biaya baru berhasil ditambahkan.", "success")
        return redirect(url_for("main.harga_level"))

    if action == "toggle_cost":
        entry_id = request.form.get("cost_id")
        try:
            entry_int = int(entry_id)
        except (TypeError, ValueError):
            entry_int = None
        if entry_int:
            cost_entry = PriceLevelCost.query.get(entry_int)
            if cost_entry:
                cost_entry.is_active = not cost_entry.is_active
                db.session.commit()
                status = "diaktifkan" if cost_entry.is_active else "dinonaktifkan"
                flash(f"Biaya {cost_entry.name} {status}.", "success")
        return redirect(url_for("main.harga_level"))

    if action == "delete_cost":
        entry_id = request.form.get("cost_id")
        try:
            entry_int = int(entry_id)
        except (TypeError, ValueError):
            entry_int = None
        if entry_int:
            cost_entry = PriceLevelCost.query.get(entry_int)
            if cost_entry:
                db.session.delete(cost_entry)
                db.session.commit()
                flash(f"Biaya {cost_entry.name} dihapus.", "success")
        return redirect(url_for("main.harga_level"))

    price_levels = PriceLevel.query.order_by(PriceLevel.name.asc()).all()
    price_entries = (
        ProductPriceLevel.query.options(
            joinedload(ProductPriceLevel.produk), joinedload(ProductPriceLevel.level)
        )
        .order_by(ProductPriceLevel.level_id.asc(), ProductPriceLevel.product_id.asc())
        .all()
    )

    level_summary = []
    for level in price_levels:
        level_summary.append(
            {
                "id": level.id,
                "name": level.name,
                "description": level.description,
                "customer_count": len(level.pelanggan),
                "price_count": sum(
                    1 for entry in price_entries if entry.level_id == level.id
                ),
            }
        )

    price_table, price_table_pages = _build_level_price_tables(
        price_levels, price_entries, request.args, per_page=8
    )

    cost_entries = (
        PriceLevelCost.query.options(joinedload(PriceLevelCost.level))
        .order_by(PriceLevelCost.level_id.asc(), PriceLevelCost.name.asc())
        .all()
    )
    price_level_costs = {}
    for cost in cost_entries:
        price_level_costs.setdefault(cost.level_id, []).append(cost)

    return render_template(
        "harga_level.html",
        price_levels=price_levels,
        level_summary=level_summary,
        price_table=price_table,
        price_table_pages=price_table_pages,
        price_level_costs=price_level_costs,
    )


@bp.route("/harga_level/level/<int:level_id>")
@login_required
@roles_required(*INVENTORY_ROLES)
def harga_level_level_fragment(level_id):
    price_levels = PriceLevel.query.order_by(PriceLevel.name.asc()).all()
    price_entries = (
        ProductPriceLevel.query.options(
            joinedload(ProductPriceLevel.produk), joinedload(ProductPriceLevel.level)
        )
        .order_by(ProductPriceLevel.level_id.asc(), ProductPriceLevel.product_id.asc())
        .all()
    )

    level_lookup = {level.id: level for level in price_levels}
    level = level_lookup.get(level_id)
    if not level:
        return jsonify({"error": "Level tidak ditemukan"}), 404

    price_table, price_table_pages = _build_level_price_tables(
        price_levels, price_entries, request.args, per_page=8
    )

    entries = price_table.get(level_id, [])
    page_info = price_table_pages.get(level_id, {})

    if request.args.get("ajax") == "1":
        return render_template(
            "partials/level_price_table.html",
            entries=entries,
            page_info=page_info,
            level=level,
        )

    return redirect(url_for("main.harga_level", **request.args.to_dict()))
