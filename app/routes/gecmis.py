# app/routes/gecmis.py
from __future__ import annotations
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, abort
from flask_login import login_required
from pytz import timezone
from sqlalchemy import func, or_, exists   
from sqlalchemy.orm import joinedload,aliased  

from app.models import db, Order, OrderItem, Product, PartialPayment, Table, User

gecmis_bp = Blueprint("gecmis", __name__, url_prefix="/gecmis")

# ---- TZ yardımcıları (DB ekseni Europe/London; gösterim TR) ----
TR = timezone("Europe/Istanbul")
UK = timezone("Europe/London")

def _tr_aware(dt):
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return TR.localize(dt)
    return dt.astimezone(TR)

def _tr_to_uk_naive(dt_tr):
    if dt_tr is None:
        return None
    dt_tr = _tr_aware(dt_tr)
    return dt_tr.astimezone(UK).replace(tzinfo=None)

def _db_to_tr(dt_from_db):
    if dt_from_db is None:
        return None
    # DB'de naive → UK-naive varsay, sonra TR'ye çevir
    if dt_from_db.tzinfo is None or dt_from_db.tzinfo.utcoffset(dt_from_db) is None:
        dt_uk = UK.localize(dt_from_db)
        return dt_uk.astimezone(TR)
    return dt_from_db.astimezone(TR)

def _business_day_range_tr(iso_date: str | None, cutoff_hour: int = 5):
    now_tr = datetime.now(TR)
    if iso_date:
        y, m, d = map(int, iso_date.split("-"))
        anchor = TR.localize(datetime(y, m, d, cutoff_hour, 0, 0))
    else:
        anchor = now_tr.replace(hour=cutoff_hour, minute=0, second=0, microsecond=0)
        if now_tr < anchor:
            anchor -= timedelta(days=1)
    return anchor, anchor + timedelta(days=1)


@gecmis_bp.route("/", methods=["GET"])
@login_required
def gecmis_list():
    # Filtreler
    d = request.args.get("d")  # YYYY-MM-DD
    cutoff = request.args.get("cutoff", type=int) or 5
    start_tr, end_tr = _business_day_range_tr(d, cutoff)
    s_uk = _tr_to_uk_naive(start_tr); e_uk = _tr_to_uk_naive(end_tr)

    q = request.args.get("q", "").strip()        # masa adı / garson adı araması
    waiter_id = request.args.get("waiter_id", type=int)
    table_id = request.args.get("table_id", type=int)
    pm = request.args.get("pm", "").strip()      # ödeme metodu

    page = max(request.args.get("page", default=1, type=int), 1)
    per_page = min(max(request.args.get("per_page", default=20, type=int), 5), 100)

    # NOT: joinedload(Order.table) KALDIRILDI
    base = (db.session.query(Order)
            .filter(
                Order.is_completed.is_(True),
                Order.created_at >= s_uk,
                Order.created_at <  e_uk
            ))

    if table_id:
        base = base.filter(Order.table_id == table_id)

    # --- WAITER/KULLANICI FİLTRESİ: served_by_user_id veya kalem ekleyen kullanıcı
    if waiter_id:
        subq_item_by_user_exists = (
            db.session.query(OrderItem.id)
            .filter(OrderItem.order_id == Order.id,
                    OrderItem.added_by_user_id == waiter_id)
            .exists()
        )
        base = base.filter(
            or_(Order.served_by_user_id == waiter_id, subq_item_by_user_exists)
        )

    # --- METİN ARAMASI: Masa adı + (servis eden kullanıcı) + (kalem ekleyen kullanıcı)
    if q:
        term = f"%{q.casefold()}%"
        U_served = aliased(User)
        U_added  = aliased(User)

        base = (base
                .outerjoin(Table, Table.id == Order.table_id)
                .outerjoin(U_served, U_served.id == Order.served_by_user_id)
                .outerjoin(OrderItem, OrderItem.order_id == Order.id)
                .outerjoin(U_added, U_added.id == OrderItem.added_by_user_id)
                .filter(or_(
                    func.lower(Table.name).like(term),
                    func.lower(U_served.username).like(term),
                    func.lower(U_added.username).like(term),
                ))
                .distinct()  # aynı Order birden fazla eşleşmeden dolayı tekrarlamasın
        )

    if pm:
        base = (base.join(PartialPayment, PartialPayment.order_id == Order.id)
                    .filter(PartialPayment.payment_method == pm)
                    .distinct())

    base = base.order_by(Order.created_at.desc())

    total = base.count()
    rows = (base.limit(per_page)
                 .offset((page - 1) * per_page)
                 .all())

    # ---- Tablo adlarını tek seferde çek (eager yok)
    table_ids = {o.table_id for o in rows if o.table_id is not None}
    table_name_map = {}
    if table_ids:
        table_name_map = dict(
            db.session.query(Table.id, Table.name)
            .filter(Table.id.in_(table_ids))
            .all()
        )

    # Listede kısa özetler
    items = []
    for o in rows:
        masa_adi = table_name_map.get(o.table_id) or (f"#{o.table_id}" if o.table_id else None)

        garson = None
        if o.served_by_user_id:
            u = db.session.get(User, int(o.served_by_user_id))
            garson = getattr(u, "username", None) if u else None

        created_tr = _db_to_tr(getattr(o, "created_at", None))

        # partial_payments dynamic olabilir -> güvenli oku
        pps = getattr(o, "partial_payments", []) or []
        if hasattr(pps, "all"):
            pps = pps.all()
        total_paid = float(sum((getattr(p, "amount", 0.0) or 0.0) for p in pps))

        items.append({
            "id": o.id,
            "masa": masa_adi or f"#{o.table_id or '-'}",
            "garson": garson,
            "created_tr": created_tr,
            "total_paid": total_paid,
        })

    # Yardımcı dropdown verileri
    tables = db.session.query(Table.id, Table.name).order_by(Table.name.asc()).all()
    users_all = (db.session.query(User.id, User.username)
                .order_by(User.username.asc())
                .all())
    payment_methods = [r[0] for r in db.session.query(PartialPayment.payment_method).distinct().all() if r[0]]

    return render_template(
        "history/list.html",
        items=items,
        start=start_tr, end=end_tr, cutoff=cutoff, d=(d or start_tr.strftime("%Y-%m-%d")),
        page=page, per_page=per_page, total=total,
        q=q, waiter_id=waiter_id, table_id=table_id, pm=pm,
        tables=tables, waiters=users_all, payment_methods=payment_methods,
    )


