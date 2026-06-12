from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from sqlalchemy import func, and_, literal
from datetime import datetime, timedelta
from pytz import timezone
from sqlalchemy.orm import joinedload
import re

from app.models import (
    db,
    Table,
    Region,
    Order,
    OrderItem,
    Product,
    PartialPayment,
    User,
)

from app import socketio

TR = timezone("Europe/Istanbul")
dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

# ---------- Helpers ----------

def _to_iso_tr(dt):
    if not dt:
        return None
    try:
        if dt.tzinfo is None:
            dt = TR.localize(dt)
        return dt.astimezone(TR).isoformat()
    except Exception:
        return str(dt)

def _resolve_table_name(order: Order) -> str | None:
    if not order:
        return None
    try:
        tid = getattr(order, "table_id", None)
        if tid:
            t = Table.query.get(tid)
            if t and t.name:
                return t.name
    except Exception:
        pass
    return None

def _resolve_waiter_name(order: Order) -> str | None:
    """User modelinde sadece username var."""
    if not order:
        return None
    try:
        wid = getattr(order, "served_by_user_id", None)
        if wid:
            u = User.query.get(wid)
            if u:
                return getattr(u, "username", None)
    except Exception:
        pass
    return None

def _build_station_payload_for_item(item: OrderItem, by_role: str) -> dict:
    """Gereken ID'leri join ile al; ad/garson eksikse ID üstünden tekil sorgu ile tamamla."""
    item_created_at_expr = func.coalesce(
        OrderItem.timed_started_at,
        Order.created_at,
    ).label("item_created_at")

    row = (
        db.session.query(
            OrderItem.id.label('item_id'),
            OrderItem.order_id.label('order_id'),
            OrderItem.quantity.label('qty'),
            OrderItem.note.label('note'),
            item_created_at_expr,
            Product.id.label('product_id'),
            Product.name.label('product_name'),
            Product.visible_for.label('visible_for'),
            Order.table_id.label('table_id'),
            # isimler gelmese de sorun değil; ID'lerden tamamlayacağız
            Table.name.label('table_name'),
            User.username.label('waiter_username'),
        )
        .join(Product, Product.id == OrderItem.product_id)
        .join(Order,   Order.id   == OrderItem.order_id)
        .outerjoin(Table, Table.id == Order.table_id)
        .outerjoin(User,  User.id  == Order.served_by_user_id)
        .filter(OrderItem.id == item.id)
        .first()
    )

    # Temel alanlar
    order_id     = getattr(row, 'order_id',  getattr(item, 'order_id', None))
    table_id     = getattr(row, 'table_id',  None)
    table_name   = getattr(row, 'table_name', None) or None
    waiter_name  = getattr(row, 'waiter_username', None) or None
    created_at   = getattr(row, 'item_created_at', None)
    product_id   = getattr(row, 'product_id', getattr(item, 'product_id', None))
    product_name = getattr(row, 'product_name', None)
    qty          = (getattr(row, 'qty', 1) or 1)
    note         = (getattr(row, 'note', "") or "")
    visible_for  = getattr(row, 'visible_for', None)

    # 🔧 Masa adı eksikse, table_id'den tekil sorgu ile çek
    try:
        t = db.session.get(Table, table_id)  # SQLAlchemy 1.4/2.x
        if t and t.name:
            table_name = t.name
    except Exception:
        table_name = table_name or (f"Masa #{table_id}")

    # 🔧 Garson adı eksikse, önce order'dan served_by_user_id al, sonra User'dan çek
    try:
        o = db.session.query(Order.served_by_user_id).filter(Order.id == order_id).scalar()
        if o:
            u = db.session.get(User, o)
            if u and getattr(u, "username", None):
                waiter_name = u.username
    except Exception:
        pass

    print(waiter_name)
    print(table_name)

    payload = {
        "event": "item_ready",
        "by_role": by_role,
        "order_id": order_id,
        "table_id": table_id,             # ID olarak doğru
        "table_name": table_name,         # Ad (tamamlandı)
        "masa_adi": table_name,           # front-end uyumu
        "waiter_name": waiter_name,
        "garson_adi": waiter_name,
        "created_at": _to_iso_tr(created_at),
        "items": [{
            "id": getattr(item, "id", None),
            "product_id": product_id,
            "name": product_name,
            "qty": qty,
            "note": note,
            "visible_for": visible_for,
        }]
    }
    return payload

