# app/routes/gun_sonu.py
from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
import csv

from flask import Blueprint, render_template, request, send_file, abort
from flask_login import login_required, current_user
from pytz import timezone
from sqlalchemy import func, and_
from sqlalchemy.orm import joinedload

from app.models import (
    db,
    Order,
    OrderItem,
    Product,
    PartialPayment,
    User,
    Region,
    Table,
)

# --- Zaman bölgeleri ---
TR = timezone("Europe/Istanbul")
UK = timezone("Europe/London")  # DB ekseni: Europe/London (GMT/BST)

gun_sonu_bp = Blueprint('gun_sonu', __name__)


# -----------------------
# Role guard (admin/cashier)
# -----------------------
def _guard():
    if getattr(current_user, "role", None) not in ('admin', 'cashier', 'cashier-lite'):
        abort(403)


# -----------------------
# TZ yardımcıları
# -----------------------
def _tr_aware(dt: datetime | None) -> datetime | None:
    """Naive ise TR.localize, aware ise TR'ye çevir."""
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return TR.localize(dt)
    return dt.astimezone(TR)

def _tr_to_uk_naive(dt_tr: datetime | None) -> datetime | None:
    """
    TR (aware/naive) bir zamanı DB ekseni olan Europe/London'a çevirip tz'siz (naive) yap.
    SQL filtrelerinde *daima* bu ekseni kullanacağız.
    """
    if dt_tr is None:
        return None
    dt_tr = _tr_aware(dt_tr)
    return dt_tr.astimezone(UK).replace(tzinfo=None)

def _db_to_uk_naive(dt_from_db: datetime | None) -> datetime | None:
    """
    DB'den gelen timestamp:
      - naive ise: zaten UK-naive varsay (dokunma)
      - aware ise: UK'ye çevir ve tz'siz (naive) yap
    """
    if dt_from_db is None:
        return None
    if dt_from_db.tzinfo is None or dt_from_db.tzinfo.utcoffset(dt_from_db) is None:
        return dt_from_db
    return dt_from_db.astimezone(UK).replace(tzinfo=None)


# -----------------------
# Cutoff sistemi: [D cutoff, D+1 cutoff)  (TR-aware döner)
# -----------------------
def business_day_range_tr(iso_date: str | None, cutoff_hour: int = 5):
    """
    İşyeri günü aralığı: [D cutoff_hour, D+1 cutoff_hour) — TR aware döner.
    iso_date verilmezse, bulunduğun güne göre en yakın aralığı hesaplar.
    """
    now_tr = datetime.now(TR)
    if iso_date:
        y, m, d = map(int, iso_date.split("-"))
        anchor = TR.localize(datetime(y, m, d, cutoff_hour, 0, 0))
    else:
        anchor = now_tr.replace(hour=cutoff_hour, minute=0, second=0, microsecond=0)
        if now_tr < anchor:
            anchor = anchor - timedelta(days=1)
    start = anchor
    end = anchor + timedelta(days=1)
    return start, end


# -----------------------
# Anlık mod: [05:00 → NOW) (TR-aware döner)
# -----------------------
def window_05_to_now(now: datetime | None = None):
    """
    05:00'dan 'şu an'a kadar olan pencere (TR aware döner).
    00:00–04:59'da çağrılırsa: başlangıç dünkü 05:00
    05:00–23:59'da çağrılırsa: başlangıç bugünkü 05:00
    """
    if now is None:
        now = datetime.now(TR)
    else:
        now = _tr_aware(now)

    today_05 = now.replace(hour=5, minute=0, second=0, microsecond=0)
    start = today_05 if now >= today_05 else (today_05 - timedelta(days=1))
    end = now
    return start, end


# -----------------------
# Ortak sorgu yardımcıları (UK-naive aralığa çevirerek filtrele)
# -----------------------
def _payments_between(start_tr, end_tr):
    s = _tr_to_uk_naive(start_tr)
    e = _tr_to_uk_naive(end_tr)
    return (
        db.session.query(
            PartialPayment.payment_method,
            func.sum(PartialPayment.amount).label("tutar"),
            func.count(PartialPayment.id).label("adet"),
        )
        .filter(and_(PartialPayment.paid_at >= s, PartialPayment.paid_at < e))
        .group_by(PartialPayment.payment_method)
        .all()
    )

