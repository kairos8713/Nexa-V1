from flask import Blueprint, current_app, request, jsonify, send_file
from pathlib import Path
import base64

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes

qz_api = Blueprint("qz_api", __name__)

def _paths():
    """
    Uygulama köküne göre kesin (absolute) yolları döndür.
    current_app.root_path => .../cafe/app
    """
    app_root = Path(current_app.root_path)   # C:\Users\eemre\Documents\pythonprojects\cafe\app
    cert_path = app_root / "keys" / "digital-certificate.txt"
    key_path  = app_root / "keys" / "private-key.pem"
    return cert_path, key_path

@qz_api.route("/qz/cert")
def qz_cert():
    cert_path, _ = _paths()
    if not cert_path.exists():
        return jsonify({"error": "digital-certificate.txt not found", "path": str(cert_path)}), 500
    return send_file(cert_path, mimetype="text/plain")

@qz_api.route("/qz/sign", methods=["POST"])
def qz_sign():
    try:
        _, key_path = _paths()
        if not key_path.exists():
            return jsonify({"error": "private-key.pem not found", "path": str(key_path)}), 500

        payload = request.get_json(silent=True) or {}
        to_sign = payload.get("call", "")
        if not to_sign:
            return jsonify({"error": "empty 'call' field"}), 400

        # Private key yükle (parolasız PEM varsaydım; parolalıysa password=b"...")
        private_key = load_pem_private_key(key_path.read_bytes(), password=None)

        signature = private_key.sign(
            to_sign.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        sig_b64 = base64.b64encode(signature).decode("ascii")
        # QZ JS bu JSON içindeki "signature" alanını alacak
        return jsonify({"signature": sig_b64})
    except Exception as e:
        return jsonify({"error": str(e)}), 500