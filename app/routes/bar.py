from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, func
from app.models import OrderItem, Product, Order, Table, db
from app import socketio

bar_bp = Blueprint('bar', __name__)

@bar_bp.route('/bar/panel', endpoint='bar_panel')
@login_required
def bar_orders():
    """
    Bar kalemleri:
      - Default: Product.category ILIKE 'bar'  OR  Product.sub_category ILIKE '%bar%'  OR  Product.visible_for == 'bar'
      - Status: 'hazırlanıyor' veya 'hazır'
    Teşhis için ?all=1 verildiğinde kategori filtresi devre dışı (tüm hazırlanan/hazır kalemler).
    """
    base_q = (
        db.session.query(OrderItem)
        .options(
            joinedload(OrderItem.product),
            joinedload(OrderItem.order).joinedload(Order.table)
        )
        .filter(OrderItem.status.in_(('hazırlanıyor', 'hazır')))
    )

    show_all = request.args.get('all') == '1'
    if show_all:
        items = base_q.all()
    else:
        items = (
            base_q.join(Product, OrderItem.product_id == Product.id)
            .filter(
                or_(
                    func.lower(Product.category) == 'bar',
                    func.lower(Product.sub_category).like('%bar%'),
                    Product.visible_for == 'bar'
                )
            )
            .all()
        )

    # Partial tbody (soft refresh için)
    if request.args.get('partial') == '1':
        return render_template('bar/_tbody_fragment.html', items=items)

    return render_template('bar_panel.html', items=items)


@bar_bp.route('/bar/durum-guncelle/<int:item_id>', methods=['POST'])
@login_required
def bar_durum_guncelle(item_id):
    if current_user.role not in ['bar', 'admin']:
        flash("Yetkisiz erişim", "danger")
        return redirect(url_for('auth.login'))

    item = OrderItem.query.get_or_404(item_id)

    if item.status == "hazırlanıyor":
        item.status = "hazır"
        db.session.commit()
        flash(f"{item.product.name} hazırlandı.", "success")

        # Socket.IO (broadcast parametresi yok)
        payload = {
            "item_id": item.id,
            "order_id": item.order_id,
            "table_id": item.order.table_id if item.order else None,
            "event": "item_ready",
            "product_name": item.product.name if item.product else None,
        }
        try:
            socketio.emit('order:updated', payload)
            socketio.emit('bar:item_updated', payload)
        except Exception:
            pass
    else:
        flash("Ürün zaten hazır.", "info")

    return redirect(url_for('bar.bar_panel'))