def _paid_orders_sub_between(start_tr, end_tr):
    s = _tr_to_uk_naive(start_tr)
    e = _tr_to_uk_naive(end_tr)
    return (
        db.session.query(PartialPayment.order_id.label("oid"))
        .filter(and_(PartialPayment.paid_at >= s, PartialPayment.paid_at < e))
        .distinct()
        .subquery()
    )


# -----------------------
# Override'lı satır toplamı (SQL tarafı)
# -----------------------
def _line_total_expr():
    """
    SQL agregasyonlarında kullanılacak satır toplamı ifadesi:
    1) OrderItem.total_price_override
    2) Product.price * OrderItem.quantity
    """
    qty = func.coalesce(OrderItem.quantity, 0)
    return func.coalesce(
        OrderItem.total_price_override,
        func.coalesce(Product.price, 0.0) * qty
    )


# -----------------------
# İndirim toplamı: ödeme metodundan (PartialPayment.payment_method = 'indirim')
# -----------------------
def _discount_total_between(start_tr, end_tr) -> float:
    s = _tr_to_uk_naive(start_tr)
    e = _tr_to_uk_naive(end_tr)
    toplam = (
        db.session.query(func.coalesce(func.sum(PartialPayment.amount), 0.0))
        .filter(
            PartialPayment.paid_at >= s,
            PartialPayment.paid_at <  e,
            func.lower(func.coalesce(PartialPayment.payment_method, "")) == "indirim",
        )
        .scalar()
        or 0.0
    )
    return float(toplam)


# -----------------------
# Açık (ANLIK) — cutoff'tan bağımsız (her zaman "şu an")
# -----------------------
def _open_total_now_tr_independent() -> float:
    """
    Cutoff'tan bağımsız, 'şu an' itibarıyla tüm açık siparişlerin (is_completed=False)
    kalan tutarı. Hesaplama DB ekseni olan UK-naive üzerinde yapılır.
    """
    now_tr = datetime.now(TR)
    as_of_uk_naive = _tr_to_uk_naive(now_tr)

    q = (Order.query
         .options(joinedload(Order.items).joinedload(OrderItem.product))
         .filter(Order.is_completed.is_(False)))

    total_open = 0.0
    for o in q.all():
        line_sum = 0.0
        for it in (o.items or []):
            if (getattr(it, "status", "") or "").lower() == "iptal edildi":
                continue

            tot_override = getattr(it, "total_price_override", None)
            if tot_override is not None:
                line_sum += float(tot_override)
            else:
                line_sum += float(it.computed_total(as_of=as_of_uk_naive))

        paid_upto = 0.0
        for pp in (o.partial_payments or []):
            if not pp:
                continue
            when_uk = _db_to_uk_naive(getattr(pp, "paid_at", None))
            amt = float(getattr(pp, "amount", 0.0) or 0.0)
            if when_uk is None or when_uk < as_of_uk_naive:
                paid_upto += amt

        total_open += max(0.0, line_sum - paid_upto)

    return float(round(total_open, 2))


# -----------------------
# (Opsiyonel) Belirli bir ana göre açık hesaplayan eski fonksiyon
# -----------------------
def _open_total_as_of(as_of_tr: datetime, instant_mode: bool, start_tr: datetime, end_tr: datetime) -> float:
    """
    Eski davranış: as_of_tr anında açık tutar. Şu an sayfada/CSV'de kullanılmıyor.
    DB ekseniyle uyumlu olması için UK-naive'a çevrildi.
    """
    as_of_uk_naive = _tr_to_uk_naive(as_of_tr)

    if instant_mode:
        q = (Order.query
             .options(joinedload(Order.items).joinedload(OrderItem.product))
             .filter(Order.is_completed.is_(False)))
    else:
        q = (Order.query
             .options(joinedload(Order.items).joinedload(OrderItem.product))
             .filter(
                 Order.created_at < _tr_to_uk_naive(end_tr),
                 Order.is_completed.is_(False)
             ))

    total_open = 0.0
    for o in q.all():
        line_sum = 0.0
        for it in (o.items or []):
            if (getattr(it, "status", "") or "").lower() == "iptal edildi":
                continue
            tot_override = getattr(it, "total_price_override", None)
            if tot_override is not None:
                line_sum += float(tot_override)
            else:
                line_sum += float(it.computed_total(as_of=as_of_uk_naive))

        paid_upto = 0.0
        for pp in (o.partial_payments or []):
            if not pp:
                continue
            when_uk = _db_to_uk_naive(getattr(pp, "paid_at", None))
            amt = float(getattr(pp, "amount", 0.0) or 0.0)
            if when_uk is None or when_uk < as_of_uk_naive:
                paid_upto += amt

        total_open += max(0.0, line_sum - paid_upto)

    return float(round(total_open, 2))


