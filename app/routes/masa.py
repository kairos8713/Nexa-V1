# app/routes/masa.py



from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort, jsonify, session



from flask_login import login_required, current_user



from sqlalchemy import func, and_, false, or_



from sqlalchemy.exc import IntegrityError



from datetime import datetime



from pytz import timezone



from sqlalchemy.orm import joinedload



from app.permissions import require



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



import math







# 🔹 Hugin entegrasyonu için eklenen importlar



from app.utils import is_hugin_enabled



from app.services.hugin_bridge.hugin_gateway import hugin_gateway







TR = timezone("Europe/Istanbul")



masa_bp = Blueprint('masa', __name__)







from datetime import datetime, time



import pytz







TR_TZ = pytz.timezone("Europe/Istanbul")







# config.py veya en üstte bir yerde



HAPPY_HOUR_ENABLED = True



HAPPY_HOUR_DISCOUNT_RATE = 0.25  # %25







def is_happy_hour() -> bool:



    if not HAPPY_HOUR_ENABLED:



        return False







    now_utc = datetime.now(pytz.utc)







    tr_now = now_utc.astimezone(TR_TZ).time()



    return time(8, 0) <= tr_now < time(12, 0)















def _active_order_for_table(table_id: int):



    """Hedef masada aktif order varsa getir, yoksa oluştur."""



    active = (db.session.query(Order)



              .filter(Order.table_id == table_id, Order.is_completed == False)



              .order_by(Order.id.desc())



              .first())



    if active:



        return active



    # yeni oluştur (senin sistem saatlerini TR'ye göre naive/aware nasıl tutuyorsan uyarla)



    o = Order(table_id=table_id, is_completed=False, created_at=datetime.now(TR))



    db.session.add(o)



    db.session.flush()



    return o







def _has_open_items(order_id: int) -> bool:



    """Siparişte hala aktif (iptal/ödendi olmayan) kalem var mı?"""



    q = (db.session.query(OrderItem.id)



         .filter(OrderItem.order_id==order_id,



                 OrderItem.status.notin_(('iptal edildi','ödendi'))))



    return db.session.query(q.exists()).scalar()







def _close_order_if_empty(order: Order):



    """Aktif kalem kalmadıysa siparişi tamamla ve masayı boşalt."""



    if not _has_open_items(order.id):



        order.is_completed = True



        # masayı boşalt



        tbl = db.session.get(Table, order.table_id)



        if tbl:



            tbl.status = 'boş'







@masa_bp.post("/masa/<int:masa_id>/adisyon-bol")



@login_required



@require('adisyon-işlemleri')



def adisyon_bol(masa_id):



    payload = request.get_json(force=True) or {}



    target_table_id = int(payload.get("target_table_id") or 0)



    item_ids = list(map(int, payload.get("item_ids") or []))







    if not target_table_id or not item_ids:



        abort(400, "target_table_id ve item_ids zorunlu")







    src_order = (



        db.session.query(Order)



        .filter(



            Order.table_id == masa_id,



            Order.is_completed.is_(False)



        )



        .order_by(Order.id.desc())



        .first()



    )



    if not src_order:



        abort(400, "Kaynak masada aktif adisyon yok")







    tgt_order = _active_order_for_table(target_table_id)







    rows = (



        db.session.query(OrderItem)



        .filter(



            OrderItem.id.in_(item_ids),



            OrderItem.order_id == src_order.id,



            OrderItem.status.notin_(('iptal edildi', 'ödendi'))



        )



        .all()



    )







    moved = 0



    for it in rows:



        it.order_id = tgt_order.id



        moved += 1







    _close_order_if_empty(src_order)







    # 🔥 MASA STATE GARANTİSİ



    tgt_tbl = db.session.get(Table, target_table_id)



    if tgt_tbl:



        tgt_tbl.status = 'dolu'







    src_tbl = db.session.get(Table, masa_id)



    if src_tbl:



        # src_order kapandıysa boş



        src_tbl.status = 'boş' if src_order.is_completed else 'dolu'







    db.session.commit()



    return jsonify({



        "ok": True,



        "moved": moved,



        "target_order_id": tgt_order.id



    })











@masa_bp.post("/masa/<int:masa_id>/masa-degistir")



@login_required



@require('adisyon-işlemleri')



def masa_degistir(masa_id):



    payload = request.get_json(force=True) or {}



    target_table_id = int(payload.get("target_table_id") or 0)







    if not target_table_id:



        abort(400, "target_table_id zorunlu")



    if target_table_id == masa_id:



        abort(400, "Hedef masa kaynakla aynı olamaz")







    src_order = (



        db.session.query(Order)



        .filter(



            Order.table_id == masa_id,



            Order.is_completed.is_(False)



        )



        .order_by(Order.id.desc())



        .first()



    )



    if not src_order:



        abort(400, "Kaynak masada aktif adisyon yok")







    existing_target_active = (



        db.session.query(Order)



        .filter(



            Order.table_id == target_table_id,



            Order.is_completed.is_(False)



        )



        .first()



    )







    if existing_target_active:



        items = (



            db.session.query(OrderItem)



            .filter(



                OrderItem.order_id == src_order.id,



                OrderItem.status.notin_(('iptal edildi', 'ödendi'))



            )



            .all()



        )



        for it in items:



            it.order_id = existing_target_active.id







        _close_order_if_empty(src_order)



    else:



        src_order.table_id = target_table_id







    # 🔥 KRİTİK KISIM (branch bağımsız)



    tgt_tbl = db.session.get(Table, target_table_id)



    if tgt_tbl:



        tgt_tbl.status = 'dolu'







    src_tbl = db.session.get(Table, masa_id)



    if src_tbl:



        src_tbl.status = 'boş'







    db.session.commit()



    return jsonify({"ok": True})







@masa_bp.post("/masa/<int:masa_id>/adisyon-birlestir")



@login_required



@require('adisyon-işlemleri')



def adisyon_birlestir(masa_id):



    payload = request.get_json(force=True) or {}



    target_table_id = int(payload.get("target_table_id") or 0)



    item_ids = list(map(int, payload.get("item_ids") or []))







    if not target_table_id or not item_ids:



        abort(400, "target_table_id ve item_ids zorunlu")



    if target_table_id == masa_id:



        abort(400, "Hedef masa kaynakla aynı olamaz")







    src_order = (



        db.session.query(Order)



        .filter(



            Order.table_id == masa_id,



            Order.is_completed.is_(False)



        )



        .order_by(Order.id.desc())



        .first()



    )



    if not src_order:



        abort(400, "Kaynak masada aktif adisyon yok")







    tgt_order = _active_order_for_table(target_table_id)







    rows = (



        db.session.query(OrderItem)



        .filter(



            OrderItem.id.in_(item_ids),



            OrderItem.order_id == src_order.id,



            OrderItem.status.notin_(('iptal edildi', 'ödendi'))



        )



        .all()



    )







    moved = 0



    for it in rows:



        it.order_id = tgt_order.id



        moved += 1







    _close_order_if_empty(src_order)







    # 🔥 MASA STATE SENKRONU



    tgt_tbl = db.session.get(Table, target_table_id)



    if tgt_tbl:



        tgt_tbl.status = 'dolu'







    src_tbl = db.session.get(Table, masa_id)



    if src_tbl:



        src_tbl.status = 'boş' if src_order.is_completed else 'dolu'







    db.session.commit()



    return jsonify({



        "ok": True,



        "moved": moved,



        "target_order_id": tgt_order.id



    })











