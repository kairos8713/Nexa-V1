
from app import create_app, db
from app.models import Product, Category
from app.api.routes import slugify

app = create_app()
with app.app_context():
    print("Migrating Categories from Products...")
    
    # Get all distinct category names from products
    product_categories = db.session.query(Product.category).distinct().all()
    unique_names = [c[0] for c in product_categories if c[0]]
    
    count = 0
    for name in unique_names:
        slug = slugify(name)
        existing = Category.query.filter_by(slug=slug).first()
        
        if not existing:
            print(f"Creating category: {name} ({slug})")
            cat = Category(
                name=name,
                slug=slug,
                display_order=999
            )
            db.session.add(cat)
            count += 1
        else:
            print(f"Skipping existing: {name}")
            
    db.session.commit()
    print(f"Migration Complete. Created {count} categories.")
