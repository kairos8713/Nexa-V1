from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from app.models import db, BlogPost, Category, Product, AppSetting
from app.utils import role_required
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from app.services.image_service import ImageService

# Define Blueprint
cms_bp = Blueprint('cms', __name__, url_prefix='/admin/cms')

# --- Helper ---
def parse_published_at(date_str):
    if not date_str:
        return datetime.utcnow()
    try:
        # Check if it's datetime-local format (YYYY-MM-DDTHH:MM)
        return datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
    except ValueError:
        return datetime.utcnow()

# --- Dashboard ---
@cms_bp.route('/')
@login_required
def dashboard():
    # Only allow admin, menu_manager, cashier, or cashier-lite
    if current_user.role not in ['admin', 'menu_manager', 'cashier', 'cashier-lite']:
        flash("Yetkiniz yok.", "danger")
        return redirect(url_for('dashboard.index'))
        
    post_count = BlogPost.query.count()
    cat_count = Category.query.count()
    
    return render_template('admin/cms/dashboard.html', 
                           post_count=post_count, 
                           cat_count=cat_count)

# --- Blog Management ---
@cms_bp.route('/blog')
@login_required
def blog_list():
    if current_user.role not in ['admin', 'menu_manager', 'cashier', 'cashier-lite']:
        return redirect(url_for('cms.dashboard'))
    posts = BlogPost.query.order_by(BlogPost.created_at.desc()).all()
    return render_template('admin/cms/blog_list.html', posts=posts)

@cms_bp.route('/blog/new', methods=['GET', 'POST'])
@login_required
def blog_new():
    if current_user.role not in ['admin', 'menu_manager', 'cashier', 'cashier-lite']:
        return redirect(url_for('cms.dashboard'))
        
    if request.method == 'POST':
        title = request.form.get('title')
        slug = request.form.get('slug')
        content = request.form.get('content')
        seo_title = request.form.get('seo_title')
        seo_desc = request.form.get('seo_description')
        seo_keywords = request.form.get('seo_keywords')
        is_pub = request.form.get('is_published') == 'on'
        published_at_str = request.form.get('published_at')
        
        published_at = parse_published_at(published_at_str)
        
        # Handle Image
        cover_url = None
        if 'cover_image' in request.files:
            cover_url = ImageService.save_image(request.files['cover_image'], 'blog_covers')

        new_post = BlogPost(
            title=title,
            slug=slug,
            content=content,
            cover_image=cover_url,
            seo_title=seo_title,
            seo_description=seo_desc,
            seo_keywords=seo_keywords,
            is_published=is_pub,
            published_at=published_at
        )
        db.session.add(new_post)
        db.session.commit()
        flash("Blog yazısı oluşturuldu.", "success")
        return redirect(url_for('cms.blog_list'))

    return render_template('admin/cms/blog_edit.html', post=None)

@cms_bp.route('/blog/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def blog_edit(post_id):
    post = BlogPost.query.get_or_404(post_id)
    
    if current_user.role not in ['admin', 'menu_manager', 'cashier', 'cashier-lite']:
        return redirect(url_for('cms.dashboard'))

    if request.method == 'POST':
        post.title = request.form.get('title')
        post.slug = request.form.get('slug')
        post.content = request.form.get('content')
        post.seo_title = request.form.get('seo_title')
        post.seo_description = request.form.get('seo_description')
        post.seo_keywords = request.form.get('seo_keywords')
        post.is_published = request.form.get('is_published') == 'on'
        
        published_at_str = request.form.get('published_at')
        if published_at_str:
             post.published_at = parse_published_at(published_at_str)
        
        if 'cover_image' in request.files:
            path = ImageService.save_image(request.files['cover_image'], 'blog_covers')
            if path:
                post.cover_image = path
                
        db.session.commit()
        flash("Blog yazısı güncellendi.", "success")
        return redirect(url_for('cms.blog_list'))
        
    return render_template('admin/cms/blog_edit.html', post=post)

@cms_bp.route('/blog/delete/<int:post_id>')
@login_required
def blog_delete(post_id):
    if current_user.role not in ['admin', 'menu_manager', 'cashier', 'cashier-lite']:
        return redirect(url_for('cms.dashboard'))

    post = BlogPost.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash("Blog yazısı silindi.", "warning")
    return redirect(url_for('cms.blog_list'))

@cms_bp.route('/upload-image', methods=['POST'])
@login_required
def upload_image():
    """Endpoint for WYSIWYG editor image uploads"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    
    file = request.files['file']
    # We use a generic 'content_images' folder
    path = ImageService.save_image(file, 'content_images', optimize=True)
    
    if path:
        return jsonify({'location': path}) # TinyMCE expects { location: 'url' }
    return jsonify({'error': 'Upload failed'}), 500


# --- Menu Category Management ---
@cms_bp.route('/categories')
@login_required
def category_list():
    if current_user.role not in ['admin', 'menu_manager', 'cashier', 'cashier-lite']:
        return redirect(url_for('cms.dashboard'))
    categories = Category.query.order_by(Category.display_order).all()
    return render_template('admin/cms/category_list.html', categories=categories)

@cms_bp.route('/categories/update', methods=['POST'])
@login_required
def category_update():
    # Helper to add/edit categories quickly
    if current_user.role not in ['admin', 'menu_manager', 'cashier', 'cashier-lite']:
        return redirect(url_for('cms.dashboard'))

    cat_id = request.form.get('id')
    name = request.form.get('name')
    slug = request.form.get('slug')
    order = request.form.get('display_order', 0)
    is_visible = request.form.get('is_visible') == 'on' # Checkbox handling
    
    if cat_id:
        # Edit
        cat = Category.query.get(cat_id)
        if cat:
            cat.name = name
            cat.slug = slug
            cat.display_order = int(order)
            cat.is_visible = is_visible
            if 'image' in request.files:
                path = ImageService.save_image(request.files['image'], 'category_covers')
                if path:
                    cat.image_url = path
    else:
        # New
        img_url = None
        if 'image' in request.files:
             img_url = ImageService.save_image(request.files['image'], 'category_covers')
             
        new_cat = Category(
            name=name, 
            slug=slug, 
            display_order=int(order), 
            image_url=img_url,
            is_visible=is_visible
        )
        db.session.add(new_cat)
    
    db.session.commit()
    flash("Kategori güncellendi.", "success")
    return redirect(url_for('cms.category_list'))


# --- Settings Management ---
@cms_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if current_user.role not in ['admin', 'menu_manager', 'cashier', 'cashier-lite']:
        return redirect(url_for('cms.dashboard'))
        
    if request.method == 'POST':
        # List of expected keys
        keys = ['instagram_url', 'google_maps_code', 'site_title', 'seo_description']
        
        for key in keys:
            val = request.form.get(key, '')
            setting = AppSetting.query.get(key)
            if not setting:
                setting = AppSetting(key=key, value=val)
                db.session.add(setting)
            else:
                setting.value = val
        
        db.session.commit()
        flash("Ayarlar kaydedildi.", "success")
    
    # Fetch current settings
    all_settings = AppSetting.query.all()
    settings_dict = {s.key: s.value for s in all_settings}
    
    return render_template('admin/cms/settings.html', settings=settings_dict)