# ---------------------------------------------------------



# MASA LİSTESİ (sol: bölgeler, sağ: masalar) + ÜST PANELLER



# ---------------------------------------------------------



@masa_bp.route('/admin/masalar', endpoint='masa_listesi')



@login_required



@require('masa-listesi')



def masa_listesi():



    from collections import defaultdict



    from sqlalchemy.orm import joinedload







    role = (getattr(current_user, "role", "") or "").lower()



    region_id = request.args.get('region_id', type=int)







    # Bölgeler



    regions = Region.query.order_by(Region.name.asc()).all()







    # Masalar (arşiv dışı + opsiyonel bölge filtresi)



    q = Table.query.filter(Table.is_archived.is_(False))



    if region_id:



        q = q.filter(Table.region_id == region_id)



    masalar = q.order_by(Table.name.asc()).all()







    # ---- Ciro haritası: sadece "dolu" masalarda gösterilecek, ama



    # hesaplamayı tüm görünür masaların açık adisyonları için yapıyoruz.



    ciro_by_table: dict[int, float] = {}



    table_ids = [m.id for m in masalar]



    if table_ids:



        # Görünür masalara ait AÇIK adisyonları, kalem ve ürünleriyle birlikte çek



        active_orders = (



            db.session.query(Order)



            .options(joinedload(Order.items).joinedload(OrderItem.product))



            .filter(



                Order.is_completed.is_(False),



                Order.table_id.in_(table_ids)



            )



            .all()



        )







        # Aynı masada birden fazla açık adisyon varsa en yenisini seç



        latest_by_table = defaultdict(lambda: None)



        for o in active_orders:



            if o.table_id is None:



                continue



            prev = latest_by_table[o.table_id]



            if prev is None or (o.created_at or datetime.min) > (prev.created_at or datetime.min):



                latest_by_table[o.table_id] = o







        # Ara toplamları hesapla (iptal edilen kalemler hariç)



        as_of = datetime.utcnow()



        for table_id, order in latest_by_table.items():



            if not order:



                continue



            total = 0.0



            for it in (order.items or []):



                status = (getattr(it, "status", "") or "").casefold()



                if status == "iptal edildi":



                    continue



                total += float(it.computed_total(as_of=as_of))



            ciro_by_table[int(table_id)] = round(total, 2)







    # Yetkiler



    has_region_ekle  = role in ('admin', 'cashier')



    has_masa_ekle    = role in ('admin', 'cashier')



    has_masa_arsivle = role in ('admin', 'cashier')







    return render_template(



        'admin/masalar.html',



        masalar=masalar,



        regions=regions,



        active_region_id=region_id,



        has_region_ekle=has_region_ekle,



        has_masa_ekle=has_masa_ekle,



        has_masa_arsivle=has_masa_arsivle,



        ciro_by_table=ciro_by_table,  # <<< template bu sözlüğü bekliyor



    )



# ---------------------



# BÖLGE OLUŞTUR (POST)



# ---------------------



@masa_bp.route('/admin/bolge-ekle', methods=['POST'], endpoint='region_ekle')



@login_required



@require('masa-ekle')



def region_ekle():







    name = (request.form.get('region_name') or '').strip()



    if not name:



        flash("Bölge adı boş olamaz.", "warning")



        return redirect(url_for('masa.masa_listesi'))







    existing = Region.query.filter(func.lower(Region.name) == name.lower()).first()



    if existing:



        flash("Bu isimde bir bölge zaten var.", "warning")



        return redirect(url_for('masa.masa_listesi'))







    db.session.add(Region(name=name))



    db.session.commit()



    flash("Bölge eklendi.", "success")



    return redirect(url_for('masa.masa_listesi'))







# -------------------



# MASA OLUŞTUR (POST)



# -------------------



@masa_bp.route('/admin/masa-ekle', methods=['POST'], endpoint='masa_ekle')



@login_required



@require('masa-ekle')



def masa_ekle():







    raw_name  = (request.form.get('name') or '').strip()



    region_id = request.form.get('region_id', type=int)







    name = " ".join(raw_name.split())



    if not name:



        flash("Masa adı boş olamaz.", "warning")



        return redirect(url_for('masa.masa_listesi'))







    region = None



    if region_id:



        region = Region.query.get(region_id)



        if not region:



            flash("Seçilen bölge bulunamadı.", "warning")



            return redirect(url_for('masa.masa_listesi'))







    aktif_var = (Table.query



                 .filter(



                     func.lower(Table.name) == name.lower(),



                     Table.is_archived.is_(False)



                 )



                 .first())



    if aktif_var:



        flash("Bu isimde **aktif** masa zaten var. Aynı ismi kullanmak istiyorsanız eskisini arşive alın.", "danger")



        target = url_for('masa.masa_listesi', region_id=region_id) if region_id else url_for('masa.masa_listesi')



        return redirect(target)







    try:



        t = Table(



            name=name,



            region_id=(region.id if region else None),



            status='boş',



            is_archived=False



        )



        db.session.add(t)



        db.session.commit()



    except IntegrityError as ie:



        db.session.rollback()



        current_app.logger.warning(f"[masa_ekle] IntegrityError: {ie}")



        flash("Bu isimde aktif masa az önce oluşturuldu. Lütfen farklı bir ad deneyin veya diğer masayı arşive alın.", "danger")



    except Exception as e:



        db.session.rollback()



        current_app.logger.exception(f"[masa_ekle] Beklenmeyen hata: {e}")



        flash("Masa eklenirken beklenmeyen bir hata oluştu.", "danger")







    target = url_for('masa.masa_listesi', region_id=region_id) if region_id else url_for('masa.masa_listesi')



    return redirect(target)







# -------------------------



# MASAYI ARŞİVLE / GERİ AL



# -------------------------



@masa_bp.route('/admin/masalar/<int:masa_id>/arsivle', methods=['POST'], endpoint='masa_arsivle')



@login_required



@require('masa-arsivle')



def masa_arsivle(masa_id):



    masa = Table.query.get_or_404(masa_id)



    if masa.is_archived:



        flash("Masa zaten arşivde.", "info")



        return redirect(url_for('masa.masa_listesi'))







    masa.is_archived = True



    db.session.commit()



    flash(f"'{masa.name}' arşive alındı.", "info")



    return redirect(url_for('masa.masa_listesi'))







@masa_bp.route('/admin/masalar/<int:masa_id>/arsivden-cikar', methods=['POST'], endpoint='masa_arsivden_cikar')



@login_required



def masa_arsivden_cikar(masa_id):



    if (getattr(current_user, "role", "") or "").lower() not in ('admin', 'cashier'):



        flash("Bu işlem için yetkiniz yok.", "danger")



        return redirect(url_for('masa.masa_listesi'))







    masa = Table.query.get_or_404(masa_id)



    if not masa.is_archived:



        flash("Masa zaten aktif.", "info")



        return redirect(url_for('masa.masa_listesi'))







    clash = (Table.query



             .filter(and_(func.lower(Table.name) == func.lower(masa.name),



                          Table.is_archived.is_(False),



                          Table.id != masa.id))



             .first())



    if clash:



        flash("Bu isimle aktif masa zaten var. Arşivden çıkarmadan önce yeniden adlandırın.", "danger")



        return redirect(url_for('masa.masa_listesi'))







    masa.is_archived = False



    db.session.commit()



    flash(f"'{masa.name}' arşivden çıkarıldı.", "success")



    return redirect(url_for('masa.masa_listesi'))