@dashboard_bp.route('/station/durum-guncelle/<int:item_id>', methods=['POST'])
@login_required
def station_durum_guncelle(item_id):
    role = (current_user.role or "").strip().lower()
    allowed_roles = {"bar", "kitchen", "nargile", "admin"}
    if role not in allowed_roles:
        flash("Yetkisiz erişim", "danger")
        return redirect(url_for("auth.login"))

    item = OrderItem.query.get_or_404(item_id)

    if item.status == "hazırlanıyor":
        item.status = "hazır"
        db.session.commit()
        flash(f"{getattr(getattr(item, 'product', None), 'name', 'Ürün')} hazırlandı.", "success")

        payload = _build_station_payload_for_item(item, by_role=role)
        try:
            socketio.emit("order:updated", payload)
            socketio.emit(f"{role}:item_updated", payload)
        except Exception as e:
            current_app.logger.warning(f"station_durum_guncelle emit failed: {e}")
    else:
        flash("Ürün zaten hazır.", "info")

    if role in {"bar", "kitchen", "nargile"}:
        return redirect(url_for("dashboard.dashboard", panel="station"))
    return redirect(url_for("dashboard.dashboard"))

# ----------------------------
# Z penceresi: [D 05:00, D+1 02:00)
# ----------------------------
def _fixed_window_05_02(now: datetime | None = None):
    if now is None:
        now = datetime.now(TR)
    elif now.tzinfo is None:
        now = TR.localize(now)

    today_05 = now.replace(hour=5, minute=0, second=0, microsecond=0)
    today_02 = now.replace(hour=2, minute=0, second=0, microsecond=0)

    if now < today_05:
        start = today_05 - timedelta(days=1)
        end = today_02
    else:
        start = today_05
        end = today_02 + timedelta(days=1)
    return start, end

# ----------------------------
# Mini Gün Sonu
# ----------------------------
def _gunsonu_mini_data():
    start, end = _fixed_window_05_02()
    payments = (
        db.session.query(
            PartialPayment.payment_method,
            func.sum(PartialPayment.amount).label("tutar"),
            func.count(PartialPayment.id).label("adet"),
        )
        .filter(and_(PartialPayment.paid_at >= start, PartialPayment.paid_at < end))
        .group_by(PartialPayment.payment_method)
        .all()
    )
    total_revenue = float(sum(p.tutar or 0 for p in payments))
    tx_count = int(sum(p.adet or 0 for p in payments))
    return {"start": start, "end": end, "payments": payments, "total_revenue": total_revenue, "tx_count": tx_count}

def _get_waiters():
    return User.query.filter_by(role="waiter").order_by(User.username.asc()).all()

def _waiter_stats(start, end, waiters):
    rows = (
        db.session.query(
            Order.served_by_user_id.label("uid"),
            func.coalesce(func.sum(PartialPayment.amount), 0.0).label("sales"),
            func.count(PartialPayment.id).label("tx"),
        )
        .join(PartialPayment, PartialPayment.order_id == Order.id)
        .filter(PartialPayment.paid_at >= start, PartialPayment.paid_at < end)
        .group_by(Order.served_by_user_id)
        .all()
    )

    stats = {
        int(uid): {"sales": float(sales or 0.0), "tx": int(tx or 0), "on_shift": False}
        for uid, sales, tx in rows
        if uid is not None
    }

    for w in waiters:
        uid = int(getattr(w, "id"))
        current_shift = bool(getattr(w, "is_on_shift", False))
        if uid not in stats:
            stats[uid] = {"sales": 0.0, "tx": 0, "on_shift": current_shift}
        else:
            stats[uid]["on_shift"] = current_shift

    return stats

_num_re = re.compile(r"(\d+(?:[.,]\d+)?)")
def _table_sort_key(t: Table):
    name = (t.name or "").strip()
    m = _num_re.search(name)
    if m:
        try:
            num = float(m.group(1).replace(",", "."))
        except Exception:
            num = float("inf")
    else:
        num = float("inf")
    return (num, name.lower())

