from flask import current_app, abort
from flask_login import current_user
from functools import wraps

def is_hugin_enabled():
    val = current_app.config.get("HUGIN_ENABLED")
    return True if val is None else bool(val)

def set_hugin_enabled(state: bool):
    current_app.config["HUGIN_ENABLED"] = bool(state)

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator
