# Eventlet kullanacaksan (Linux prod gibi) monkey_patch en BAŞTA olmalı

import os

USE_EVENTLET = os.getenv("SOCKETIO_BACKEND", "").lower() == "eventlet" and platform.system() != "Windows"

if USE_EVENTLET:

    import eventlet

    eventlet.monkey_patch()

# run.py







import sys

import platform



# Uygulama yolu

sys.path.insert(0, './app')



from app import create_app, socketio  # socketio: app/__init__.py içinde 1 kez yaratılmalı



app = create_app()



# Auto-create tables for new models (Category, BlogPost)

with app.app_context():

    from app import db

    db.create_all()





if __name__ == "__main__":

    # Windows/dev: threading; Linux/prod ve istek varsa: eventlet

    # Reloader KAPALI, tek proses. Debug False (reloader açmasın diye)

    run_kwargs = dict(

        host="0.0.0.0",

        port=int(os.getenv("PORT", "5000")),

        debug=True,           # <- reloader tetiklememesi için False

        use_reloader=True     # <- ÇİFT BAŞLATMAYI ENGELLER

    )



    # Bağlantı yönetimi daha stabil olsun diye ping ayarlarını app/__init__.py içinde verdik.

    socketio.run(app,**run_kwargs)