# ----------------------------
# Dashboard
# ----------------------------
@dashboard_bp.route("/", methods=["GET", "POST"])
@login_required
def dashboard():
    role = (getattr(current_user, "role", "") or "").lower()

    if request.method == "POST":
        action = request.values.get("action")
        if action == "shift_toggle":
            waiter_id = request.values.get("waiter_id", type=int)
            if not waiter_id:
                flash("Garson ID bulunamadı.", "danger")
            else:
                waiter = User.query.filter_by(id=waiter_id, role="waiter").first()
                if not waiter:
                    flash("Garson bulunamadı.", "danger")
                else:
                    waiter.is_on_shift = not bool(waiter.is_on_shift)
                    db.session.commit()
                    flash(
                        f"{waiter.username or ('Garson #' + str(waiter.id))} mesai durumu değiştirildi.",
                        "success",
                    )
            return redirect(url_for("dashboard.dashboard"))

    window_start, window_end = _fixed_window_05_02()

    revenue_today = (
        db.session.query(func.coalesce(func.sum(PartialPayment.amount), 0.0))
        .filter(and_(PartialPayment.paid_at >= window_start, PartialPayment.paid_at < window_end))
        .scalar()
        or 0.0
    )

    tx_count_today = (
        db.session.query(func.count(PartialPayment.id))
        .filter(and_(PartialPayment.paid_at >= window_start, PartialPayment.paid_at < window_end))
        .scalar()
        or 0
    )

    avg_basket_today = revenue_today / tx_count_today if tx_count_today else 0.0

    paid_orders_sub = (
        db.session.query(PartialPayment.order_id.label("oid"))
        .filter(and_(PartialPayment.paid_at >= window_start, PartialPayment.paid_at < window_end))
        .distinct()
        .subquery()
    )

    cancelled_total_today = (
        db.session.query(func.coalesce(func.sum(OrderItem.quantity * Product.price), 0.0))
        .join(Product, Product.id == OrderItem.product_id)
        .join(Order, Order.id == OrderItem.order_id)
        .join(paid_orders_sub, paid_orders_sub.c.oid == Order.id)
        .filter(OrderItem.status == "iptal edildi")
        .scalar()
        or 0.0
    )

    now = datetime.utcnow()
    open_items = (
        OrderItem.query
        .options(joinedload(OrderItem.product))
        .join(Order, Order.id == OrderItem.order_id)
        .filter(
            Order.is_completed.is_(False),
            OrderItem.status.notin_(('iptal edildi', 'ödendi')),
            Order.created_at >= window_start,
            Order.created_at <  window_end,
        )
        .all()
    )
    open_total_today = float(sum(i.computed_total(as_of=now) for i in open_items))
    ciro_today = float(revenue_today + open_total_today)
    from collections import defaultdict

    per_table_open = defaultdict(float)
    for it in open_items:
        try:
            tid = getattr(getattr(it, "order", None), "table_id", None)
            if tid is None:
                continue
            per_table_open[int(tid)] += float(it.computed_total(as_of=now))
        except Exception:
            continue

    # İkiye yuvarlayıp template’e verelim
    table_open_map = {tid: round(val, 2) for tid, val in per_table_open.items()}

    data = {
        "role": role,
        "window_start": window_start,
        "window_end": window_end,
        "revenue_today": revenue_today,
        "tx_count_today": tx_count_today,
        "avg_basket_today": avg_basket_today,
        "cancelled_total_today": cancelled_total_today,
        "open_total_today": open_total_today,
        "ciro_today": ciro_today,
        "table_open_map": table_open_map,   # ✅ EKLENDİ
    }

    if role in ("admin", "cashier", "waiter", "cashier-lite", "bar", "kitchen", "nargile"):
        tables = Table.query.filter(Table.is_archived.is_(False)).all()
        tables_sorted = sorted(tables, key=_table_sort_key)
        data["tables"] = tables_sorted
        data["tables_map"] = {t.id: t for t in tables_sorted}
        data["regions"] = Region.query.order_by(Region.name.asc()).all()
        data["active_region_id"] = request.args.get("region_id", type=int)

    if role in ("admin", "cashier", "cashier-lite"):
        data["gunsonu"] = _gunsonu_mini_data()
        waiters = _get_waiters()
        data["waiters"] = waiters
        data["waiter_stats"] = _waiter_stats(window_start, window_end, waiters)

    # İstasyon: bar/kitchen/nargile
    station_items = []
    if role in ("bar", "kitchen", "nargile", "admin"):
        item_created_at_expr = func.coalesce(
            OrderItem.timed_started_at,
            Order.created_at,
        ).label("item_created_at")

        STATION_SCOPE_MAP = {
            "bar": ["bar"],
            "kitchen": ["kitchen", "mutfak"],
            "mutfak": ["kitchen", "mutfak"],
            "nargile": ["nargile"],
            "admin": ["bar", "kitchen", "mutfak", "nargile"],
        }

        allowed_scopes = STATION_SCOPE_MAP.get(role, [])

        station_q = (
        db.session.query(
            OrderItem.id.label('item_id'),
            OrderItem.order_id.label('order_id'),
            OrderItem.quantity.label('qty'),
            OrderItem.note.label('note'),
            item_created_at_expr,
            Product.id.label('product_id'),
            Product.name.label('product_name'),
            Product.visible_for.label('visible_for'),
            Order.table_id.label('table_id'),
            Table.name.label('table_name'),
            User.username.label('waiter_username'),
        )
        .join(Product, Product.id == OrderItem.product_id)
        .join(Order, Order.id == OrderItem.order_id)
        .outerjoin(Table, Table.id == Order.table_id)
        .outerjoin(User, User.id == Order.served_by_user_id)
        .filter(
            OrderItem.status == "hazırlanıyor",
            Product.visible_for.in_(allowed_scopes)
        )
    )

        rows = station_q.all()
        from types import SimpleNamespace as NS
        for r in rows:
            product = NS(id=r.product_id, name=r.product_name, visible_for=r.visible_for)
            table   = NS(id=r.table_id, name=r.table_name)
            waiter_name = r.waiter_username or None
            created_at  = r.item_created_at

            it = NS(
                id=r.item_id,
                order_id=r.order_id,
                product=product,
                table=table,
                note=r.note or "",
                quantity=r.qty or 1,
                status="hazırlanıyor",
                table_name=r.table_name,
                waiter_name=waiter_name,
                visible_for=r.visible_for,
                created_at=created_at,
            )
            station_items.append(it)

    data["station_items"] = station_items
    return render_template("dashboard/dashboard.html", **data)


