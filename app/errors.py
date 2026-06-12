# app/errors.py
from flask import render_template, request, jsonify
from werkzeug.exceptions import HTTPException

def wants_json() -> bool:
    # XHR/fetch veya JSON kabulü daha yüksekse JSON dön
    if request.headers.get("X-Requested-With", "").lower() in ("xmlhttprequest", "fetch"):
        return True
    accept = request.accept_mimetypes
    return accept.best == "application/json" and accept["application/json"] > accept["text/html"]

def register_error_handlers(app):
    @app.errorhandler(403)
    def forbidden(e):
        code = 403
        msg = getattr(e, "description", "Bu sayfaya erişim yetkiniz yok.")
        if wants_json():
            return jsonify(ok=False, error="forbidden", message=msg), code
        return render_template("errors/403.html", message=msg), code

    @app.errorhandler(404)
    def not_found(e):
        import os
        from flask import current_app, send_from_directory
        
        # Determine if it's an API request
        if request.path.startswith('/api/'):
            code = 404
            msg = getattr(e, "description", "Aradığın sayfayı bulamadık.")
            return jsonify(ok=False, error="not_found", message=msg), code
            
        # For non-API requests, fallback to Next.js SPA
        root_dir = os.path.dirname(current_app.root_path)
        out_dir = os.path.join(root_dir, 'frontend', 'out')
        
        path = request.path.lstrip('/')
        
        # 1. Check if specific HTML exists (e.g. /menu -> /menu.html)
        if path:
            html_path = path + ".html"
            if os.path.exists(os.path.join(out_dir, html_path)):
                return send_from_directory(out_dir, html_path)
                
            # 2. Check for index.html in directory (e.g. /menu/ -> /menu/index.html)
            index_path = os.path.join(path, "index.html")
            if os.path.exists(os.path.join(out_dir, index_path)):
                return send_from_directory(out_dir, index_path)
        
        # Fallback to SPA index.html mostly for React routers
        if os.path.exists(os.path.join(out_dir, "index.html")):
            return send_from_directory(out_dir, "index.html")
            
        # Ultimate fallback if out/ is missing
        code = 404
        msg = getattr(e, "description", "Aradığın sayfayı bulamadık.")
        if wants_json():
            return jsonify(ok=False, error="not_found", message=msg), code
        return render_template("errors/404.html", message=msg), code

    @app.errorhandler(405)
    def method_not_allowed(e):
        code = 405
        msg = getattr(e, "description", "Bu işlem için yöntem (HTTP method) geçerli değil.")
        if wants_json():
            return jsonify(ok=False, error="method_not_allowed", message=msg), code
        return render_template("errors/405.html", message=msg), code

    # Opsiyonel ama önerilir: 500 → prod’da kullanıcı dostu
    @app.errorhandler(500)
    def internal_error(e):
        code = 500
        if isinstance(e, HTTPException):
            # bazen debug/HTTPException 500 gibi gelebilir
            msg = getattr(e, "description", "Beklenmeyen bir hata oluştu.")
        else:
            msg = "Beklenmeyen bir hata oluştu."
        if wants_json():
            return jsonify(ok=False, error="internal_error", message=msg), code
        return render_template("errors/500.html", message=msg), code

    @app.errorhandler(401)
    def unauthorized(e):
        code = 401
        msg = getattr(e, "description", "Bu sayfaya erişmek için giriş yapmanız gerekiyor.")
        if wants_json():
            return jsonify(ok=False, error="unauthorized", message=msg), code
        # login sayfası varsa URL'sini gönderelim
        return render_template("errors/401.html", message=msg), code