@gecmis_bp.route("/detay/<int:order_id>")
@login_required
def gecmis_detail(order_id: int):
    # Kapalı (tamamlanmış) siparişi, kalemleri ve ürünlerini eager yükle
    order = (
        db.session.query(Order)
        .options(
            joinedload(Order.items).joinedload(OrderItem.product)
        )
        .filter(
            Order.id == order_id,
            Order.is_completed.is_(True)
        )
        .first()
    )
    if not order:
        abort(404)

    # Masa adı (Order.table ilişkisi yoksa tekil sorgu ile)
    table_name = None
    if order.table_id:
        t = db.session.get(Table, int(order.table_id))
        table_name = getattr(t, "name", None) or f"#{order.table_id}"

    # Garson adı
    waiter_name = None
    if order.served_by_user_id:
        u = db.session.get(User, int(order.served_by_user_id))
        waiter_name = getattr(u, "username", None)

    # Ödemeler (dynamic olabilir)
    pps = getattr(order, "partial_payments", []) or []
    if hasattr(pps, "all"):
        pps = pps.all()

    # Görüntülenecek kalemler: SADECE iptal olmayanlar (ödendi dahil)
    items_for_view = [
        it for it in (order.items or [])
        if (getattr(it, "status", "") or "").lower() != "iptal edildi"
    ]

    # --- Yeni: Kalem metasını üret (ekleyen kişi + eklenme zamanı TR)
    added_by_ids = {
        int(getattr(it, "added_by_user_id"))
        for it in items_for_view
        if getattr(it, "added_by_user_id", None)
    }
    user_name_map: dict[int, str] = {}
    if added_by_ids:
        for uid, uname in db.session.query(User.id, User.username).filter(User.id.in_(added_by_ids)).all():
            user_name_map[int(uid)] = uname

    item_meta = {}
    for it in items_for_view:
        wid = getattr(it, "added_by_user_id", None)
        who = user_name_map.get(int(wid)) if wid else None
        when_tr = _db_to_tr(getattr(it, "created_at", None)) if getattr(it, "created_at", None) else None
        item_meta[it.id] = {"waiter": who, "created_tr": when_tr}

    # Kalem toplamları (readonly hesap)
    # Kapanış anına sabitlemek istiyorsan as_of olarak order.completed_at (varsa) kullan
    as_of_dt = getattr(order, "completed_at", None) or datetime.utcnow()
    item_display_totals = {}
    for it in items_for_view:
        item_display_totals[it.id] = float(it.computed_total(as_of=as_of_dt))

    total_items = float(round(sum(item_display_totals.values()), 2))
    total_paid = float(round(sum(float(getattr(p, "amount", 0.0) or 0.0) for p in pps), 2))
    remain = float(round(max(0.0, total_items - total_paid), 2))

    # Tarihler (TR gösterim için)
    created_tr = _tr_aware(getattr(order, "created_at", None)) if getattr(order, "created_at", None) else None
    closed_tr  = _tr_aware(getattr(order, "completed_at", None)) if getattr(order, "completed_at", None) else None

    return render_template(
        "history/detail.html",
        order=order,
        table_name=table_name,
        waiter_name=waiter_name,
        payments=pps,
        # Liste ve toplamlar
        items_for_view=items_for_view,
        item_display_totals=item_display_totals,
        # NEW: per-item meta
        item_meta=item_meta,
        total_items=total_items,
        total_paid=total_paid,
        remain=remain,
        created_tr=created_tr,
        closed_tr=closed_tr,
        readonly=True,
    )