# ---------------------------------------------------------



# 🔸 MASA DASHBOARD (Jinja include ile panel)



# ---------------------------------------------------------



@masa_bp.route('/masa-dashboard/<int:masa_id>')



@login_required



@require('masa-listesi')



def masa_dashboard(masa_id):



    # --- TR saatine çeviren minik yardımcı (self-contained) ---



    from pytz import timezone, UTC



    TR = timezone("Europe/Istanbul")







    def _to_tr(dt):



        if not dt:



            return None



        # naive ise UTC varsayımı yapıp TR'ye çevir



        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:



            dt = UTC.localize(dt)



        return dt.astimezone(TR)







    now = datetime.utcnow()



    happy_hour_active = is_happy_hour()











    masa = Table.query.get_or_404(masa_id)



    if getattr(masa, "is_archived", False):



        flash("Arşivdeki masa görüntülenemez.", "warning")



        return redirect(url_for('masa.masa_listesi'))







    role = (getattr(current_user, "role", "") or "").lower()



    panel = (request.args.get("panel") or "").strip().lower()



    if role == "waiter":



        panel = "siparis"



    if panel not in ("siparis", "odeme"):



        panel = "siparis"







    aktif_siparis = (Order.query



                     .filter(Order.table_id == masa.id, Order.is_completed == false())



                     .order_by(Order.created_at.desc())



                     .first())







    tum_masalar = (db.session.query(Table.id, Table.name)



                   .filter(Table.is_archived.is_(False))



                   .order_by(Table.name.asc())



                   .all())







    urunler = (Product.query



               .filter(



                   Product.is_active.is_(True),



                   or_(Product.visible_for.is_(None), Product.visible_for != "gösterme")



               ).all())







    gruplu_urunler = {}



    for u in urunler:



        kat = u.category or "Diğer"



        alt = u.sub_category or "Genel"



        gruplu_urunler.setdefault(kat, {}).setdefault(alt, []).append(u)







    # ✅ Sol panel metaları



    left_item_display_totals = {}



    left_item_elapsed_mins = {}



    left_item_meta = {}   # (id -> {"waiter": str|None, "created_at": datetime|None [TR]})







    if aktif_siparis:



        now_left = datetime.utcnow()



        left_items = (OrderItem.query



                      .options(joinedload(OrderItem.product))



                      .filter(OrderItem.order_id == aktif_siparis.id,



                              OrderItem.status != 'iptal edildi')



                      .all())







        # Anlık tutar



        left_item_display_totals = {i.id: i.computed_total(as_of=now_left) for i in left_items}







        # Saatlik ürünlerde geçen süre (dk)



        for i in left_items:



            if i.product and i.product.is_timed and i.timed_started_at:



                end = i.timed_ended_at or now_left



                secs = max((end - i.timed_started_at).total_seconds(), 0)



                mins = int(secs // 60) + (1 if secs % 60 > 0 else 0)



                left_item_elapsed_mins[i.id] = mins







        # Garson isimlerini topluca çek



        waiter_ids = {i.added_by_user_id for i in left_items if getattr(i, "added_by_user_id", None)}



        user_names = {}



        if waiter_ids:



            for uid, uname in db.session.query(User.id, User.username).filter(User.id.in_(waiter_ids)).all():



                user_names[int(uid)] = uname







        # Garson + eklenme zamanı (TR) meta



        for i in left_items:



            wid = getattr(i, "added_by_user_id", None)



            waiter = user_names.get(int(wid)) if wid else None



            created_raw = getattr(i, "created_at", None)  # kolon yoksa None kalır



            created_tr = _to_tr(created_raw) if created_raw else None



            left_item_meta[i.id] = {"waiter": waiter, "created_at": created_tr}







    # ---- ÖDEME PANELİ ----



    order = None



    items = []



    total_price = 0.0



    total_paid = 0.0



    item_display_totals = {}



    money = {"total_items":0.0,"tahsilat":0.0,"indirim":0.0,"remain_net":0.0}







    if panel == "odeme":



        order = aktif_siparis



        if order is None:



            order = (db.session.query(Order)



                     .outerjoin(OrderItem, OrderItem.order_id == Order.id)



                     .filter(



                         Order.table_id == masa.id,



                         OrderItem.id.isnot(None),



                         OrderItem.status.notin_(['iptal edildi', 'ödendi'])



                     )



                     .order_by(Order.created_at.desc())



                     .first())







        if order:



            now = datetime.utcnow()



            if '_snapshot_overrides_to_now' in globals():



                _snapshot_overrides_to_now(order, now)



                db.session.commit()







            items = (OrderItem.query



                     .options(joinedload(OrderItem.product))



                     .filter_by(order_id=order.id)



                     .all())







            item_display_totals = {



                i.id: i.computed_total(as_of=now)



                for i in items if i.status != 'iptal edildi'



            }



            total_price = sum(item_display_totals.values())



            total_paid = sum(p.amount for p in (order.partial_payments or []))



            money = _calc_totals_breakdown(order)







    return render_template(



        "masa/masa_dashboard.html",



        masa=masa,



        aktif_siparis=aktif_siparis,



        panel=panel,



        gruplu_urunler=gruplu_urunler,



        order=order,



        items=items,



        total_price=total_price,



        total_paid=total_paid,



        tum_masalar=tum_masalar,



        item_display_totals=item_display_totals,



        left_item_display_totals=left_item_display_totals,



        left_item_elapsed_mins=left_item_elapsed_mins,



        left_item_meta=left_item_meta,  # created_at artık TR



        auto_print_jobs=session.pop("auto_print_jobs", None),



        happy_hour_active=happy_hour_active,



    )















# ---------------------------------------------------------



# 🔹 PANEL: Sipariş Ekleme (POST + Socket.IO yayın)



# ---------------------------------------------------------



@masa_bp.route('/masa/<int:masa_id>/siparis-ekle-panel', methods=['GET', 'POST'])



@login_required



@require('sipariş-ekle')



def siparis_ekle_panel(masa_id):



    masa = Table.query.get_or_404(masa_id)



    if masa.is_archived:



        flash("Arşivdeki masaya işlem yapılamaz.", "danger")



        return redirect(url_for('masa.masa_listesi'))







    order = Order.query.filter_by(table_id=masa.id, is_completed=false()).first()







    order_yeni_olustu = False



    if not order:



        order = Order(



            table_id=masa.id,



            served_by_user_id=getattr(current_user, "id", None),



            is_completed=False



        )



        db.session.add(order)



        masa.status = "dolu"



        db.session.flush()



        order_yeni_olustu = True







    if request.method == 'POST':



        # "gösterme" hariç ürünler



        urunler = Product.query.filter(Product.visible_for != "gösterme").all()



        product_map = {u.id: u for u in urunler}







        # Formdan adetleri toparla



        qty_aggregate = {}



        for key, val in request.form.items():



            if not key.startswith('product_'):



                continue



            try:



                pid = int(key.split('_', 1)[1])



            except ValueError:



                continue



            if not val or not val.isdigit():



                continue



            adet = int(val)



            if adet <= 0 or pid not in product_map:



                continue



            qty_aggregate[pid] = qty_aggregate.get(pid, 0) + adet







        if not qty_aggregate:



            return "En az bir ürün seçmelisiniz.", 400







        def _round_up_amount(amount: float, inc: float | None) -> float:



            if not inc or inc <= 0:



                return round(float(amount), 2)



            return round(math.ceil(amount / inc) * inc, 2)







        eklenen_kalem_sayisi = 0



        eklenen_urunler = []







        for pid, adet in qty_aggregate.items():



            note = request.form.get(f'note_{pid}', "")



            p = product_map[pid]







            visible_for_mapped = ("cay" if (p.visible_for or "").lower() == "bar"



                                  else (p.visible_for or "adisyon"))







            if p.is_timed:



                # SAATLİK ÜRÜN



                start_now = (p.auto_start_on_add is None) or bool(p.auto_start_on_add)







                initial_amount_preview = 0.0



                if (p.initial_minutes or 0) > 0 and (p.hourly_rate or 0) > 0:



                    raw = (float(p.initial_minutes) / 60.0) * float(p.hourly_rate)



                    initial_amount_preview = _round_up_amount(raw, p.price_round_inc)







                for _ in range(adet):



                    item = OrderItem(



                        order_id=order.id,



                        product_id=p.id,



                        quantity=1,



                        note=note or f"{p.name} (saatlik)"



                        ,



                        status='hazırlanıyor',



                        added_by_user_id=getattr(current_user, "id", None),







                        # sayaç



                        timed_started_at=(datetime.utcnow() if start_now else None),



                        timed_ended_at=None,







                        # 🔹 eklenen saat damgası



                        created_at=datetime.utcnow(),



                    )



                    db.session.add(item)







                eklenen_kalem_sayisi += adet



                eklenen_urunler.append({



                    "product_id": pid,



                    "name": p.name,



                    "unit_price": 0.0,



                    "display_price": initial_amount_preview,



                    "qty": adet,



                    "visible_for": visible_for_mapped,



                    "is_timed": True,



                    "started": start_now,



                })







            else:



                # NORMAL ÜRÜN



                for _ in range(adet):



                    item = OrderItem(



                        order_id=order.id,



                        product_id=pid,



                        quantity=1,



                        note=note,



                        status='hazırlanıyor',



                        added_by_user_id=getattr(current_user, "id", None),







                        # 🔹 eklenen saat damgası



                        created_at=datetime.utcnow(),



                    )



                    db.session.add(item)







                eklenen_kalem_sayisi += adet



                eklenen_urunler.append({



                    "product_id": pid,



                    "name": p.name,



                    "unit_price": float(p.price),



                    "qty": adet,



                    "visible_for": visible_for_mapped,



                    "is_timed": False,



                })







        db.session.commit()







        # ✅ QZ-Tray için HTML fişleri (değişmedi)



        try:



            waiter_name = getattr(current_user, "username", None)



            table_name = masa.name or f"Masa #{masa.id}"



            dt_tr = datetime.now(TR).strftime("%d.%m.%Y %H:%M")







            grouped: dict[str, dict[str, int]] = {}



            for it in eklenen_urunler:



                vis = (it.get("visible_for") or "").strip().lower()



                if not vis or vis == "gösterme":



                    continue



                name = it["name"]



                qty  = int(it.get("qty", 0) or 0)



                if qty <= 0:



                    continue



                grouped.setdefault(vis, {}).setdefault(name, 0)



                grouped[vis][name] += qty







            jobs = []



            for vis, name_qty_map in grouped.items():



                items_for_html = sorted(name_qty_map.items(), key=lambda x: x[0].lower())



                html_doc = _build_order_ticket_html(



                    waiter_name=waiter_name,



                    table_name=table_name,



                    items=items_for_html,



                    dt_tr=dt_tr



                )



                printer_name = vis



                jobs.append({



                    "printer": printer_name,



                    "type": "html",



                    "format": "plain",



                    "data": html_doc,



                    "meta": {



                        "table_id": masa.id,



                        "table_name": table_name,



                        "order_id": order.id,



                        "station": vis



                    }



                })







            if jobs:



                session["auto_print_jobs"] = jobs



        except Exception as e:



            current_app.logger.warning(f"[siparis_ekle_panel] auto_print_jobs prepare failed: {e}")







        payload = {



            "table_id": masa.id,



            "order_id": order.id,



            "event": "items_added",



            "items_added_count": eklenen_kalem_sayisi,



            "items": eklenen_urunler,



            "order_newly_created": order_yeni_olustu,



            "user_id": getattr(current_user, "id", None),



        }



        try:



            socketio.emit('yeni_siparis', {"message": "Yeni sipariş eklendi", "table_id": masa.id})



            socketio.emit('order:updated', payload)



            for it in eklenen_urunler:



                socketio.emit('order:item_added', {



                    "table_id": masa.id,



                    "order_id": order.id,



                    "item": it,



                    "visible_for": it["visible_for"]



                })



        except Exception as e:



            current_app.logger.warning(f"Socket emit failed: {e}")







        return redirect(url_for('masa.masa_dashboard', masa_id=masa_id, panel=''))







    return redirect(url_for('masa.masa_dashboard', masa_id=masa_id, panel='siparis'))











# ---------------------------------------------------------



# Yardımcılar (hesap & yazdırma)



# ---------------------------------------------------------



def _calc_totals(order: Order) -> tuple[float, float]:



    """Anlık toplam (computed_total) ve alınan toplam (legacy: tüm partial_payments)."""



    if not order:



        return 0.0, 0.0



    now = datetime.utcnow()



    items = (OrderItem.query



             .options(joinedload(OrderItem.product))



             .filter(OrderItem.order_id == order.id)



             .all())



    total_items = sum(i.computed_total(as_of=now) for i in items if i.status != 'iptal edildi')



    total_paid  = float(sum(pp.amount for pp in (order.partial_payments or [])))



    return float(total_items), float(total_paid)







def _sum_unpaid_items(order: Order) -> float:



    """Ödenmemiş kalemlerin anlık toplamı (iptaller hariç)."""



    if not order:



        return 0.0



    now = datetime.utcnow()



    items = (OrderItem.query



             .options(joinedload(OrderItem.product))



             .filter(OrderItem.order_id == order.id,



                     OrderItem.status.notin_(['iptal edildi', 'ödendi']))



             .all())



    return float(sum(i.computed_total(as_of=now) for i in items))







def _close_all_items(order: Order, when: datetime):



    """Tüm açık kalemleri kapat; saatlikse sayaç bitişini işaretle."""



    open_items = (OrderItem.query



                  .filter(OrderItem.order_id == order.id,



                          OrderItem.status.notin_(['iptal edildi', 'ödendi']))



                  .all())



    for it in open_items:



        if it.timed_started_at and not it.timed_ended_at:



            it.timed_ended_at = when



        it.status = 'ödendi'



    order.is_completed = True



    tbl = db.session.get(Table, order.table_id)



    if tbl:



        tbl.status = 'boş'







def _get_active_order(masa_id: int):



    # 1) Tamamlanmamış (False veya NULL) son sipariş



    o = (Order.query



         .filter(



             Order.table_id == masa_id,



             or_(Order.is_completed == false(), Order.is_completed.is_(None))



         )



         .order_by(Order.created_at.desc())



         .first())



    if o:



        return o







    # 2) Fallback: içinde ödenmemiş kalemi olan en son sipariş



    return (db.session.query(Order)



            .outerjoin(OrderItem, OrderItem.order_id == Order.id)



            .filter(



                Order.table_id == masa_id,



                OrderItem.id.isnot(None),



                OrderItem.status.notin_(['iptal edildi', 'ödendi'])



            )



            .order_by(Order.created_at.desc())



            .first())







def _freeze_item_price(it: OrderItem, when: datetime) -> float:



    """



    Kalemin o anki computed_total değerini total_price_override'a yazar.



    Öncesi ile farkı döndürür (bilgi amaçlı).



    """



    cur = float(it.computed_total(as_of=when))



    prev = float(it.total_price_override or 0.0)



    delta = max(0.0, cur - prev)



    if delta > 0:



        it.total_price_override = prev + delta



    return delta







def _freeze_all_open_items(order: Order, when: datetime) -> float:



    """



    Ödenmemiş/iptal olmayan tüm kalemleri freeze eder (istatistik için).



    Toplam eklenen tutarı döndürür.



    """



    open_items = (OrderItem.query



                  .options(joinedload(OrderItem.product))



                  .filter(OrderItem.order_id == order.id,



                          OrderItem.status.notin_(['iptal edildi', 'ödendi']))



                  .all())



    added = 0.0



    for it in open_items:



        added += _freeze_item_price(it, when)



    return added







def _snapshot_overrides_to_now(order: Order, when: datetime) -> None:



    """



    Anlık görüntü: Açık kalemlerin total_price_override'ını 'şu anki tutar'a eşitler.



    (Her GET odeme ekranında çağırıyoruz ki UI ile DB uyumlu kalsın.)



    """



    items = (OrderItem.query



             .options(joinedload(OrderItem.product))



             .filter(OrderItem.order_id == order.id,



                     OrderItem.status.notin_(['iptal edildi', 'ödendi']))



             .all())



    for it in items:



        cur = float(it.computed_total(as_of=when))



        it.total_price_override = cur







# ---- ÖDEME YÖNTEMİ / İNDİRİM YARDIMCILARI ----



def _normalize_pm(pm: str | None) -> str:



    return (pm or "").strip().lower()







def _is_discount_method(pm: str | None) -> bool:



    # front-end dropdownda 'indirim' kullanacağız



    return _normalize_pm(pm) == "indirim"







def _sum_payments(order: Order) -> tuple[float, float]:



    """



    (tahsilat, indirim) döner.



    - tahsilat: indirim HARİÇ tüm ödemeler toplamı



    - indirim : payment_method == 'indirim' toplamı



    """



    if not order or not getattr(order, "partial_payments", None):



        return 0.0, 0.0



    tahsilat = 0.0



    indirim  = 0.0



    for pp in (order.partial_payments or []):



        if _is_discount_method(pp.payment_method):



            indirim += float(pp.amount or 0.0)



        else:



            tahsilat += float(pp.amount or 0.0)



    return tahsilat, indirim







def _calc_totals_breakdown(order: Order) -> dict:



    """



    Tam fotoğraf:



      total_items: anlık kalem toplamı (iptaller hariç)



      tahsilat   : kasaya giren para toplamı (indirim HARİÇ)



      indirim    : indirim toplamı



      remain_net : ödenmesi gereken net (total_items - tahsilat - indirim)



    """



    total_items, _legacy = _calc_totals(order)



    tahsilat, indirim = _sum_payments(order)



    remain_net = max(0.0, float(total_items) - tahsilat - indirim)



    return {



        "total_items": float(total_items),



        "tahsilat": float(tahsilat),



        "indirim": float(indirim),



        "remain_net": float(remain_net),



    }







# ---------------------------------------------------------



# 🔸 HTML SİPARİŞ FİŞİ (QZ-Tray için)



# ---------------------------------------------------------



def _build_order_ticket_html(*, waiter_name: str | None, table_name: str, items: list[tuple[str, int]], dt_tr: str) -> str:



    """



    Basit HTML fiş (kalın yazı destekli). items: [(product_name, qty), ...]



    - İstenen alanlar: garson, tarih (TR), masa adı, ürün ve adet



    """



    rows = "\n".join(



        f"""<tr>



              <td style="padding:4px 0;"><strong>{qty}×</strong> {name}</td>



            </tr>"""



        for name, qty in items



    )



    waiter_line = f"<div><strong>Garson:</strong> {waiter_name}</div>" if waiter_name else ""



    return f"""<!doctype html>



<html>



  <head><meta charset="utf-8"></head>



  <body style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif; font-size:14px; margin:0; padding:12px;">



    <div style="text-align:center; margin-bottom:8px;">



      <div style="font-size:16px; font-weight:800;">NEXA — Sipariş Fişi</div>



    </div>



    <div style="margin-bottom:8px; line-height:1.5;">



      <div><strong>Masa:</strong> {table_name}</div>



      {waiter_line}



      <div><strong>Tarih:</strong> {dt_tr}</div>



    </div>



    <hr style="border:none; border-top:1px solid #ddd; margin:8px 0;">



    <table style="width:100%; border-collapse:collapse;">



      <tbody>



        {rows or '<tr><td>(Ürün yok)</td></tr>'}



      </tbody>



    </table>



    <hr style="border:none; border-top:1px solid #ddd; margin:8px 0;">



    <div style="text-align:center;">Afiyet olsun!</div>



  </body>



</html>"""







# ---------------------------------------------------------



# 🔹 Hugin köprü akış yardımcıları (kart ödemesi)



# ---------------------------------------------------------



def _is_card_method(pm: str) -> bool:



    """Kart yöntemini saptar (form tarafındaki adlandırmaların varyantlarını kapsa)."""



    if not pm:



        return False



    p = pm.strip().lower()



    return p in {"kredi_karti", "kredi-karti", "kart", "card", "pos", "kredi", "credit_card"}







# ---- Hugin gateway imza sarmalayıcıları (geriye uyumlu) ----



def _hg_pay_cash(sale_id, amount):



    """Yeni imza: pay_cash(sale_id, amount). Eski: pay_cash(amount)."""



    try:



        return hugin_gateway.pay_cash(sale_id, float(amount))



    except TypeError:



        return hugin_gateway.pay_cash(float(amount))







def _hg_pay_card(sale_id, amount, installment=1):



    """Yeni imza: pay_card(sale_id, amount, installment). Eski: pay_card(amount, installment)."""



    inst = int(max(1, int(installment or 1)))



    try:



        return hugin_gateway.pay_card(sale_id, float(amount), installment=inst)



    except TypeError:



        return hugin_gateway.pay_card(float(amount), installment=inst)







def _hg_close(sale_id):



    """Yeni imza: close(sale_id). Eski: close()."""



    try:



        return hugin_gateway.close(sale_id)



    except TypeError:



        return hugin_gateway.close()







def _hugin_sale_sequence(order: Order, amount: float, installment: int = 1) -> dict:



    try:



        items = [{"name": f"Adisyon #{order.id}", "qty": 1, "price": float(amount)}]



        r1 = hugin_gateway.start_sale(items, note=None)



        if not r1.get("ok"):



            return {"ok": False, "error": r1.get("error", "bridge_start")}



        sale_id = r1.get("sale_id")



        if not sale_id:



            return {"ok": False, "error": "no_sale_id"}







        r2 = hugin_gateway.pay_card(sale_id, float(amount), installment=max(1, int(installment or 1)))



        if not r2.get("ok"):



            return {"ok": False, "error": r2.get("error", "bridge_pay")}







        r3 = hugin_gateway.close(sale_id)



        if not r3.get("ok"):



            return {"ok": False, "error": r3.get("error", "bridge_close")}







        return {



            "ok": True,



            "mode": "hugin",



            "batch": r2.get("batch"),



            "stan": r2.get("stan"),



            "auth_code": r2.get("auth_code")



        }



    except Exception as e:



        current_app.logger.warning(f"[hugin] bridge error: {e}")



        return {"ok": False, "error": "bridge_exception"}



# ---------------------------------------------------------



# 🔹 PANEL: Ödeme Al (POST) — İNDİRİM ENTEGRASYONLU



# ---------------------------------------------------------



@masa_bp.route('/masa/<int:masa_id>/odeme', methods=['POST'])



@login_required



@require('ödeme-al')



def odeme_al_panel(masa_id):



    masa = Table.query.get_or_404(masa_id)



    order = _get_active_order(masa_id)







    if not order:



        flash("Aktif sipariş bulunamadı.", "warning")



        return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







    EPS = 0.01



    now = datetime.utcnow()  # 🔒 TEK ZAMAN KAYNAĞI 



    HAPPY_HOUR_PM = "indirim"



# =========================================================



# 0) HAPPY HOUR İNDİRİMİ



# =========================================================



    if request.form.get('happy_hour_submit') == '1':



        now = datetime.utcnow()







        if not is_happy_hour():



            flash("Happy Hour süresi sona ermiştir.", "danger")



            return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        order = _get_active_order(masa_id)



        if not order:



            flash("Aktif sipariş bulunamadı.", "warning")



            return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        # 🔒 DAHA ÖNCE UYGULANDI MI?



        already_used = (



            db.session.query(PartialPayment.id)



            .filter(



                PartialPayment.order_id == order.id,



                PartialPayment.payment_method == HAPPY_HOUR_PM



            )



            .first()



        )







        if already_used:



            flash("Happy Hour indirimi bu sipariş için zaten uygulanmış.", "warning")



            return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        _snapshot_overrides_to_now(order, now)



        db.session.flush()







        totals = _calc_totals_breakdown(order)



        remain_net = totals["remain_net"]







        if remain_net <= 0:



            flash("İndirim uygulanacak tutar yok.", "warning")



            return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        discount_amount = round(remain_net * HAPPY_HOUR_DISCOUNT_RATE, 2)







        db.session.add(PartialPayment(



            order_id=order.id,



            amount=discount_amount,



            payment_method=HAPPY_HOUR_PM



        ))







        db.session.commit()



        flash(f"Happy Hour indirimi uygulandı (%25): -{discount_amount}₺", "success")







        return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))











    # =========================================================



    # 1) TAM TUTAR ÖDE / İNDİR



    # =========================================================



    if request.form.get('full_submit') == '1':



        pm = (request.form.get('payment_method') or '').strip()



        if not pm:



            flash("Ödeme yöntemi seçiniz.", "warning")



            return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        # 🔒 SNAPSHOT SADECE BURADA



        _snapshot_overrides_to_now(order, now)



        db.session.flush()







        totals = _calc_totals_breakdown(order)



        remain_net = totals["remain_net"]







        if remain_net <= EPS:



            _close_all_items(order, now)



            db.session.commit()



            flash("Ödenecek tutar yoktu, sipariş kapatıldı.", "success")



            return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        is_disc = _is_discount_method(pm)







        if not is_disc and is_hugin_enabled() and _is_card_method(pm):



            br = _hugin_sale_sequence(order, remain_net, int(request.form.get('installment', '1') or 1))



            if not br.get("ok"):



                db.session.rollback()



                flash("Kart provizyonu alınamadı.", "danger")



                return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        db.session.add(PartialPayment(



            order_id=order.id,



            amount=remain_net,



            payment_method=pm



        ))







        _close_all_items(order, now)



        db.session.commit()



        flash("Sipariş kapatıldı.", "success")







    # =========================================================



    # 2) BELİRLİ TUTAR İLE ÖDE / İNDİR



    # =========================================================



    elif request.form.get('amount_submit') == '1':



        pm = (request.form.get('payment_method') or '').strip()



        try:



            amount = float(request.form.get('amount') or 0)



        except ValueError:



            amount = 0.0







        if amount <= 0 or not pm:



            flash("Geçerli tutar ve ödeme yöntemi giriniz.", "warning")



            return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        _snapshot_overrides_to_now(order, now)



        db.session.flush()







        totals = _calc_totals_breakdown(order)



        remain_net = totals["remain_net"]







        if amount > remain_net + EPS:



            flash("Tutar kalan borcu aşamaz.", "danger")



            return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        is_disc = _is_discount_method(pm)







        if not is_disc and is_hugin_enabled() and _is_card_method(pm):



            br = _hugin_sale_sequence(order, amount, int(request.form.get('installment', '1') or 1))



            if not br.get("ok"):



                db.session.rollback()



                flash("Kart provizyonu alınamadı.", "danger")



                return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        db.session.add(PartialPayment(



            order_id=order.id,



            amount=amount,



            payment_method=pm



        ))







        db.session.commit()



        flash("Ödeme kaydedildi.", "success")







    # =========================================================



    # 3) SEÇİLİ ÜRÜNLERLE ÖDE / İNDİR



    # =========================================================



    elif request.form.get('partial_submit') == '1':



        pm = (request.form.get('payment_method') or '').strip()



        selected = request.form.getlist('selected_items')







        if not selected or not pm:



            flash("Ürün ve ödeme yöntemi seçiniz.", "warning")



            return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        try:



            sel_ids = [int(x) for x in selected]



        except ValueError:



            flash("Geçersiz seçim.", "danger")



            return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        sel_items = (OrderItem.query



                     .options(joinedload(OrderItem.product))



                     .filter(



                         OrderItem.order_id == order.id,



                         OrderItem.id.in_(sel_ids),



                         OrderItem.status.notin_(['iptal edildi', 'ödendi'])



                     )



                     .all())







        if not sel_items:



            flash("Seçili kalemler uygun değil.", "warning")



            return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        sel_total = 0.0



        for it in sel_items:



            _freeze_item_price(it, now)   # 🔒 sadece seçili kalem



            sel_total += float(it.total_price_override or 0.0)







        totals = _calc_totals_breakdown(order)



        if sel_total <= EPS or sel_total > totals["remain_net"] + EPS:



            db.session.rollback()



            flash("Seçili kalem toplamı geçersiz.", "danger")



            return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        OrderItem.query.filter(



            OrderItem.id.in_(sel_ids),



            OrderItem.order_id == order.id



        ).update({



            OrderItem.status: 'ödendi',



            OrderItem.timed_ended_at: now



        }, synchronize_session=False)







        is_disc = _is_discount_method(pm)







        if not is_disc and is_hugin_enabled() and _is_card_method(pm):



            br = _hugin_sale_sequence(order, sel_total, int(request.form.get('installment', '1') or 1))



            if not br.get("ok"):



                db.session.rollback()



                flash("Kart provizyonu alınamadı.", "danger")



                return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







        db.session.add(PartialPayment(



            order_id=order.id,



            amount=sel_total,



            payment_method=pm



        ))







        db.session.commit()



        flash("Seçili ürünler kapatıldı.", "success")







    # =========================================================



    # ORTAK: NET SIFIRSA KAPAT



    # =========================================================



    totals_after = _calc_totals_breakdown(order)



    if totals_after["remain_net"] <= EPS:



        _close_all_items(order, now)



        db.session.commit()







    return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel='odeme'))







