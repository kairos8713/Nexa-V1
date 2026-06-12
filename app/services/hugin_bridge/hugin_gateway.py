# app/services/hugin_gateway.py
import os, requests
from flask import Blueprint, jsonify

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://127.0.0.1:7080")

class HuginGateway:
    def __init__(self, base=BRIDGE_URL, timeout=15):
        self.base = base.rstrip("/")
        self.t = timeout
        self._sale_id = None  # tek-oturum modu için fallback

    def _url(self, path): return f"{self.base}{path}"

    def connect(self):
        r = requests.post(self._url("/connect"), timeout=self.t)
        return r.json()

    def start_sale(self, items, note=None):
        payload = {"items": items}
        if note: payload["note"] = note
        r = requests.post(self._url("/sale/start"), json=payload, timeout=self.t)
        data = r.json()
        self._sale_id = data.get("sale_id") or self._sale_id
        return data

    def pay_cash(self, sale_id, amount):
        r = requests.post(self._url("/sale/pay/cash"),
                          json={"sale_id": sale_id, "amount": amount},
                          timeout=self.t)
        return r.json()

    def pay_card(self, sale_id, amount, installment=1):
        r = requests.post(self._url("/sale/pay/card"),
                          json={"sale_id": sale_id, "amount": amount, "installment": installment},
                          timeout=self.t)
        return r.json()

    def close(self, sale_id):
        r = requests.post(self._url("/sale/close"), json={"sale_id": sale_id}, timeout=self.t)
        return r.json()

    def last_result(self):
        return requests.get(self._url("/sale/last_result"), timeout=self.t).json()

    # Hızlı saha testi
    def test_connection(self):
        try:
            c = self.connect()
            ok = bool(c.get("ok", True))
            return {"ok": ok, "bridge": self.base, "raw": c}
        except Exception as e:
            return {"ok": False, "bridge": self.base, "err": str(e)}

hugin_gateway = HuginGateway()

# İsteğe bağlı test endpoint'i:
hugin_bp = Blueprint("hugin", __name__)
@hugin_bp.route("/hugin/test")
def test_hugin():
    return jsonify(hugin_gateway.test_connection())
