# app/routes/istatistikler.py
from flask import Blueprint, render_template, request, abort
from flask_login import login_required, current_user
from sqlalchemy import func, case, and_, or_
from sqlalchemy.orm import joinedload, aliased
from datetime import datetime, timedelta
from pytz import timezone, UTC
import json

from app.models import (
    db, Order, OrderItem, Product, PartialPayment, Table, User, Region
)

# Ürün bazlı tutar hesaplama (İndirimli fiyat varsa onu, yoksa normal fiyatı baz alır)
row_total = case(
    (OrderItem.total_price_override.isnot(None), OrderItem.total_price_override),
    else_=(OrderItem.quantity * Product.price)
)

TR = timezone("Europe/Istanbul")
istat_bp = Blueprint("istatistikler", __name__)

def _guard():
    if (getattr(current_user, "role", "") or "").lower() not in ("admin", "cashier"):
        abort(403)

def _to_utc_naive(dt):
    return dt.astimezone(UTC).replace(tzinfo=None)

def _cutoff_floor_tr(dt_tr):
    base = dt_tr.astimezone(TR)
    five = TR.localize(datetime(base.year, base.month, base.day, 5, 0, 0))
    if base < five:
        five -= timedelta(days=1)
    return five

def _date_range():
    now_tr = datetime.now(UTC).astimezone(TR)
    s = request.args.get("from")
    e = request.args.get("to")
    instant = bool(request.args.get("instant"))

    if instant:
        start_tr = _cutoff_floor_tr(now_tr)
        end_tr = now_tr
        start_ui = start_tr.date().isoformat()
        end_ui = end_tr.date().isoformat()
    elif s and e:
        y1, m1, d1 = map(int, s.split("-"))
        y2, m2, d2 = map(int, e.split("-"))
        start_tr = TR.localize(datetime(y1, m1, d1, 5))
        end_tr = (TR.localize(datetime(y2, m2, d2, 5)) + timedelta(days=1) - timedelta(microseconds=1))
        start_ui, end_ui = s, e
    else:
        today_cut = _cutoff_floor_tr(now_tr)
        start_tr = today_cut - timedelta(days=6)
        end_tr = today_cut + timedelta(days=1) - timedelta(microseconds=1)
        start_ui = start_tr.date().isoformat()
        end_ui = end_tr.date().isoformat()

    return _to_utc_naive(start_tr), _to_utc_naive(end_tr), instant, start_ui, end_ui, start_tr.date(), end_tr.date()

def _open_total_now():
    as_of = datetime.utcnow()
    # "iptal" olmayan ve henüz kapanmamış (Order.is_completed=False) siparişler
    items = db.session.query(OrderItem).options(joinedload(OrderItem.product)).join(Order).filter(
        Order.is_completed.is_(False),
        ~OrderItem.status.in_(["iptal", "iptal edildi", "ödendi"])
    ).all()
    return float(sum(i.computed_total(as_of=as_of) for i in items))

