# app/routes/perm_admin.py
from __future__ import annotations
from typing import Dict, Any, List
from functools import wraps

from flask import Blueprint, render_template, request, abort, redirect, url_for
from flask_login import login_required, current_user

from app.permissions import (
    role_of, flags_all,
    grant, revoke, set_flag,
)
from app.permissions import _load_perms as _all_perms

try:
    from app.models import db, User
except Exception:
    db, User = None, None

perms_bp = Blueprint("perms_admin", __name__, url_prefix="/admin/perms")


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if role_of(current_user) != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def _roles_from_users() -> List[str]:
    if not (db and User):
        return []
    q = db.session.query(User.role).distinct().all()
    roles = [((r[0] or "").strip().lower()) for r in q]
    return sorted(set([r for r in roles if r]))


@perms_bp.route("/", methods=["GET"])
@login_required
@admin_required
def page():
    all_perms: Dict[str, Dict[str, bool]] = _all_perms()
    admin_perms = sorted(list(all_perms.get("admin", {}).keys()))

    roles = sorted(set(list(all_perms.keys()) + _roles_from_users()))
    roles = ["admin"] + [r for r in roles if r != "admin"]

    table: Dict[str, Dict[str, bool]] = {}
    for role in roles:
        role_map = all_perms.get(role, {})
        table[role] = {p: bool(role_map.get(p, False)) for p in admin_perms}

    return render_template(
        "admin/perms.html",
        roles=roles,
        admin_perms=admin_perms,
        table=table,
        flags=flags_all(),
    )


# ---------- URL tabanlı işlemler ----------

@perms_bp.route("/toggle/<role>/<perm>/<int:value>")
@login_required
@admin_required
def toggle(role, perm, value):
    role = role.strip().lower()
    perm = perm.strip()
    if role == "admin" and not value:
        abort(400, "admin yetkileri kapatılamaz")

    if value:
        grant(role, perm, True)
    else:
        revoke(role, perm)
    return redirect(url_for("perms_admin.page"))

@perms_bp.route("/flag/<key>/<int:value>")
@login_required
@admin_required
def toggle_flag(key, value):
    key = key.strip()
    set_flag(key, bool(value))
    return redirect(url_for("perms_admin.page"))

# --- formdan rol ekleme (POST) ---
@perms_bp.route("/role/add", methods=["POST"])
@login_required
@admin_required
def add_role_form():
    role = (request.form.get("role") or "").strip().lower()
    if not role or role == "admin":
        abort(400, "Geçersiz rol")
    # Kayıt ilk toggle'da oluşacak; burada sadece geri dönüyoruz
    return redirect(url_for("perms_admin.page"))

# --- formdan izin ekleme (POST) ---
@perms_bp.route("/perm/add", methods=["POST"])
@login_required
@admin_required
def add_perm_form():
    perm = (request.form.get("perm") or "").strip()
    add_to_admin = bool(request.form.get("add_to_admin"))
    if not perm:
        abort(400, "Geçersiz izin")
    if add_to_admin:
        grant("admin", perm, True)
    return redirect(url_for("perms_admin.page"))

# --- formdan flag ekleme/açma (POST) ---
@perms_bp.route("/flag/add", methods=["POST"])
@login_required
@admin_required
def add_flag_form():
    key = (request.form.get("key") or "").strip()
    if not key:
        abort(400, "Geçersiz flag anahtarı")
    set_flag(key, True)  # oluşturur veya açar
    return redirect(url_for("perms_admin.page"))
