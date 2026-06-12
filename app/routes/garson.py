# app/routes/garson.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from sqlalchemy import func
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import exists, or_
from app.models import db, User, Order, OrderItem, PartialPayment, StaffShift

waiter_bp = Blueprint('waiter', __name__)

def _guard_admin_cashier():
    if getattr(current_user, "role", None) not in ['admin', 'cashier']:
        flash("Yetkisiz erişim", "danger")
        return False
    return True


@waiter_bp.route('/admin/garsonlar')
@login_required
def waiter_list():
    if not _guard_admin_cashier():
        return redirect(url_for('auth.login'))

    garsonlar = User.query.filter_by(role='waiter').order_by(User.username.asc()).all()
    return render_template('admin/garson_listesi.html', garsonlar=garsonlar)


@waiter_bp.route('/admin/garson/ekle', methods=['GET', 'POST'])
@login_required
def waiter_add():
    if not _guard_admin_cashier():
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '').strip()

        if not username or not password:
            flash("Kullanıcı adı ve şifre zorunludur", "warning")
            return redirect(request.url)

        if User.query.filter_by(username=username).first():
            flash("Bu kullanıcı adı zaten alınmış", "warning")
            return redirect(request.url)

        yeni = User(
            username=username,
            password=generate_password_hash(password),  # hash’liyoruz
            role='waiter',
            is_on_shift=False  # varsayılan kapalı
        )
        db.session.add(yeni)
        db.session.commit()
        flash("Garson eklendi", "success")
        return redirect(url_for('waiter.waiter_list'))

    return render_template('admin/garson_ekle.html')


@waiter_bp.route('/admin/garson/<int:waiter_id>/sifre', methods=['GET', 'POST'])
@login_required
def waiter_reset_password(waiter_id):
    if not _guard_admin_cashier():
        return redirect(url_for('auth.login'))

    waiter = User.query.filter_by(id=waiter_id, role='waiter').first_or_404()

    if request.method == 'POST':
        new_password = (request.form.get('password') or '').strip()
        if not new_password:
            flash("Şifre boş olamaz", "warning")
            return redirect(request.url)

        waiter.password = generate_password_hash(new_password)
        db.session.commit()
        flash("Şifre güncellendi", "success")
        return redirect(url_for('waiter.waiter_list'))

    return render_template('admin/garson_sifre_guncelle.html', waiter=waiter)


@waiter_bp.route('/admin/garson/<int:waiter_id>/sil', methods=['POST'])
@login_required
def waiter_delete(waiter_id):
    if not _guard_admin_cashier():
        flash("Yetkiniz yok.", "danger")
        return redirect(url_for('auth.login'))

    waiter = (db.session.query(User)
              .filter(User.id == waiter_id, User.role == 'waiter'))
    u = waiter.first()
    if not u:
        flash("Garson bulunamadı.", "warning")
        return redirect(url_for('waiter.waiter_list'))

    # Aktif mesaiyi kapat (varsa), yoksa FK hatası almayız ama mantıksal olarak kapatalım
    if u.is_on_shift:
        u.is_on_shift = False
        try:
            db.session.flush()
        except Exception:
            db.session.rollback()
            flash("Mesai durumu güncellenemedi.", "danger")
            return redirect(url_for('waiter.waiter_list'))

    try:
        # --- 1) Garsona ait tüm referansları NULL'a çek ---
        # Orders: served_by / opened_by
        (db.session.query(Order)
           .filter(Order.served_by_user_id == u.id)
           .update({Order.served_by_user_id: None}, synchronize_session=False))
        (db.session.query(Order)
           .filter(Order.opened_by_user_id == u.id)
           .update({Order.opened_by_user_id: None}, synchronize_session=False))

        # OrderItems: added_by
        (db.session.query(OrderItem)
           .filter(OrderItem.added_by_user_id == u.id)
           .update({OrderItem.added_by_user_id: None}, synchronize_session=False))

        # PartialPayments: cashier_user_id
        (db.session.query(PartialPayment)
           .filter(PartialPayment.cashier_user_id == u.id)
           .update({PartialPayment.cashier_user_id: None}, synchronize_session=False))

        # --- 2) Mesai kayıtlarını (tarihçeyi) tamamen sil ---
        db.session.query(StaffShift).filter(StaffShift.user_id == u.id).delete(synchronize_session=False)

        # --- 3) Kullanıcıyı sil ---
        db.session.delete(u)
        db.session.commit()
        flash("Garson ve tarihçesi silindi.", "success")

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("waiter_force_delete SQLAlchemyError: %s", e)
        flash("Garson silinemedi. Lütfen tekrar deneyin.", "danger")
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("waiter_force_delete Exception: %s", e)
        flash("Beklenmeyen bir hata oluştu.", "danger")

    return redirect(url_for('waiter.waiter_list'))

# --- Mesai Toggle: Başlat/Bitir ---
@waiter_bp.route('/garson/<int:waiter_id>/mesai', methods=['POST'], endpoint="waiter_shift_toggle")
@login_required
def waiter_shift_toggle(waiter_id):
    if not _guard_admin_cashier():
        return redirect(url_for('auth.login'))

    waiter = User.query.filter_by(id=waiter_id, role='waiter').first_or_404()

    now = datetime.utcnow()

    if not waiter.is_on_shift:
        # Başlat: yeni shift oluştur
        new_shift = StaffShift(user_id=waiter.id, start_at=now, end_at=None)
        db.session.add(new_shift)
        waiter.is_on_shift = True
        db.session.commit()
        flash(f"{waiter.username} için mesai BAŞLADI.", "success")
    else:
        # Bitir: açık vardiyayı kapat
        active_shift = StaffShift.query.filter_by(user_id=waiter.id, end_at=None).order_by(StaffShift.id.desc()).first()
        if active_shift is None:
            # Koruma: flag açık ama kayıt yoksa yine de bayrağı kapat
            waiter.is_on_shift = False
            db.session.commit()
            flash("Açık mesai kaydı bulunamadı; durum kapatıldı.", "warning")
        else:
            active_shift.end_at = now
            waiter.is_on_shift = False
            db.session.commit()
            flash(f"{waiter.username} için mesai BİTTİ.", "info")

    next_url = request.referrer or url_for('waiter.waiter_list')
    return redirect(next_url)