@istat_bp.route("/istatistikler")
@login_required
def istatistikler():
    _guard()
    tab = (request.args.get("tab") or "tarih").lower()
    start, end, instant, start_ui, end_ui, start_date_tr, end_date_tr = _date_range()
    cutoff = 5

    # --- KPI HESAPLAMALARI ---
    # Tahsilat (Kasaya Giren): Ödemeler tablosundan
    tahsilat = float(db.session.query(func.coalesce(func.sum(PartialPayment.amount), 0)).filter(
        PartialPayment.paid_at.between(start, end), 
        PartialPayment.payment_method != "indirim"
    ).scalar())
    
    indirim_total = float(db.session.query(func.coalesce(func.sum(PartialPayment.amount), 0)).filter(
        PartialPayment.paid_at.between(start, end), 
        PartialPayment.payment_method == "indirim"
    ).scalar())
    
    islem_adedi = int(db.session.query(func.count(func.distinct(PartialPayment.order_id))).filter(
        PartialPayment.paid_at.between(start, end), 
        PartialPayment.payment_method != "indirim"
    ).scalar())
    
    # Açık Tutar (Masada Bekleyen)
    today_tr = datetime.now(UTC).astimezone(TR).date()
    open_total = _open_total_now() if start_date_tr <= today_tr <= end_date_tr else 0.0
    
    # Toplam Ciro = Tahsilat + Açık
    ciro_total = tahsilat + open_total
    ort_fis = tahsilat / islem_adedi if islem_adedi else 0
    masa_sayisi = islem_adedi

    data = {
        "urun_performans": [], "iptal_analizi": [], "staff_json": "{}",
        "pie_ekran_genel": [], "pie_kat_genel": [], "uyumlu_ekranlar": [], "uyumlu_kategoriler": []
    }

    if tab == "analiz":
        # 1. Ürün Performans & Masa Katkısı
        perf_query = db.session.query(
            Product.id.label("p_id"), Product.name.label("name"), func.sum(OrderItem.quantity).label("adet"),
            func.sum(row_total).label("product_ciro"), func.count(func.distinct(Order.id)).label("masa_sayisi")
        ).select_from(OrderItem).join(Product).join(Order).filter(
            OrderItem.status == "ödendi", 
            OrderItem.created_at.between(start, end)
        ).group_by(Product.id, Product.name).all()

        final_perf = []
        for r in perf_query:
            # Bu ürünün bulunduğu siparişlerdeki toplam ciro
            order_ids_sub = db.session.query(OrderItem.order_id).filter(OrderItem.product_id == r.p_id, OrderItem.status == "ödendi", OrderItem.created_at.between(start, end)).subquery()
            total_rev = db.session.query(func.sum(row_total)).select_from(OrderItem).join(Product).filter(OrderItem.order_id.in_(order_ids_sub), OrderItem.status == "ödendi").scalar() or 0
            
            # Masa Katkısı = (Toplam Ciro - Ürünün Kendi Cirosu) / İşlem Sayısı
            masa_katki = (float(total_rev) - float(r.product_ciro)) / r.masa_sayisi if r.masa_sayisi else 0
            final_perf.append({"name": r.name, "adet": r.adet, "ciro": r.product_ciro, "ort_fiyat": r.product_ciro/r.adet if r.adet else 0, "masa_katki": masa_katki, "islem_sayisi": r.masa_sayisi})
        data["urun_performans"] = sorted(final_perf, key=lambda x: x['ciro'], reverse=True)

        # 2. İptal Analizi
        iptal_stats = db.session.query(
            Product.name.label("name"),
            func.sum(case((OrderItem.status.in_(["iptal", "iptal edildi"]), OrderItem.quantity), else_=0)).label("iptal_adet"),
            func.sum(OrderItem.quantity).label("toplam_adet")
        ).select_from(OrderItem).join(Product).filter(OrderItem.created_at.between(start, end)).group_by(Product.name).all()
        
        data["iptal_analizi"] = [
            {"name": r.name, "adet": int(r.iptal_adet or 0), "oran": (float(r.iptal_adet)*100/float(r.toplam_adet)) if (r.toplam_adet and r.toplam_adet > 0) else 0} 
            for r in iptal_stats if (r.iptal_adet and r.iptal_adet > 0)
        ]

        # 3. Personel x Ürün Kırılımı (Kritik Düzeltme: Alt Sorgu Kullanımı)
        # Önce kullanıcı bazında ürün toplamlarını alıyoruz
        staff_subq = db.session.query(
            OrderItem.added_by_user_id.label("uid"),
            Product.name.label("p_name"),
            Product.category.label("p_cat"),
            Product.visible_for.label("p_screen"),
            func.sum(OrderItem.quantity).label("qty"),
            func.sum(row_total).label("ciro")
        ).join(Product, Product.id == OrderItem.product_id)\
         .filter(OrderItem.created_at.between(start, end), OrderItem.status == "ödendi")\
         .group_by(OrderItem.added_by_user_id, Product.name, Product.category, Product.visible_for).subquery()

        # Sonra kullanıcı adlarıyla birleştiriyoruz
        staff_raw = db.session.query(
            User.username.label("user"), 
            staff_subq.c.p_name, 
            staff_subq.c.p_cat, 
            staff_subq.c.p_screen, 
            staff_subq.c.qty, 
            staff_subq.c.ciro
        ).join(staff_subq, User.id == staff_subq.c.uid).all()
        
        staff_stats = {}
        for r in staff_raw:
            u = r.user
            # Admin'i listeden kaldırmak isterseniz burayı açın, ama "Remove from chart" dendiği için JS tarafında da yapılabilir.
            # if u.lower() == 'admin': continue 
            if u not in staff_stats: staff_stats[u] = {"products": [], "categories": {}, "screens": {}}
            staff_stats[u]["products"].append({"p": r.p_name, "q": int(r.qty)})
            k, e = (r.p_cat or "Diğer"), (r.p_screen or "Genel")
            staff_stats[u]["categories"][k] = staff_stats[u]["categories"].get(k, 0) + float(r.ciro or 0)
            staff_stats[u]["screens"][e] = staff_stats[u]["screens"].get(e, 0) + float(r.ciro or 0)
        data["staff_json"] = json.dumps(staff_stats)

    elif tab == "tarih":
        data["gunluk"] = db.session.query(func.strftime("%Y-%m-%d", PartialPayment.paid_at).label("gun"), func.sum(PartialPayment.amount).label("tutar")).filter(PartialPayment.paid_at.between(start, end), PartialPayment.payment_method != "indirim").group_by("gun").order_by("gun").all()
    
    elif tab == "bolge":
        rows = db.session.query(func.coalesce(Region.name, "Bölgesiz").label("bolge"), func.sum(PartialPayment.amount).label("tutar"), func.count(func.distinct(Order.id)).label("islem")).select_from(PartialPayment).join(Order, Order.id == PartialPayment.order_id).join(Table, Table.id == Order.table_id).outerjoin(Region, Region.id == Table.region_id).filter(PartialPayment.paid_at.between(start, end), PartialPayment.payment_method != "indirim").group_by("bolge").all()
        data["bolgeler"] = [{"bolge": r.bolge, "tutar": r.tutar, "masa": r.islem, "ort_masa": (r.tutar / r.islem) if r.islem else 0} for r in rows]
    
    elif tab == "personel":
        # HATA DÜZELTİLDİ: "Kartezyen Çarpım" Engellemesi
        # Personel cirosu hesaplanırken önce ürünler toplanır (subquery), sonra kullanıcı ile birleştirilir.
        # Bu yöntem, aynı adisyonda birden fazla ödeme satırı varsa sonucun katlanmasını (1m -> 22m) engeller.
        
        user_sales_subq = db.session.query(
            OrderItem.added_by_user_id.label("uid"),
            func.sum(row_total).label("total_sales"),
            func.count(func.distinct(OrderItem.order_id)).label("order_count")
        ).join(Product, Product.id == OrderItem.product_id)\
         .filter(
            OrderItem.created_at.between(start, end),
            ~OrderItem.status.in_(["iptal", "iptal edildi"]) # İptal olmayan tüm satışlar
        ).group_by(OrderItem.added_by_user_id).subquery()

        rows = db.session.query(
            User.username.label("ad"),
            user_sales_subq.c.total_sales.label("tutar"),
            user_sales_subq.c.order_count.label("islem")
        ).join(user_sales_subq, User.id == user_sales_subq.c.uid).all()
        
        data["garsonlar"] = [{"ad": r.ad, "tutar": float(r.tutar or 0), "masa": r.islem, "ort_masa": (float(r.tutar or 0) / r.islem) if r.islem else 0} for r in rows]
    
    elif tab == "saat":
        # GMT+3 Düzenlemesi (+3 hours)
        data["saatler"] = db.session.query(func.strftime("%H", func.datetime(PartialPayment.paid_at, "+3 hours")).label("saat"), func.sum(PartialPayment.amount).label("tutar")).filter(PartialPayment.paid_at.between(start, end), PartialPayment.payment_method != "indirim").group_by("saat").order_by("saat").all()
    
    elif tab == "ekran":
        # Ekran Verileri
        rows = db.session.query(Product.visible_for.label("ekran"), func.coalesce(func.sum(OrderItem.quantity), 0).label("adet"), func.coalesce(func.sum(row_total), 0.0).label("tutar")).select_from(OrderItem).join(Product, Product.id == OrderItem.product_id).filter(OrderItem.created_at.between(start, end), OrderItem.status == "ödendi").group_by(Product.visible_for).order_by(func.sum(row_total).desc()).all()
        data["ekranlar"] = [{"ekran": r.ekran or "-", "adet": int(r.adet or 0), "tutar": float(r.tutar or 0.0)} for r in rows]
        
        # Ekran Korelasyon Analizi (Birlikte Satış)
        i1 = aliased(OrderItem)
        i2 = aliased(OrderItem)
        p1 = aliased(Product)
        p2 = aliased(Product)
        
        corr = db.session.query(
            p1.visible_for, p2.visible_for, func.count(func.distinct(i1.order_id))
        ).join(p1, p1.id == i1.product_id).join(i2, i1.order_id == i2.order_id).join(p2, p2.id == i2.product_id)\
         .filter(i1.created_at.between(start, end), p1.visible_for < p2.visible_for, i1.status == "ödendi", i2.status == "ödendi")\
         .group_by(p1.visible_for, p2.visible_for).order_by(func.count(func.distinct(i1.order_id)).desc()).limit(10).all()
        
        data["uyumlu_ekranlar"] = [{"cift": f"{r[0]} + {r[1]}", "adet": r[2]} for r in corr]

    elif tab == "urun":
        kategoris = db.session.query(Product.category.label("kat"), func.coalesce(func.sum(row_total), 0.0).label("tutar")).select_from(OrderItem).join(Product, Product.id == OrderItem.product_id).filter(OrderItem.created_at.between(start, end), OrderItem.status == "ödendi").group_by(Product.category).order_by(func.sum(row_total).desc()).all()
        data["kategori"] = [{"kat": r.kat or "-", "tutar": float(r.tutar or 0.0)} for r in kategoris]
        
        # Kategori Korelasyon Analizi
        i1 = aliased(OrderItem)
        i2 = aliased(OrderItem)
        p1 = aliased(Product)
        p2 = aliased(Product)
        
        corr = db.session.query(
            p1.category, p2.category, func.count(func.distinct(i1.order_id))
        ).join(p1, p1.id == i1.product_id).join(i2, i1.order_id == i2.order_id).join(p2, p2.id == i2.product_id)\
         .filter(i1.created_at.between(start, end), p1.category < p2.category, i1.status == "ödendi", i2.status == "ödendi")\
         .group_by(p1.category, p2.category).order_by(func.count(func.distinct(i1.order_id)).desc()).limit(10).all()
        data["uyumlu_kategoriler"] = [{"cift": f"{r[0]} + {r[1]}", "adet": r[2]} for r in corr]

    return render_template("admin/istatistikler.html", tab=tab, start=start_date_tr, end=end_date_tr, start_ui=start_ui, end_ui=end_ui, instant=instant, cutoff=cutoff, tahsilat=tahsilat, indirim_total=indirim_total, open_total=open_total, ciro_total=ciro_total, masa_sayisi=masa_sayisi, ort_fis=ort_fis, **data)