# ---------------------------------------------------------



# 🔸 ÜRÜN İPTAL (GÜNCEL)



# ---------------------------------------------------------



@masa_bp.route('/masa/<int:masa_id>/urun-iptal', methods=['POST'])



@login_required



@require('ürün-iptal')



def urun_iptal(masa_id):



    # Yetki kontrolü (senin önceki mantığın korunuyor)



    if (getattr(current_user, "role", "") or "").lower() not in ('-', 'cashier', 'admin'):



        flash("Yetkiniz yok.", "danger")



        return redirect(url_for('masa.masa_dashboard', masa_id=masa_id, panel=''))







    masa = Table.query.get_or_404(masa_id)



    if masa.is_archived:



        flash("Arşivdeki masaya işlem yapılamaz.", "danger")



        return redirect(url_for('masa.masa_listesi'))







    order = Order.query.filter_by(table_id=masa.id, is_completed=False).first()



    if not order:



        flash("Aktif sipariş bulunamadı.", "warning")



        return redirect(url_for('masa.masa_dashboard', masa_id=masa_id, panel=''))







    cancel_one = request.form.get("cancel_one")



    selected_ids = request.form.getlist("selected_items")



    reason = (request.form.get("cancel_reason") or "").strip()







    # Hedef kalemleri belirle



    target_ids = []



    if cancel_one:



        target_ids = [int(cancel_one)]



    elif selected_ids:



        try:



            target_ids = list(map(int, selected_ids))



        except ValueError:



            target_ids = []







    if not target_ids:



        flash("İptal için ürün seçilmedi.", "warning")



        return redirect(url_for('masa.masa_dashboard', masa_id=masa_id, panel=''))







    # İptal edilecek kalemler



    items = (OrderItem.query



             .filter(OrderItem.order_id == order.id,



                     OrderItem.id.in_(target_ids))



             .all())







    if not items:



        flash("İptal edilecek uygun kalem bulunamadı.", "warning")



        return redirect(url_for('masa.masa_dashboard', masa_id=masa_id, panel=''))







    affected = 0



    for it in items:



        if it.status in ('iptal edildi', 'ödendi'):



            continue



        it.status = 'iptal edildi'



        if reason:



            it.note = f"{(it.note + ' | ') if it.note else ''}İptal: {reason}"



        affected += 1







    if affected == 0:



        flash("Seçilen kalemler iptal edilemedi (önceden ödenmiş/iptal).", "warning")



        return redirect(url_for('masa.masa_dashboard', masa_id=masa_id, panel=''))







    # İptal sonrası otomatik kapatma: açık kalem yoksa siparişi tamamla ve masayı boşalt



    order_closed_now = False



    if not _has_open_items(order.id):



        order.is_completed = True



        masa.status = 'boş'



        order_closed_now = True







    # Socket yayını (opsiyonel)



    try:



        socketio.emit('order:item_cancelled', {



            "table_id": masa.id,



            "order_id": order.id,



            "item_ids": target_ids,



            "reason": reason



        })



    except Exception as e:



        current_app.logger.warning(f"[urun_iptal] socket emit failed: {e}")







    db.session.commit()







    if order_closed_now:



        flash(f"{affected} kalem iptal edildi. Açık kalem kalmadığı için sipariş kapatıldı ve masa boşaltıldı.", "success")



    else:



        flash(f"{affected} kalem iptal edildi.", "success")







    return redirect(url_for('masa.masa_dashboard', masa_id=masa_id, panel=''))







