# app/__init__.py



from flask import Flask



from flask_sqlalchemy import SQLAlchemy



from flask_login import LoginManager



from flask_migrate import Migrate



from flask_socketio import SocketIO



from datetime import datetime



from pytz import timezone



from .errors import register_error_handlers







# ====== Global extensions ======



TR = timezone("Europe/Istanbul")



socketio = SocketIO(cors_allowed_origins="*")



db = SQLAlchemy()



login_manager = LoginManager()



migrate = Migrate()







def create_app():



    app = Flask(__name__)



    app.config['SECRET_KEY'] = 'gizli-anahtar'



    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///cafe.db'







    # 🔹 Hugin entegrasyonu başlangıç durumu (iz bırakmadan RAM'de tutuyoruz)



    #    Uygulama restartında varsayılanı burada belirle (True/False).



    app.config.setdefault('HUGIN_ENABLED', True)







    # ====== Init extensions ======



    socketio.init_app(app)



    db.init_app(app)



    login_manager.init_app(app)



    migrate.init_app(app, db)



    login_manager.login_view = "auth.login"







    # ====== Permissions ======



    from app import permissions



    permissions.init_app(app)







    # ====== User loader ======



    from app.models import User



    @login_manager.user_loader



    def load_user(user_id: str):



        if not user_id:



            return None



        try:



            return User.query.get(int(user_id))



        except Exception:



            return None







    # ====== Blueprints ======



    from app.routes.auth import auth_bp



    app.register_blueprint(auth_bp)







    from app.routes.menu import qr_bp



    app.register_blueprint(qr_bp)







    from app.routes.perm_admin import perms_bp



    app.register_blueprint(perms_bp)







    from app.routes.files_admin import files_bp



    app.register_blueprint(files_bp)







    from app.routes.garson import waiter_bp



    app.register_blueprint(waiter_bp)





    from app.routes.frontend import frontend_bp

    app.register_blueprint(frontend_bp)



    from app.api import api_bp

    app.register_blueprint(api_bp)





    from app.routes.urun import urun_bp



    app.register_blueprint(urun_bp)







    from app.routes.dashboard import dashboard_bp



    app.register_blueprint(dashboard_bp)







    from app.routes.gun_sonu import gun_sonu_bp



    app.register_blueprint(gun_sonu_bp)







    from app.routes.qz_api import qz_api



    app.register_blueprint(qz_api)







    from app.routes.gecmis import gecmis_bp



    app.register_blueprint(gecmis_bp)







    from app.services.hugin_bridge.hugin_gateway import hugin_bp



    app.register_blueprint(hugin_bp)











    from app.routes.kitchen import kitchen_bp



    from app.routes.bar import bar_bp



    from app.routes.masa import masa_bp



    from app.routes.istatistikler import istat_bp







    app.register_blueprint(istat_bp)



    app.register_blueprint(masa_bp)



    app.register_blueprint(kitchen_bp)



    app.register_blueprint(bar_bp)







    # 🔹 Hugin toggle endpoint’ini içeren admin blueprint’i kaydet



    #    (app/routes/admin.py içinde /toggle/hugin tanımlı olmalı)



    try:



        from app.routes.admin import admin_bp



        app.register_blueprint(admin_bp)



    except Exception:



        # admin_bp yoksa sessiz geç (opsiyonel: loglayabilirsin)



        pass







    from app.routes.cms import cms_bp



    app.register_blueprint(cms_bp)







    # ====== Context processors ======



    @app.context_processor



    def inject_globals():



        return {



            "current_year": datetime.now(TR).year,



            "brand_name": "Nexa",



        }







    # 🔹 Hugin durumunu tüm şablonlara enjekte et (Nexa ikonundaki nokta için)



    @app.context_processor



    def inject_hugin_flag():



        # import burada yapılır ki dairesel import oluşmasın



        from app.utils import is_hugin_enabled



        return {"HUGIN_ENABLED": is_hugin_enabled()}







    # ====== Errors ======



    register_error_handlers(app)







    return app



