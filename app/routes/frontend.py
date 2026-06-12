from flask import Blueprint, render_template, abort
from app.models import BlogPost, Category, AppSetting, Product, db
from sqlalchemy import or_, and_
import datetime

frontend_bp = Blueprint('frontend', __name__)

def get_app_settings():
    settings = AppSetting.query.all()
    data = {s.key: s.value for s in settings}
    defaults = {
        "instagram_url": "https://www.instagram.com/veloya.lounge/",
        "google_maps_code": "",
        "site_title": "Veloya Lounge",
        "seo_description": "Veloya Lounge - Doğanın Ruhu, Şehrin Nefesi."
    }
    for k, v in defaults.items():
        if k not in data:
            data[k] = v
    return data

@frontend_bp.route('/')
def index():
    settings = get_app_settings()
    return render_template('index.html', settings=settings)

@frontend_bp.route("/menu/nargile")
@frontend_bp.route('/menu')
def menu_categories():
    categories = Category.query.filter_by(is_visible=True).order_by(Category.display_order).all()
    settings = get_app_settings()
    return render_template('menu/menu_categories.html', categories=categories, settings=settings)

@frontend_bp.route('/menu/<slug>')
def menu_items(slug):
    category = Category.query.filter_by(slug=slug, is_visible=True).first_or_404()
    
    # Fetch active products for this category
    products = Product.query.filter(
        and_(
            Product.category == category.name,
            Product.is_active == True,
            or_(
                Product.visible_for.is_(None),
                Product.visible_for == "",
                Product.visible_for != "gösterme"
            )
        )
    ).all()
    
    # Group products by sub_category
    grouped_products = {}
    for p in products:
        sub = p.sub_category or 'Diğer'
        if sub not in grouped_products:
            grouped_products[sub] = []
        grouped_products[sub].append(p)

    settings = get_app_settings()
    return render_template('menu/menu_items.html', category=category, grouped_products=grouped_products, settings=settings)

@frontend_bp.route('/blog')
def blog_list():
    now = datetime.datetime.utcnow()
    posts = BlogPost.query.filter(
        BlogPost.is_published == True,
        or_(BlogPost.published_at <= now, BlogPost.published_at == None)
    ).order_by(BlogPost.published_at.desc(), BlogPost.created_at.desc()).all()
    
    settings = get_app_settings()
    return render_template('blog/blog_list.html', posts=posts, settings=settings)

@frontend_bp.route('/blog/<slug>')
def blog_post(slug):
    now = datetime.datetime.utcnow()
    post = BlogPost.query.filter(
        BlogPost.slug == slug,
        BlogPost.is_published == True,
        or_(BlogPost.published_at <= now, BlogPost.published_at == None)
    ).first_or_404()
    
    settings = get_app_settings()
    return render_template('blog/blog_post.html', post=post, settings=settings)
