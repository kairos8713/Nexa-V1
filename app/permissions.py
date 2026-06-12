# app/permissions.py
"""
Merkezî izin ve özellik (feature flag) yönetimi.
"""

from __future__ import annotations
import json, time
from typing import Any, Dict, Optional
from functools import wraps

from flask import abort, current_app, redirect, url_for, flash
from flask_login import current_user, logout_user
from sqlalchemy.exc import ProgrammingError, OperationalError

# ---- DB ve AppSetting modelini TEK YERDEN al ----
from app.models import db, AppSetting, Order

# -------------------------------------------------------------------
# Varsayılan izinler ve feature flag'ler
# -------------------------------------------------------------------
DEFAULT_PERMS: Dict[str, Dict[str, bool]] = {
    "admin": {
        "ürün-iptal": True,
        "ödeme-al": True,
        "sipariş-ekle": True,
        "masa-listesi": True,
        "masa-arsivle": True,
        "masa-ekle": True,
        "adisyon-işlemleri": True,
        "ürün-listesi": True,
        "ürün-ekle": True,
        "ürün-sil": True,
        "ürün-düzenle": True,
    }
}

DEFAULT_FLAGS: Dict[str, Any] = {
    "qz_tray_print": True,
    "escpos_cp857": True,
    "instant_cutoff_mode": True,
    "inventory_module": False,
    "reservation_module": False,
}

SETTINGS_KEY_PERMS = "permissions.roles"
SETTINGS_KEY_FLAGS = "permissions.flags"

# -------------------------------------------------------------------
# Basit RAM cache (okumaları azaltır)
# -------------------------------------------------------------------
_cache: Dict[str, Any] = {}
_cache_ttl = 10.0  # saniye
_cache_time: Dict[str, float] = {}

def _cache_get(k: str) -> Optional[Any]:
    t = _cache_time.get(k, 0.0)
    if time.time() - t < _cache_ttl:
        return _cache.get(k)
    return None

def _cache_set(k: str, v: Any) -> None:
    _cache[k] = v
    _cache_time[k] = time.time()

# -------------------------------------------------------------------
# AppSetting yardımcıları (models.py'daki sade model için)
# -------------------------------------------------------------------
def _ensure_table():
    try:
        AppSetting.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        pass

def _appsetting_get(key: str) -> Optional[str]:
    try:
        row = db.session.get(AppSetting, key)
        return row.value if row else None
    except (ProgrammingError, OperationalError):
        return None

def _appsetting_set(key: str, value: str) -> None:
    row = db.session.get(AppSetting, key)
    if row:
        row.value = value
    else:
        row = AppSetting(key=key, value=value)
        db.session.add(row)
    db.session.commit()

# -------------------------------------------------------------------
# JSON get/set yardımcıları
# -------------------------------------------------------------------
def _load_perms() -> Dict[str, Dict[str, bool]]:
    cached = _cache_get(SETTINGS_KEY_PERMS)
    if cached is not None:
        return cached
    _ensure_table()
    raw = _appsetting_get(SETTINGS_KEY_PERMS)
    if not raw:
        _appsetting_set(SETTINGS_KEY_PERMS, json.dumps(DEFAULT_PERMS, ensure_ascii=False))
        _cache_set(SETTINGS_KEY_PERMS, DEFAULT_PERMS)
        return DEFAULT_PERMS
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
    except Exception:
        data = DEFAULT_PERMS
    _cache_set(SETTINGS_KEY_PERMS, data)
    return data

def _save_perms(perms: Dict[str, Dict[str, bool]]) -> None:
    _ensure_table()
    _appsetting_set(SETTINGS_KEY_PERMS, json.dumps(perms, ensure_ascii=False))
    _cache_set(SETTINGS_KEY_PERMS, perms)
    current_app.logger.info("[perms] saved: %s", list(perms.keys()))

def _load_flags() -> Dict[str, Any]:
    cached = _cache_get(SETTINGS_KEY_FLAGS)
    if cached is not None:
        return cached
    _ensure_table()
    raw = _appsetting_get(SETTINGS_KEY_FLAGS)
    if not raw:
        _appsetting_set(SETTINGS_KEY_FLAGS, json.dumps(DEFAULT_FLAGS, ensure_ascii=False))
        _cache_set(SETTINGS_KEY_FLAGS, DEFAULT_FLAGS)
        return DEFAULT_FLAGS
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
    except Exception:
        data = DEFAULT_FLAGS
    _cache_set(SETTINGS_KEY_FLAGS, data)
    return data

def _save_flags(flags: Dict[str, Any]) -> None:
    _ensure_table()
    _appsetting_set(SETTINGS_KEY_FLAGS, json.dumps(flags, ensure_ascii=False))
    _cache_set(SETTINGS_KEY_FLAGS, flags)

# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------
def role_of(user) -> str:
    # kritik: boşlukları temizle
    return ((getattr(user, "role", "") or "").strip().lower())

def perms_for(user=None) -> Dict[str, bool]:
    user = user or current_user
    return _load_perms().get(role_of(user), {})

def flags_all() -> Dict[str, Any]:
    return _load_flags()

def can(user_or_perm, maybe_perm: Optional[str] = None) -> bool:
    if isinstance(user_or_perm, str):
        user = current_user
        perm = user_or_perm
    else:
        user = user_or_perm
        perm = maybe_perm or ""
    if not perm:
        return False
    role = role_of(user)
    perms = _load_perms()
    return bool(perms.get(role, {}).get(perm, False))

def feature(key: str) -> bool:
    return bool(_load_flags().get(key, False))

def require(perm: str):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not can(perm):
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return deco

# Yönetim API'leri
def grant(role: str, perm: str, value: bool = True) -> Dict[str, Dict[str, bool]]:
    perms = _load_perms()
    role = (role or "").strip().lower()
    perms.setdefault(role, {})
    perms[role][perm] = bool(value)
    _save_perms(perms)
    return perms

def revoke(role: str, perm: str) -> Dict[str, Dict[str, bool]]:
    perms = _load_perms()
    role = (role or "").strip().lower()
    if role in perms and perm in perms[role]:
        perms[role].pop(perm)
        _save_perms(perms)
    return perms

def set_flag(key: str, value: Any) -> Dict[str, Any]:
    flags = _load_flags()
    flags[key] = value
    _save_flags(flags)
    return flags

def reset_defaults() -> None:
    _save_perms(DEFAULT_PERMS)
    _save_flags(DEFAULT_FLAGS)

# -------------------------------------------------------------------
# Flask entegrasyonu
# -------------------------------------------------------------------
def init_app(app):
    @app.before_request
    def _ensure_defaults_and_shift():
        try:
            _ensure_table()
            _load_perms()
            _load_flags()
        except Exception as e:
            app.logger.warning(f"[permissions] init defaults skipped: {e}")

        # ---- Mesai kontrolü ----
        if current_user and current_user.is_authenticated:
            role = (getattr(current_user, "role", "") or "").lower()
            if role == "waiter":
                if not getattr(current_user, "is_on_shift", False):
                    # Garson mesaisi kapalıysa: açık hesabı var mı?
                    open_orders = Order.query.filter_by(
                        served_by_user_id=current_user.id,
                        is_completed=False
                    ).count()

                    # logout + engelle
                    logout_user()
                    if open_orders > 0:
                        flash("Mesainiz kapalı ve açık hesabınız var, sistemden çıkarıldınız.", "danger")
                    else:
                        flash("Mesainiz kapalı olduğu için sistemden çıkarıldınız.", "warning")
                    return redirect(url_for("auth.login"))
    @app.before_request
    def _ensure_defaults():
        try:
            _ensure_table()
            _load_perms()
            _load_flags()
        except Exception as e:
            app.logger.warning(f"[permissions] init defaults skipped: {e}")

    # Jinja
    app.jinja_env.globals['can'] = lambda perm: can(perm)
    app.jinja_env.globals['feature'] = lambda key: feature(key)
    app.jinja_env.globals['perms_for'] = lambda: perms_for(current_user)
    app.jinja_env.globals['flags_all'] = lambda: flags_all()

    # CLI
    import click

    @app.cli.command("perms-init")
    def _perms_init():
        reset_defaults()
        click.echo("Permissions & flags reset to defaults.")

    @app.cli.command("perms-show")
    def _perms_show():
        click.echo(json.dumps(_load_perms(), indent=2, ensure_ascii=False))

    @app.cli.command("perms-grant")
    @click.argument("role")
    @click.argument("perm")
    @click.option("--value", type=bool, default=True, help="true/false")
    def _perms_grant(role, perm, value):
        grant(role, perm, value)
        click.echo(f"Granted {perm}={value} to role={role}")

    @app.cli.command("perms-revoke")
    @click.argument("role")
    @click.argument("perm")
    def _perms_revoke(role, perm):
        revoke(role, perm)
        click.echo(f"Revoked {perm} from role={role}")

    @app.cli.command("flags-show")
    def _flags_show():
        click.echo(json.dumps(_load_flags(), indent=2, ensure_ascii=False))

    @app.cli.command("flag-on")
    @click.argument("key")
    def _flag_on(key):
        set_flag(key, True)
        click.echo(f"Flag enabled: {key}")

    @app.cli.command("flag-off")
    @click.argument("key")
    def _flag_off(key):
        set_flag(key, False)
        click.echo(f"Flag disabled: {key}")
