# app/models.py
from app import db
from flask_login import UserMixin
from datetime import datetime
from sqlalchemy import Column, String, Text, text
import math


class AppSetting(db.Model):
    __tablename__ = "app_settings"
    key   = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)


# -----------------------------
# USERS (tek tablo)
# -----------------------------
class User(db.Model, UserMixin):
    __tablename__ = "users"

    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)  # mevcut yapını bozma
    role     = db.Column(db.String(20), nullable=False)   # 'admin' | 'cashier' | 'waiter' | 'menu_manager'
    is_on_shift = db.Column(db.Boolean, default=False, nullable=False)  # True -> mesai açık
    last_login  = db.Column(db.DateTime, nullable=True)   # ← yeni

    def get_id(self) -> str:
        return str(self.id)


class StaffShift(db.Model):
    __tablename__ = "staff_shifts"

    id        = db.Column(db.Integer, primary_key=True)
    user_id   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    start_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)
    end_at    = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref="shifts")

    def start(self):
        """Mesai başlatılır."""
        self.start_at = datetime.utcnow()

    def stop(self):
        """Mesai bitirilir/duraklatılır."""
        self.end_at = datetime.utcnow()


# -----------------------------
# LAYOUT
# -----------------------------
class Region(db.Model):
    __tablename__ = 'regions'
    id     = db.Column(db.Integer, primary_key=True)
    name   = db.Column(db.String(50), unique=True, nullable=False)
    tables = db.relationship('Table', back_populates='region')


class Table(db.Model):
    __tablename__ = 'tables'
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(20), nullable=False)
    region_id   = db.Column(db.Integer, db.ForeignKey('regions.id'), nullable=True)
    status      = db.Column(db.String(20), default='boş')
    is_archived = db.Column(db.Boolean, nullable=False, default=False, server_default="0")

    region = db.relationship('Region', back_populates='tables')

    __table_args__ = (
        db.Index('uq_tables_name_active', 'name', unique=True, sqlite_where=text('is_archived = 0')),
    )


# -----------------------------
# CATALOG & ORDERS
# -----------------------------
class Product(db.Model):
    __tablename__ = "product"
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(100), nullable=False)
    price        = db.Column(db.Float, nullable=False)
    category     = db.Column(db.String(50), nullable=True)
    stock        = db.Column(db.Integer, default=0)
    visible_for  = db.Column(db.String(20), default='gösterme')  # bar | mutfak | nargile | gösterme
    sub_category = db.Column(db.String(50), nullable=True)
    is_active    = db.Column(db.Boolean, nullable=False, default=True)
    deleted_at   = db.Column(db.DateTime, nullable=True)

    # ----- Saatlik ürün alanları (DEFAULT YOK) -----
    is_timed          = db.Column(db.Boolean, nullable=True)   # saatlik ürün mü?
    hourly_rate       = db.Column(db.Float,   nullable=True)   # TL/saat
    initial_minutes   = db.Column(db.Integer, nullable=True)   # açılışta min dakika (örn 30)
    price_round_inc   = db.Column(db.Float,   nullable=True)   # fiyat yuvarlama adımı (örn 5, 10)
    auto_start_on_add = db.Column(db.Boolean, nullable=True)   # eklendiği anda sayaç başlasın mı?


class Order(db.Model):
    __tablename__ = "orders"
    id             = db.Column(db.Integer, primary_key=True)
    table_id       = db.Column(db.Integer, db.ForeignKey('tables.id'), nullable=False, index=True)
    status         = db.Column(db.String(20), default='hazırlanıyor')
    created_at     = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Kim servis ediyor (eski waiter_id) -> users.id
    served_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    # Kim açtı -> users.id
    opened_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)

    is_completed   = db.Column(db.Boolean, default=False, nullable=False, index=True)
    items          = db.relationship("OrderItem", backref="order", cascade="all, delete-orphan")
    payment_method = db.Column(db.String(50), nullable=True)
    day_session_id = db.Column(db.Integer, db.ForeignKey('day_session.id'), index=True)
    day_session    = db.relationship('DaySession', backref='orders')


class OrderItem(db.Model):
    __tablename__ = "order_items"
    id         = db.Column(db.Integer, primary_key=True)
    order_id   = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, index=True)
    quantity   = db.Column(db.Float,   nullable=False, default=1.0)    
    note       = db.Column(db.String(255), nullable=True)
    status     = db.Column(db.String(20), default='hazırlanıyor', index=True)

    product = db.relationship("Product", backref="order_items", lazy="joined")  # ürün adını/price'ı Jinja'da güvenle kullanırız
    # Kim ekledi -> users.id
    added_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)

    # ---- Saatlik için sadece zaman bilgisi ----
    timed_started_at = db.Column(db.DateTime, nullable=True)  # sayaç başlangıcı
    timed_ended_at   = db.Column(db.DateTime, nullable=True)  # kapandığı an (ödeme/bitirme)

    # ---- (Opsiyonel) Fiyat override alanları; diğer yerlerde kullanılıyor olabilir ----
    total_price_override = db.Column(db.Float, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (db.CheckConstraint('quantity >= 0', name='ck_order_items_quantity_min'),)

    # ---------- Saatlik hesap yardımcıları (DB'ye fiyat yazmaz) ----------
    def _elapsed_minutes(self, as_of: datetime | None = None) -> int:
        """Saatlik item için geçen süre (dakika). Yukarı dakikaya yuvarlar."""
        if not self.timed_started_at:
            return 0
        end = self.timed_ended_at or as_of 
        secs = max((end - self.timed_started_at).total_seconds(), 0)
        return int(secs // 60) + (1 if secs % 60 > 0 else 0)

    @staticmethod
    def _round_up_amount(amount: float, inc: float | None) -> float:
        """Fiyatı inc katına YUKARI yuvarlar (ör: 223→225)."""
        if not inc or inc <= 0:
            return round(float(amount), 2)
        return round(math.ceil(amount / inc) * inc, 2)

    def computed_total(self, as_of: datetime | None = None) -> float:
        if self.status == 'iptal edildi':
            return 0.0

        # Saatlik ürün
        if (
            self.product
            and bool(getattr(self.product, "is_timed", False))
            and self.timed_started_at
            and (self.product.hourly_rate or 0) > 0
        ):
            mins      = self._elapsed_minutes(as_of=as_of)
            rate      = float(self.product.hourly_rate or 0.0)
            init_min  = int(self.product.initial_minutes or 0)
            round_inc = self.product.price_round_inc

            raw      = (mins / 60.0) * rate
            minimum  = (init_min / 60.0) * rate if init_min > 0 else 0.0
            base     = max(raw, minimum)

            return self._round_up_amount(base, round_inc)

        # ⬇️ NORMAL ÜRÜN: quantity artık FLOAT kullanılmalı
        if self.total_price_override is not None:
            return float(self.total_price_override)

        unit = float(getattr(self.product, "price", 0.0) or 0.0)
        qty  = float(self.quantity or 0.0)   # <-- BURASI DEĞİŞTİ (int → float)
        return round(unit * qty, 2)


class PartialPayment(db.Model):
    __tablename__ = 'partial_payments'
    id               = db.Column(db.Integer, primary_key=True)
    order_id         = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False, index=True)
    amount           = db.Column(db.Float, nullable=False)
    payment_method   = db.Column(db.String(20), nullable=False, index=True)
    paid_at          = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    # Kim tahsil etti -> users.id
    cashier_user_id  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)

    order = db.relationship('Order', backref='partial_payments')


class DaySession(db.Model):
    __tablename__ = 'day_session'
    id         = db.Column(db.Integer, primary_key=True)
    date       = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.DateTime, nullable=False, index=True)
    end_time   = db.Column(db.DateTime, nullable=True, index=True)
    is_closed  = db.Column(db.Boolean, default=False, nullable=False, index=True)


# -----------------------------
# Satır toplamı yardımcı (Jinja/servis tarafında aynı mantık)
# -----------------------------
def order_item_total(item: OrderItem, as_of: datetime | None = None) -> float:
    """
    """
    return float(item.computed_total(as_of=as_of))


# -----------------------------
# NEW CONTENT MODELS (Blog & Menu CMS)
# -----------------------------

class BlogPost(db.Model):
    __tablename__ = "blog_posts"
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.String(200), nullable=False)
    slug        = db.Column(db.String(200), unique=True, nullable=False)
    content     = db.Column(db.Text, nullable=False)  # HTML content
    cover_image = db.Column(db.String(255), nullable=True)
    
    # SEO
    seo_title       = db.Column(db.String(200), nullable=True)
    seo_description = db.Column(db.String(300), nullable=True)
    seo_keywords    = db.Column(db.String(300), nullable=True)  # New: Keywords
    
    published_at = db.Column(db.DateTime, default=datetime.utcnow) # New: Schedule date
    is_published = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "slug": self.slug,
            "content": self.content,
            "cover_image": self.cover_image,
            "seo_title": self.seo_title,
            "seo_description": self.seo_description,
            "seo_keywords": self.seo_keywords,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "is_published": self.is_published,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class Category(db.Model):
    __tablename__ = "categories"
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(100), unique=True, nullable=False)
    slug          = db.Column(db.String(100), unique=True, nullable=False)
    image_url     = db.Column(db.String(255), nullable=True)
    display_order = db.Column(db.Integer, default=0)
    
    is_visible    = db.Column(db.Boolean, default=True, nullable=False) # New: Menu visibility toggle
    
    # Optional: Relationship to products if we migrate Product.category (string) to ID
    # For now, keeping string link in Product, but this table manages the metadata.

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "image_url": self.image_url,
            "display_order": self.display_order,
            "is_visible": self.is_visible
        }

