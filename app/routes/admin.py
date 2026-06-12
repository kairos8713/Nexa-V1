from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from app.utils import is_hugin_enabled, set_hugin_enabled
from app import socketio

admin_bp = Blueprint("admin", __name__)

def _can_toggle():
    role = (getattr(current_user, "role", "") or "").lower()
    return role in ("admin","cashier","cashier-lite")

@admin_bp.post("/toggle/hugin")
@login_required
def toggle_hugin():
    if not _can_toggle():
        from flask import abort; abort(403)
    new_state = not is_hugin_enabled()
    set_hugin_enabled(new_state)
    socketio.emit("hugin:state", {"enabled": new_state}, broadcast=True)
    return jsonify(enabled=new_state)