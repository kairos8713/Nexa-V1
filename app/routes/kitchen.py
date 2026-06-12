from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import OrderItem, db

kitchen_bp = Blueprint('kitchen', __name__)

@kitchen_bp.route('/kitchen')
@login_required
def kitchen_orders():
    if current_user.role not in ['mutfak', 'admin']:
        flash("Yetkisiz erişim", "danger")
        return redirect(url_for('auth.login'))
    
    # sadece yemek kategorisindeki sipariş öğelerini al
    items = OrderItem.query.join(OrderItem.product).filter(
        OrderItem.status != 'teslim edildi',
        OrderItem.product.category == 'yemek'
    ).all()

    return render_template('kitchen/orders.html', items=items)

@kitchen_bp.route('/kitchen/update_status/<int:item_id>', methods=['POST'])
@login_required
def update_status(item_id):
    if current_user.role not in ['mutfak', 'admin']:
        flash("Yetkisiz erişim", "danger")
        return redirect(url_for('auth.login'))

    item = OrderItem.query.get_or_404(item_id)
    new_status = request.form.get('status')

    if new_status in ['hazırlanıyor', 'hazır', 'teslim edildi']:
        item.status = new_status
        db.session.commit()
        flash("Sipariş durumu güncellendi", "success")
    else:
        flash("Geçersiz durum", "danger")

    return redirect(url_for('kitchen.kitchen_orders'))
