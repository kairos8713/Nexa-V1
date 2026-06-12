from flask import jsonify, request, current_app
from . import api_bp
from app.models import Product, BlogPost, Category, AppSetting, db
from sqlalchemy import func, and_, or_
from datetime import datetime

# Helper to slugify (same as in menu.py, maybe move to utils later)
from unidecode import unidecode
def slugify(s):
    s = unidecode((s or "").strip().lower())
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("-")
    return "-".join([p for p in "".join(out).strip("-").split("-") if p])

@api_bp.route('/menu', methods=['GET'])
def get_menu():
    # 1. Fetch all visible products
    query = Product.query.filter(
        and_(
            or_(
                Product.visible_for.is_(None),
                Product.visible_for == "",
                Product.visible_for != "gösterme"
            ),
            Product.is_active == True
        )
    )
    products = query.all()

    # 2. Fetch Category Metadata
    categories_meta = Category.query.all()
    # Map slug -> Category
    meta_map = {c.slug: c for c in categories_meta}
    # Also map name -> Category for fallback lookup
    name_map = {c.name.lower(): c for c in categories_meta}

    # 3. Group products by category
    products_by_cat = {}
    
    for p in products:
        c_name = (p.category or "").strip()
        if not c_name:
            continue
            
        # Determine category slug/meta to check visibility
        slug = slugify(c_name)
        meta = meta_map.get(slug) or name_map.get(c_name.lower())
        
        # SKIP if category is explicitly hidden
        if meta and not meta.is_visible:
            continue
            
        if c_name not in products_by_cat:
            products_by_cat[c_name] = []
        
        # Add product to list
        products_by_cat[c_name].append({
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "sub_category": p.sub_category,
        })

    # 4. Construct Response
    result_categories = []
    
    for c_name, cat_products in products_by_cat.items():
        slug = slugify(c_name)
        meta = meta_map.get(slug) or name_map.get(c_name.lower())
        
        # Double check visibility (redundant but safe)
        if meta and not meta.is_visible:
            continue
            
        cat_data = {
            "name": meta.name if meta else c_name,
            "slug": meta.slug if meta else slug, 
            "image": meta.image_url if meta else None,
            "order": meta.display_order if meta else 999,
            "products": cat_products
        }
        result_categories.append(cat_data)
        
    # Sort by order, then name
    result_categories.sort(key=lambda x: (x['order'], x['name']))
    
    return jsonify(result_categories)

@api_bp.route('/blog', methods=['GET'])
def get_blog_posts():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    now = datetime.utcnow()
    
    query = BlogPost.query.filter(
        BlogPost.is_published == True,
        or_(BlogPost.published_at <= now, BlogPost.published_at == None)
    ).order_by(BlogPost.published_at.desc(), BlogPost.created_at.desc())
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
    posts = [p.to_dict() for p in pagination.items]
    
    return jsonify({
        "posts": posts,
        "total": pagination.total,
        "pages": pagination.pages,
        "current_page": page
    })

@api_bp.route('/blog/<slug>', methods=['GET'])
def get_blog_post(slug):
    now = datetime.utcnow()
    post = BlogPost.query.filter(
        BlogPost.slug == slug, 
        BlogPost.is_published == True,
        or_(BlogPost.published_at <= now, BlogPost.published_at == None)
    ).first_or_404()
    
    return jsonify(post.to_dict())

@api_bp.route('/settings', methods=['GET'])
def get_settings():
    settings = AppSetting.query.all()
    # Convert list of key-values to dict
    data = {s.key: s.value for s in settings}
    
    # Defaults if not in DB
    defaults = {
        "instagram_url": "https://www.instagram.com/veloya.lounge/",
        "google_maps_code": "",
        "site_title": "Nexa Lounge",
        "seo_description": "Best lounge in town."
    }
    
    # Merge defaults
    for k, v in defaults.items():
        if k not in data:
            data[k] = v
            
    return jsonify(data)