def _tr_simplify(text: str) -> str:



    """POS yazıcılarda codepage sorununa takılmamak için TR harflerini sadeleştirir."""



    if not text:



        return ""



    repl = str.maketrans({



        "Ç":"C","Ğ":"G","İ":"I","Ö":"O","Ş":"S","Ü":"U",



        "ç":"c","ğ":"g","ı":"i","ö":"o","ş":"s","ü":"u",



    })



    return text.translate(repl)







def _line_bytes(text: str = "", lf: int = 1) -> bytes:



    """Basit satır + LF."""



    return _tr_simplify(text).encode("ascii", errors="ignore") + (b"\n" * lf)







def _money(v: float) -> str:



    """₺ para formatı (TR biçimi)."""



    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")







def _pad_line(left: str, right: str, width: int = 32) -> bytes:



    """



    'left .... right' tek satır. width: yazıcının sütun genişliği.



    Birçok 58mm yazıcı 32, 80mm olanlar 42-48 sütun basar.



    """



    l = _tr_simplify(left)



    r = _tr_simplify(right)



    max_left = max(1, width - len(r) - 1)



    if len(l) > max_left:



        l = l[:max_left]



    spaces = max(1, width - len(l) - len(r))



    return (l + (" " * spaces) + r).encode("ascii", errors="ignore") + b"\n"