# -----------------------
# Bölge kırılımı (ciro ve işlem adedi)
# -----------------------
def _region_sales_between(start_tr, end_tr):
    """
    Sonuç: list[dict] → {"region_id": int, "region_name": str, "ciro": float, "tx": int}
    * Bölgesi olmayan masalar 'Bölgesiz' altında toplanır.
    * Ciro PartialPayment üzerinden hesaplanır (ödeme esaslı).
    """
    s = _tr_to_uk_naive(start_tr)
    e = _tr_to_uk_naive(end_tr)

    rid = func.coalesce(Table.region_id, -1).label("rid")
    rname = func.coalesce(Region.name, "Bölgesiz").label("rname")

    rows = (
        db.session.query(
            rid,
            rname,
            func.coalesce(func.sum(PartialPayment.amount), 0.0).label("ciro"),
            func.count(PartialPayment.id).label("tx"),
        )
        .join(Order, Order.id == PartialPayment.order_id)        # PP -> Order
        .join(Table, Table.id == Order.table_id)                 # Order -> Table
        .outerjoin(Region, Region.id == Table.region_id)         # Table -> Region (opsiyonel)
        .filter(PartialPayment.paid_at >= s, PartialPayment.paid_at < e)
        .group_by(rid, rname)
        .order_by(func.sum(PartialPayment.amount).desc())
        .all()
    )

    return [
        {
            "region_id": int(r.rid),
            "region_name": r.rname,
            "ciro": float(r.ciro or 0.0),
            "tx": int(r.tx or 0),
        }
        for r in rows
    ]


