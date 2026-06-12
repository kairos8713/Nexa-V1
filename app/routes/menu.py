# app/routes/menu_qr.py
from flask import Blueprint, render_template, url_for, abort
from sqlalchemy import func, or_, and_
from unidecode import unidecode
from app.models import Product

qr_bp = Blueprint("qrmenu", __name__, url_prefix="/old_menu")  # /menu, /menu/<slug> ...

def slugify(s: str) -> str:
    s = unidecode((s or "").strip().lower())
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("-")
    return "-".join([p for p in "".join(out).strip("-").split("-") if p])

def _visible_products_query():
    from sqlalchemy import and_, or_
    return Product.query.filter(
        and_(
            or_(
                Product.visible_for.is_(None),
                Product.visible_for == "",
                Product.visible_for != "gösterme"
            ),
            Product.is_active == True
        )
    )


# ---- Kapak görselleri (opsiyonel) ----
COVER_MAP = {
    "nargile": "nargile.jpg",
    "sicak-icecekler": "sicak_icecekler.jpg",
    "soguk-icecekler": "soguk_icecekler.jpg",
    "tatlilar": "tatlilar.jpg",
    "ana-yemekler": "ana_yemekler.jpg",
    "gune-baslarken": "gune_baslarken.jpg",
}
DEFAULT_COVER = "gune_baslarken.jpg"

def cover_for(slug: str) -> str:
    fname = COVER_MAP.get(slug, DEFAULT_COVER)
    return url_for("static", filename=f"images/{fname}")

@qr_bp.route("/")
@qr_bp.route("/nargile")   # alias: kategori seçimi
def menu_home():
    base = _visible_products_query()  # <-- TÜM ürünler

    # distinct kategori isimleri (None/boş hariç)
    cat_names = sorted(
        {(c[0] or "").strip()
         for c in base.with_entities(Product.category).distinct()
         if (c[0] or "").strip()},
        key=lambda x: x.lower()
    )

    categories = []
    for cname in cat_names:
        slug = slugify(cname)

        # 🔹 alias kontrolü
        display_slug = "hookah" if slug == "nargile" else slug

        # Önizleme: bu kategoriye ait TÜM ürünlerden ilk 3
        preview_rows = (
            base.filter(func.lower(Product.category) == cname.lower())
                .with_entities(Product.name, Product.price)
                .order_by(Product.sub_category.asc(), Product.name.asc())
                .limit(3)
                .all()
        )
        # Toplam adet (tamamı)
        count = (
            base.filter(func.lower(Product.category) == cname.lower())
                .with_entities(func.count(Product.id)).scalar() or 0
        )

        categories.append({
            "name": cname,
            "slug": display_slug,  # gerçek slug (örn: nargile)
            "count": int(count),
            "preview": [{"name": n, "price": float(p or 0)} for (n, p) in preview_rows],
            "cover": cover_for(slug),
            # 🔹 link: nargile yerine hookah kullan
            "href": url_for("qrmenu.menu_category", category_slug=display_slug),
        })

    return render_template("qr_theme/menu.html", categories=categories)


# !!! DİKKAT: Ayrı bir @qr_bp.route("/nargile") fonksiyonu EKLEME!
# Yukarıdaki dekoratör alias yeterli; aksi halde route çakışır.

# ---- Kategori sayfası: /menu/<slug> ----
@qr_bp.route("/<category_slug>")
def menu_category(category_slug):
    base = _visible_products_query()  # tüm ürünler

    # 🔹 URL alias haritası
    ALIASES = {
        "hookah": "nargile",  # /menu/hookah → nargile ürünleri
    }
    query_slug = ALIASES.get(category_slug, category_slug)

    # slug → kategori adları
    rows = base.with_entities(Product.category).distinct().all()
    slug_groups = {}
    for (raw_cat,) in rows:
        if not raw_cat:
            continue
        real = (raw_cat or "").strip()
        s = slugify(real)
        slug_groups.setdefault(s, set()).add(real)

    if query_slug not in slug_groups:
        abort(404)

    candidate_names = sorted(slug_groups[query_slug])

    rows = (
        base.filter(Product.category.in_(candidate_names))
            .with_entities(Product.name, Product.price, Product.sub_category)
            .order_by(Product.sub_category.asc(), Product.name.asc())
            .all()
    )

    from collections import defaultdict
    buckets = defaultdict(list)
    for name, price, sub in rows:
        buckets[(sub or "Diğer").strip()].append({
            "name": name,
            "price": float(price or 0),
            "description": "",
        })

    sections = [
        {"title": title, "items": items}
        for title, items in sorted(buckets.items(), key=lambda x: x[0].lower())
    ]

    category = {
        "name": next(iter(candidate_names)),   # Örn: "Nargile"
        "cover": cover_for(query_slug),
        "sections": sections,
        "link": category_slug,                 # URL’de görünen (örn: hookah)
        "source_slug": query_slug,             # Gerçekte kullanılan slug (örn: nargile)
    }

    # ürün listesi ayrıca döndürülüyor
    items = [it for _, items in buckets.items() for it in items]

    return render_template(
        "qr_theme/nargile.html",
        category=category,
        items=items,
    )

