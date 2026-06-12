from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from sqlalchemy import func, update
from datetime import datetime
from app.models import db, Product, OrderItem
from pytz import timezone
from app.permissions import require

urun_bp = Blueprint('urun', __name__)
TR = timezone("Europe/Istanbul")

def _guard_roles(*roles):
    return current_user.role in roles

# ---- küçük yardımcılar ----
def _get_bool(val):
    if val is None:
        return None
    s = str(val).strip().lower()
    return s in ("1", "true", "on", "yes")

def _get_float_or_none(val):
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(val)
    except Exception:
        return None

def _get_int_or_none(val):
    if val is None or str(val).strip() == "":
        return None
    try:
        return int(val)
    except Exception:
        return None

@urun_bp.route('/admin/urunler')
@login_required
@require('ürün-listesi')
def urun_listesi():
    show = (request.args.get('show') or '').lower()  # "" | "all" | "archived"
    base_q = Product.query

    if show == 'archived':
        urunler = base_q.filter(Product.is_active == False).all()
    elif show == 'all':
        urunler = base_q.all()
    else:
        # varsayılan: sadece aktifler
        urunler = base_q.filter(Product.is_active == True).all()

    panels = [r[0] for r in (db.session.query(Product.visible_for)
                             .filter(Product.visible_for.isnot(None))
                             .distinct()
                             .order_by(Product.visible_for.asc())
                             .all()) if r[0]]

    return render_template('admin/urunler.html', urunler=urunler, panels=panels, show=show)

@urun_bp.route('/urun/ekle', methods=['GET', 'POST'])
@login_required
@require('ürün-ekle')
def urun_ekle():
    if current_user.role not in ['admin', 'cashier']:
        flash("Yetkisiz erişim", "danger")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        name         = request.form.get('name')
        price        = _get_float_or_none(request.form.get('price'))
        category     = request.form.get('category')
        sub_category = request.form.get('sub_category')
        stock_raw    = request.form.get('stock', '').strip()
        stock        = int(stock_raw) if stock_raw else 0
        visible_for  = request.form.get('visible_for')

        # --- saatlik alanlar (opsiyonel) ---
        is_timed          = _get_bool(request.form.get('is_timed'))
        hourly_rate       = _get_float_or_none(request.form.get('hourly_rate'))
        initial_minutes   = _get_int_or_none(request.form.get('initial_minutes'))
        price_round_inc   = _get_float_or_none(request.form.get('price_round_inc'))
        auto_start_on_add = _get_bool(request.form.get('auto_start_on_add'))

        # Validasyon: saatlik işaretliyse zorunlu alanlar
        if is_timed is True:
            if not hourly_rate or hourly_rate <= 0:
                flash("Saatlik ürün için 'Saatlik Ücret' zorunlu ve 0'dan büyük olmalı.", "danger")
                return redirect(url_for('urun.urun_ekle'))
            # initial_minutes/price_round_inc/auto_start_on_add boş olabilir (senin talebine göre default yok)

        yeni_urun = Product(
            name=name,
            price=price if price is not None else 0.0,
            category=category,
            sub_category=sub_category,
            stock=stock,
            visible_for=visible_for,
            # saatlik alanlar: normal üründe None kalır
            is_timed=is_timed,
            hourly_rate=hourly_rate if is_timed else None,
            initial_minutes=initial_minutes if is_timed else None,
            price_round_inc=price_round_inc if is_timed else None,
            auto_start_on_add=auto_start_on_add if is_timed else None,
        )
        db.session.add(yeni_urun)
        db.session.commit()

        flash("Ürün eklendi tabiki Babayiğit", "success")
        return redirect(url_for('urun.urun_ekle'))

    if request.method == 'GET':
        panels = [r[0] for r in db.session.query(Product.visible_for)
                                    .filter(Product.visible_for.isnot(None))
                                    .distinct()
                                    .order_by(Product.visible_for.asc())
                                    .all()]
    return render_template('admin/urun_ekle.html', panels=panels)

@urun_bp.route('/admin/urun/sil/<int:id>')
@login_required
@require('ürün-sil')
def urun_sil(id):

    urun = Product.query.get_or_404(id)

    try:
        urun.is_active = False
        urun.deleted_at = datetime.now(TR)
        db.session.commit()
        flash(f"‘{urun.name}’ arşive alındı.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Arşivleme sırasında hata: {e}", "danger")

    return redirect(url_for('urun.urun_listesi'))

@urun_bp.route('/urun/duzenle/<int:urun_id>', methods=['GET', 'POST'])
@login_required
@require('ürün-düzenle')
def urun_duzenle(urun_id):
    if current_user.role not in ['admin', 'cashier']:
        flash("Yetkisiz erişim", "danger")
        return redirect(url_for('auth.login'))

    urun = Product.query.get_or_404(urun_id)

    if request.method == 'POST':
        urun.name         = request.form.get('name')
        urun.price        = _get_float_or_none(request.form.get('price')) or 0.0
        urun.category     = request.form.get('category')
        urun.sub_category = request.form.get('sub_category')
        stock_raw         = request.form.get('stock', '').strip()
        urun.stock        = int(stock_raw) if stock_raw else 0
        urun.visible_for  = request.form.get('visible_for')

        # saatlik alanlar (opsiyonel)
        is_timed_form          = _get_bool(request.form.get('is_timed'))
        hourly_rate_form       = _get_float_or_none(request.form.get('hourly_rate'))
        initial_minutes_form   = _get_int_or_none(request.form.get('initial_minutes'))
        price_round_inc_form   = _get_float_or_none(request.form.get('price_round_inc'))
        auto_start_on_add_form = _get_bool(request.form.get('auto_start_on_add'))

        if is_timed_form is True:
            if not hourly_rate_form or hourly_rate_form <= 0:
                flash("Saatlik ürün için 'Saatlik Ücret' zorunlu ve 0'dan büyük olmalı.", "danger")
                return redirect(url_for('urun.urun_duzenle', urun_id=urun.id))

            urun.is_timed          = True
            urun.hourly_rate       = hourly_rate_form
            urun.initial_minutes   = initial_minutes_form
            urun.price_round_inc   = price_round_inc_form
            urun.auto_start_on_add = auto_start_on_add_form
        else:
            # saatlik değil olarak işaretlendiyse alanları temizle (None)
            urun.is_timed          = None
            urun.hourly_rate       = None
            urun.initial_minutes   = None
            urun.price_round_inc   = None
            urun.auto_start_on_add = None

        db.session.commit()
        flash("Ürün güncellendi", "success")
        return redirect(url_for('urun.urun_listesi'))

    panels = [r[0] for r in db.session.query(Product.visible_for)
                            .filter(Product.visible_for.isnot(None))
                            .distinct()
                            .order_by(Product.visible_for.asc())
                            .all()]

    return render_template('admin/urun_guncelle.html', urun=urun, panels=panels)