# -----------------------
# Sayfa: Gün Sonu
# -----------------------
@gun_sonu_bp.route("/gun-sonu/")
@gun_sonu_bp.route("/gun-sonu")
@login_required
def gun_sonu():
    _guard()

    instant_mode = (request.args.get("instant") == "1")

    if instant_mode:
        start, end = window_05_to_now()     # TR aware
        d = start.strftime("%Y-%m-%d")
        cutoff = None
    else:
        d = request.args.get("d")
        cutoff = int(request.args.get("cutoff", 5))
        start, end = business_day_range_tr(d, cutoff)  # TR aware

    # Ödemeler & özet (TAHSİLAT) — SQL UK-naive ekseninde
    payments = _payments_between(start, end)

    # Tahsilat = 'indirim' HARİÇ ödeme yöntemleri
    total_revenue = float(sum(
        (p.tutar or 0.0)
        for p in payments
        if (str(p.payment_method or "").lower() != "indirim")
    ))
    # İşlem adedi de indirimleri hariç tutsun (fiş sayısı algısına daha yakın)
    tx_count = int(sum(
        (p.adet or 0)
        for p in payments
        if (str(p.payment_method or "").lower() != "indirim")
    ))

    # Bu aralıkta ödemesi olan siparişler (ürün kırılımı ve iptaller için)
    paid_orders_sub = _paid_orders_sub_between(start, end)

    # Ürün kırılımı (ödenmiş kalemler) — OVERRIDE DÂHİL, SADECE ÖDEMESİ OLAN SİPARİŞLER
    product_breakdown = (
        db.session.query(
            Product.id.label("pid"),
            Product.name.label("name"),
            func.sum(OrderItem.quantity).label("qty"),
            func.sum(_line_total_expr()).label("total")
        )
        .join(Product, Product.id == OrderItem.product_id)
        .join(Order, Order.id == OrderItem.order_id)
        .join(paid_orders_sub, paid_orders_sub.c.oid == Order.id)
        .filter(OrderItem.status == 'ödendi')
        .group_by(Product.id, Product.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .all()
    )

    # Garson/Servis kırılımı: Order.served_by_user_id (UK-naive aralığa göre)
    s_uk = _tr_to_uk_naive(start); e_uk = _tr_to_uk_naive(end)
    waiter_breakdown = (
        db.session.query(
            User.id.label("uid"),
            User.username.label("name"),
            func.coalesce(func.sum(PartialPayment.amount), 0.0).label("total"),
            func.count(PartialPayment.id).label("tx"),
        )
        .join(Order, Order.id == PartialPayment.order_id)
        .outerjoin(User, User.id == Order.served_by_user_id)
        .filter(and_(PartialPayment.paid_at >= s_uk, PartialPayment.paid_at < e_uk))
        .group_by(User.id, User.username)
        .order_by(func.coalesce(func.sum(PartialPayment.amount), 0.0).desc())
        .all()
    )

    # Kasiyer kırılımı: PartialPayment.cashier_user_id (UK-naive aralığa göre)
    cashier_breakdown = (
        db.session.query(
            User.id.label("uid"),
            User.username.label("name"),
            func.coalesce(func.sum(PartialPayment.amount), 0.0).label("total"),
            func.count(PartialPayment.id).label("tx"),
        )
        .outerjoin(User, User.id == PartialPayment.cashier_user_id)
        .filter(and_(PartialPayment.paid_at >= s_uk, PartialPayment.paid_at < e_uk))
        .group_by(User.id, User.username)
        .order_by(func.coalesce(func.sum(PartialPayment.amount), 0.0).desc())
        .all()
    )

    # İptal edilen kalemler (ödemesi bu aralıkta olan siparişler içinden)
    cancelled_items = (
        db.session.query(
            Product.name.label("name"),
            func.count(OrderItem.id).label("count")
        )
        .join(Product, Product.id == OrderItem.product_id)
        .join(Order, Order.id == OrderItem.order_id)
        .join(paid_orders_sub, paid_orders_sub.c.oid == Order.id)
        .filter(OrderItem.status == 'iptal edildi')
        .group_by(Product.name)
        .order_by(func.count(OrderItem.id).desc())
        .all()
    )

    # Bölge kırılımı (tahsilat bazlı) — burada indirimleri ayrıca ayırmıyoruz; talep gelirse filtrelenebilir.

    region_sales = _region_sales_between(start, end)

    # Açık (ANLIK)
    open_total = _open_total_now_tr_independent()
    ciro_total = float(round(total_revenue + open_total, 2))

    # İndirim (ödeme metodu)
    discount_total = _discount_total_between(start, end)

    # Masa & ORT. FİŞ — Order.created_at penceresi, iptal dışı kalemi olan masalar
    items_not_cancelled_exists = (
        db.session.query(OrderItem.id)
        .filter(
            OrderItem.order_id == Order.id,
            OrderItem.status != 'iptal edildi'
        )
        .exists()
    )
    table_count = int(
        db.session.query(func.count(Order.id))
        .filter(
            Order.created_at >= s_uk,
            Order.created_at <  e_uk,
            Order.table_id.isnot(None),
            items_not_cancelled_exists
        )
        .scalar() or 0
    )
    avg_receipt = (total_revenue / table_count) if table_count > 0 else 0.0

    return render_template(
        "admin/gun_sonu.html",
        # Form alanları
        d=(d or datetime.now(TR).strftime("%Y-%m-%d")),
        cutoff=cutoff,
        instant=instant_mode,
        # Zaman penceresi (TR aware gösterim)
        start=start, end=end,
        # Veriler
        payments=payments,
        total_revenue=total_revenue,    # Tahsilat (indirim hariç)
        tx_count=tx_count,              # İşlem adedi (indirim hariç)
        product_breakdown=product_breakdown,
        waiter_breakdown=waiter_breakdown,
        cashier_breakdown=cashier_breakdown,
        cancelled_items=cancelled_items,
        region_sales=region_sales,
        # KPI'lar
        open_total=open_total,
        ciro_total=ciro_total,
        discount_total=discount_total,  # 🔻 İndirim toplamı (ödeme metodu)
        table_count=table_count,
        avg_receipt=avg_receipt,
    )


# -----------------------
# CSV: Gün Sonu Export
# -----------------------
@gun_sonu_bp.route("/gun-sonu/export.csv")
@login_required
def gun_sonu_export_csv():
    _guard()

    instant_mode = (request.args.get("instant") == "1")

    if instant_mode:
        start, end = window_05_to_now()
        label = "Gün Sonu (05:00 → Şimdi)"
    else:
        d = request.args.get("d")
        cutoff = int(request.args.get("cutoff", 12))
        start, end = business_day_range_tr(d, cutoff)
        label = f"Gün Sonu (Cutoff {cutoff:02d}:00)"

    payments = _payments_between(start, end)

    # Tahsilat ve indirimleri CSV için de ayır
    total_revenue = float(sum(
        (p.tutar or 0.0)
        for p in payments
        if (str(p.payment_method or "").lower() != "indirim")
    ))
    discount_total = float(sum(
        (p.tutar or 0.0)
        for p in payments
        if (str(p.payment_method or "").lower() == "indirim")
    ))

    paid_orders_sub = _paid_orders_sub_between(start, end)

    # Ürün kırılımı — OVERRIDE DÂHİL, sadece ödemesi olan siparişler
    products = (
        db.session.query(
            Product.name.label("name"),
            func.sum(OrderItem.quantity).label("qty"),
            func.sum(_line_total_expr()).label("total")
        )
        .join(Product, Product.id == OrderItem.product_id)
        .join(Order, Order.id == OrderItem.order_id)
        .join(paid_orders_sub, paid_orders_sub.c.oid == Order.id)
        .filter(OrderItem.status == 'ödendi')
        .group_by(Product.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .all()
    )

    # Açık (Anlık) cutoff'tan bağımsız
    open_total = _open_total_now_tr_independent()
    ciro_total = float(round(total_revenue + open_total, 2))

    # Masa & ort. fiş (CSV için de)
    s_uk = _tr_to_uk_naive(start); e_uk = _tr_to_uk_naive(end)
    items_not_cancelled_exists = (
        db.session.query(OrderItem.id)
        .filter(
            OrderItem.order_id == Order.id,
            OrderItem.status != 'iptal edildi'
        )
        .exists()
    )
    table_count = int(
        db.session.query(func.count(Order.id))
        .filter(
            Order.created_at >= s_uk,
            Order.created_at <  e_uk,
            Order.table_id.isnot(None),
            items_not_cancelled_exists
        )
        .scalar() or 0
    )
    avg_receipt = (total_revenue / table_count) if table_count > 0 else 0.0

    output = StringIO()
    w = csv.writer(output)
    w.writerow([label, start.strftime("%d.%m.%Y %H:%M"), end.strftime("%d.%m.%Y %H:%M")])
    w.writerow([])
    # Özet
    w.writerow(["Özet"])
    w.writerow(["Tahsilat (Ödemeler Toplamı, indirim hariç)", f"{total_revenue:.2f}"])
    w.writerow(["Açık (Anlık)", f"{open_total:.2f}"])
    w.writerow(["Toplam Ciro (Tahsilat + Açık)", f"{ciro_total:.2f}"])
    w.writerow(["İndirim Toplamı (ödeme metodu)", f"{discount_total:.2f}"])
    w.writerow(["Masa (Order.created_at penceresi)", table_count])
    w.writerow(["Ortalama Fiş (Tahsilat / Masa)", f"{avg_receipt:.2f}"])
    w.writerow([])

    # Ödemeler (tüm yöntemleri tek tek yaz)
    w.writerow(["Ödeme Yöntemi", "İşlem Adedi", "Tutar"])
    for p in payments:
        w.writerow([p.payment_method or "-", int(p.adet or 0), float(p.tutar or 0)])
    w.writerow([])

    # Ürün kırılımı
    w.writerow(["Ürün", "Adet", "Tutar"])
    for row in products:
        w.writerow([row.name, int(row.qty or 0), float(row.total or 0)])

    output.seek(0)
    filename = f"gun_sonu_{start.strftime('%Y%m%d_%H%M')}-{end.strftime('%Y%m%d_%H%M')}{'_instant' if instant_mode else ''}.csv"
    return send_file(output, mimetype="text/csv", as_attachment=True, download_name=filename)