def _build_adisyon_hex(order: Order, line_width: int = 42) -> str:



    """ESC/POS adisyon: saatlik kalemleri anlık hesapla, diğerlerini adet topla yazdır."""



    from math import ceil







    # ESC/POS komutları



    ESC = b"\x1b"; GS = b"\x1d"



    INIT         = ESC + b"@"                # reset



    ALIGN_LEFT   = ESC + b"a" + b"\x00"



    ALIGN_CENTER = ESC + b"a" + b"\x01"



    BOLD_ON      = ESC + b"E" + b"\x01"



    BOLD_OFF     = ESC + b"E" + b"\x00"



    CUT_FULL     = GS  + b"V" + b"\x41" + b"\x03"   # tam kes







    masa = db.session.get(Table, order.table_id)



    masa_ad = getattr(masa, "name", f"Masa #{order.table_id}") or f"Masa #{order.table_id}"



    dt = datetime.now(TR).strftime("%d.%m.%Y %H:%M")







    # Şu an için hesapla (adisyon_yazdir zaten snapshotlıyor ama yine de tutarlı olsun)



    as_of_now = datetime.utcnow()







    # Kalemleri çek (iptaller hariç)



    items = (



        OrderItem.query



        .options(joinedload(OrderItem.product))



        .filter(



            OrderItem.order_id == order.id,



            OrderItem.status != 'iptal edildi',



        )



        .all()



    )







    # Saatlik olmayanları ürün bazında topla; saatlikleri tek tek yaz



    normal_agg = {}  # key=(name, unit) -> {"qty": int, "subtotal": float}



    timed_rows: list[tuple[str, float]] = []  # (label, subtotal)







    def _fmt_minutes(it: OrderItem) -> int:



        start = it.timed_started_at



        end = it.timed_ended_at or as_of_now



        if not start:



            return 0



        secs = max((end - start).total_seconds(), 0)



        # saniye varsa yukarı yuvarla (dakika)



        mins = int(secs // 60) + (1 if secs % 60 > 0 else 0)



        return mins







    for it in items:



        p = it.product



        if not p:



            # ürünü silinmiş olabilir; computed_total yine çalışıyorsa toplamı yaz



            label = f"Ürün #{it.product_id or '-'}"



            line_total = float(it.computed_total(as_of=as_of_now))



            timed_rows.append((label, line_total))



            continue







        line_total = float(it.computed_total(as_of=as_of_now))



        if getattr(p, "is_timed", False):



            mins = _fmt_minutes(it)



            label = f"{p.name} ({mins} dk)"



            timed_rows.append((label, line_total))



        else:



            unit = float(getattr(p, "price", 0.0) or 0.0)



            key = (p.name, unit)



            bucket = normal_agg.setdefault(key, {"qty": 0, "subtotal": 0.0})



            bucket["qty"] += int(it.quantity or 1)



            bucket["subtotal"] += unit * int(it.quantity or 1)







    # Satırları ESC/POS byte dizisine çevir



    satirlar: list[bytes] = []







    # Önce saatlik olmayanlar (isim sırası)



    for (name, unit) in sorted(normal_agg.keys(), key=lambda k: k[0].lower()):



        qty = normal_agg[(name, unit)]["qty"]



        subtotal = normal_agg[(name, unit)]["subtotal"]



        satirlar.append(_pad_line(f"{qty}x {name}", f"₺ {_money(subtotal)}", width=line_width))







    # Sonra saatlikler (ekrana yazıldıkları gibi)



    for label, subtotal in sorted(timed_rows, key=lambda x: x[0].lower()):



        satirlar.append(_pad_line(label, f"₺ {_money(subtotal)}", width=line_width))







    # Ara toplam: tüm satırların toplamı



    ara_toplam = 0.0



    for (_, unit) in normal_agg.keys():



        pass  # sadece okuma için; toplamı aşağıda tek döngüde hesaplayacağız



    ara_toplam = (



        sum(b["subtotal"] for b in normal_agg.values()) +



        sum(sub for _, sub in timed_rows)



    )







    # Ödemeler: İNDİRİM ayrı tutulur



    tahsilat, indirim = _sum_payments(order)



    kalan = max(0.0, ara_toplam - tahsilat - indirim)







    # Header + gövde + footer



    out = bytearray()



    out += INIT



    out += ALIGN_CENTER + BOLD_ON



    out += _line_bytes("NEXA CAFE")



    out += BOLD_OFF



    out += _line_bytes(f"{masa_ad}  ·  #{order.id}")



    out += _line_bytes(dt)



    out += _line_bytes("-" * line_width)







    out += ALIGN_LEFT



    if satirlar:



        for b in satirlar:



            out += b



    else:



        out += _line_bytes("(Kalem yok)")







    out += _line_bytes("-" * line_width)



    out += BOLD_ON



    out += _pad_line("Ara Toplam", f"₺ {_money(ara_toplam)}", width=line_width)



    out += _pad_line("Alınan",     f"₺ {_money(tahsilat)}",   width=line_width)



    out += _pad_line("İndirim",    f"₺ {_money(indirim)}",    width=line_width)



    out += _pad_line("Kalan",      f"₺ {_money(kalan)}",      width=line_width)



    out += BOLD_OFF







    out += _line_bytes("")



    out += ALIGN_CENTER



    out += _line_bytes("Tesekkur ederiz!")



    out += _line_bytes("")



    out += CUT_FULL







    return out.hex()







@masa_bp.get("/masa/<int:masa_id>/adisyon-yazdir")



@login_required



def adisyon_yazdir(masa_id):



    """QZ Tray'e verilecek adisyon payload'unu JSON döndürür.



       - Aktif siparişi bulur (yoksa en son sipariş).



       - Ekranda gördüğün anlık tutarı SABİTLER (snapshot),



         ama ÖDEME ALMAZ ve sayaçları bitirmez.



       - ESC/POS (hex) üretir.



    """



    masa = Table.query.get_or_404(masa_id)







    # 1) Siparişi bul



    order = _get_active_order(masa_id)



    if not order:



        order = (Order.query



                 .filter(Order.table_id == masa.id)



                 .order_by(Order.created_at.desc())



                 .first())



    if not order:



        return jsonify({"ok": False, "error": "Bu masada adisyon bulunamadı."}), 404







    # 2) Anlık görünümü DB'ye snapshotla (ödeme almadan, sayaçları durdurmadan)



    #    Böylece fişteki tutarlar o ana sabitlenir.



    try:



        now = datetime.utcnow()



        if '_snapshot_overrides_to_now' in globals():



            _snapshot_overrides_to_now(order, now)



            db.session.flush()  # yazdırmadan önce anlık override'lar diske yazılsın



    except Exception as e:



        current_app.logger.warning(f"[adisyon_yazdir] snapshot failed: {e}")







    # 3) ESC/POS içeriği üret (hex)



    #    _build_adisyon_hex içinde subtotal/ödemeler hesabı zaten yapılıyor.



    try:



        hex_payload = _build_adisyon_hex(order, line_width=42)



    except Exception as e:



        current_app.logger.exception(f"[adisyon_yazdir] build hex failed: {e}")



        return jsonify({"ok": False, "error": "Fiş oluşturulurken hata oluştu."}), 500







    # 4) Header bilgileri (masa adı, garson)



    table_name = getattr(masa, "name", str(masa_id))



    waiter_name = None



    try:



        if getattr(order, "served_by_user_id", None):



            w = db.session.get(User, order.served_by_user_id)



            if w and getattr(w, "username", None):



                waiter_name = w.username



    except Exception:



        pass







    # 5) Front-end’in beklediği sade payload (hem tek item, hem dizi olarak koyuyoruz)



    payload = {



        "ok": True,



        "printer": "adisyon",



        "type": "raw",



        "format": "hex",



        "data": hex_payload,



        "order_id": order.id,



        "table_id": masa.id,



        "table": table_name,          # backward compat: ad olarak da kullanıyorsun



        "table_name": table_name,     # açık isim



        "waiter_name": waiter_name,   # varsa garson adı



        # İstersen QZ’nin dizi formatını kullananlar için de hazır verelim:



        "qzPayload": [{



            "type": "raw",



            "format": "hex",



            "data": hex_payload



        }]



    }



    return jsonify(payload)







@masa_bp.post("/masa/<int:masa_id>/bitir/<int:item_id>", endpoint="item_bitir")



@login_required



@require('sipariş-ekle')  # uygun bir izin; istersen değiştir



def item_bitir(masa_id, item_id):



    """Saatlik ürünü ÖDEME ALMADAN dondur (süreyi durdur)."""



    # Masayı ve item'ı bul



    masa = Table.query.get_or_404(masa_id)



    it = (OrderItem.query



          .options(joinedload(OrderItem.product))



          .filter(OrderItem.id == item_id)



          .first_or_404())







    # Guard: aynı masanın siparişi mi?



    if it.order and it.order.table_id != masa.id:



        abort(400, "Ürün bu masaya ait değil.")







    # Sadece saatlik ve başlamış ama bitmemiş ise.



    if not (it.product and it.product.is_timed):



        flash("Bu kalem saatlik değil.", "warning")



        return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel=''))







    if not it.timed_started_at:



        flash("Saatlik ürün henüz başlatılmamış.", "warning")



        return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel=''))







    if it.timed_ended_at:



        # zaten dondurulmuş



        return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel=''))







    # Şimdi dondur (bitirme saati = şimdi). ÖDEME ALMA!



    now = datetime.utcnow()



    it.timed_ended_at = now







    # İsteğe bağlı: anlık tutarı override’a yaz (görsel toplam ile DB tam eşit kalsın)



    try:



        cur = float(it.computed_total(as_of=now))



        it.total_price_override = cur



    except Exception:



        pass







    db.session.commit()



    flash("Saatlik ürün durduruldu (ödeme alınmadı).", "success")



    return redirect(url_for('masa.masa_dashboard', masa_id=masa.id, panel=''))