@dashboard_bp.route("/api/nargile-sales", methods=["GET"])
@login_required
def get_nargile_sales():
    role = (getattr(current_user, "role", "") or "").lower()
    if role not in ("admin", "nargile"):
        return {"error": "Unauthorized"}, 403

    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    try:
        # Default to today if dates are not provided
        if start_date_str:
            start_date = TR.localize(datetime.strptime(start_date_str, "%Y-%m-%d")).replace(hour=0, minute=0, second=0)
        else:
            start_date, _ = _fixed_window_05_02()

        if end_date_str:
            end_date = TR.localize(datetime.strptime(end_date_str, "%Y-%m-%d")).replace(hour=23, minute=59, second=59)
        else:
            _, end_date = _fixed_window_05_02()

    except Exception:
        return {"error": "Invalid date format"}, 400

    items = (
        db.session.query(
            OrderItem.product_id,
            func.sum(OrderItem.quantity).label("total_qty")
        )
        .join(Order, Order.id == OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .filter(
            Product.category == "Nargile",
            Order.created_at >= start_date,
            Order.created_at <= end_date,
            OrderItem.status != "iptal edildi"
        )
        .group_by(OrderItem.product_id)
        .all()
    )

    special_nargile_qty = 0
    other_nargile_qty = 0
    buzlu_marpuc_qty = 0
    kafa_degisim_qty = 0

    for product_id, total_qty in items:
        if product_id == 221:
            buzlu_marpuc_qty += total_qty or 0
        elif product_id == 222:
            kafa_degisim_qty += total_qty or 0
        else:
            other_nargile_qty += total_qty or 0

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "buzlu_marpuc_qty": buzlu_marpuc_qty,
        "kafa_degisim_qty": kafa_degisim_qty,
        "nargile_qty": other_nargile_qty
    }
