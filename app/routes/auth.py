from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User, db, Order
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/old_home')
def home():
    return render_template('index.html')


# ----------------------------
# LOGIN
# ----------------------------
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            role = (user.role or "").lower()

            # Eğer waiter ise mesai kontrolü
            if role == "waiter":
                # Mesai kapalı → girişe izin verme
                if not user.is_on_shift:
                    flash("Mesai başlatılmadan giriş yapılamaz.", "warning")
                    return redirect(request.url)

            # Giriş başarılı → last_login güncelle
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user)
            flash("Giriş başarılı", "success")

            # Rolüne göre yönlendir

            if role in ["admin", "cashier", "cashier-lite"]:
                return redirect(url_for("dashboard.dashboard"))
            elif role == "waiter":
                return redirect(url_for("dashboard.dashboard"))  # waiter dashboard’un zaten sipariş ekranını açıyor
            elif role in ["bar", "kitchen", "nargile"]:
                return redirect(url_for("dashboard.dashboard", panel="station"))
            else:
                return redirect(url_for("dashboard.dashboard"))

        # Kullanıcı adı veya şifre yanlış
        flash("Kullanıcı adı veya şifre hatalı.", "danger")
        return redirect(request.url)

    return render_template('login.html')


# ----------------------------
# LOGOUT
# ----------------------------
@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Çıkış yapıldı", "info")
    return redirect(url_for('auth.login'))

@auth_bp.route("/change-password", methods=["POST"])
@login_required
def change_password():
    # Sadece yeni şifre alanlarını alıyoruz
    new_pw = (request.form.get("new_password") or "").strip()
    new_pw2 = (request.form.get("new_password_confirm") or "").strip()

    # 1. Boş alan kontrolü
    if not new_pw or not new_pw2:
        flash("Lütfen tüm alanları doldurun.", "warning")
        return redirect(request.referrer or url_for("dashboard.dashboard"))

    # 2. Şifre eşleşme kontrolü
    if new_pw != new_pw2:
        flash("Yeni şifre ile tekrarı aynı değil.", "warning")
        return redirect(request.referrer or url_for("dashboard.dashboard"))

    # 3. Uzunluk kontrolü
    if len(new_pw) < 6:
        flash("Yeni şifre en az 6 karakter olmalı.", "warning")
        return redirect(request.referrer or url_for("dashboard.dashboard"))

    # 4. Yeni şifreyi kaydetme
    try:
        # Eğer User modelinizde set_password metodu varsa onu kullanır
        if hasattr(current_user, "set_password"):
            current_user.set_password(new_pw)
        else:
            # Yoksa manuel olarak hash'leme yapar (Werkzeug kullanarak)
            from werkzeug.security import generate_password_hash
            
            if hasattr(current_user, "password_hash"):
                current_user.password_hash = generate_password_hash(new_pw)
            elif hasattr(current_user, "password"):
                current_user.password = generate_password_hash(new_pw)
            else:
                flash("Modelde şifre alanı bulunamadı.", "danger")
                return redirect(request.referrer or url_for("dashboard.dashboard"))

        db.session.add(current_user)
        db.session.commit()
        flash("Şifreniz başarıyla güncellendi.", "success")

    except Exception as e:
        db.session.rollback()
        flash("Bir hata oluştu, lütfen tekrar deneyin.", "danger")
        print(f"Hata: {e}") # Debug için terminale yazdırır

    return redirect(request.referrer or url_for("dashboard.dashboard"))