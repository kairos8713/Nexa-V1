# bridge_server.py
import os, uuid, logging, traceback
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ---- LOGGING ----
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hugin-bridge")

# ---- Device import (gerçek POS sürüşü) ----
# device.py içinde Device ve PosError tanımlı olmalı. Import hatasında fallback stub kullanıyoruz.
try:
    from device import Device, PosError  # sizin gerçek sürücünüz
    POS_HOST = os.getenv("POS_HOST", "192.168.1.100")
    POS_PORT = int(os.getenv("POS_PORT", "4444"))
    dev = Device(POS_HOST, POS_PORT)
    log.info(f"Device bound to POS {POS_HOST}:{POS_PORT}")
except Exception as e:
    log.warning("device import/initialize failed, using dummy device; POS'a komut GİTMEZ!")
    log.warning(str(e))

    class PosError(Exception):
        pass

    class Device:
        def __init__(self, host="dummy", port=0): pass
        def start_sale(self, items, note=None):
            # sadece wiring testi için
            return {"ok": True}
        def pay_card(self, amount: float, installment: int = 1):
            return {"ok": True, "batch": "000000", "stan": "000000", "auth_code": "DUMMY"}
        def close_sale(self):
            return {"ok": True}

    dev = Device()

# ---- FastAPI app ----
app = FastAPI(title="Hugin Bridge", version="1.1")
sales: dict[str, dict] = {}  # sale_id -> context

# ---- Schemas ----
class Item(BaseModel):
    name: str
    qty: int
    price: float

class StartSaleReq(BaseModel):
    items: List[Item]
    note: Optional[str] = None

class PayReq(BaseModel):
    sale_id: str
    amount: float
    installment: int = 1

class CashReq(BaseModel):
    sale_id: str
    amount: float

class CloseReq(BaseModel):
    sale_id: str

# ---- Health/Connect ----
@app.get("/ping")
def ping():
    return {"ok": True}

@app.get("/connect")
def connect_get():
    return {"ok": True, "method": "GET"}

@app.post("/connect")
def connect_post():
    return {"ok": True, "method": "POST"}

# ---- Start ----
@app.post("/sale/start")
def sale_start(body: StartSaleReq):
    try:
        if not body.items:
            raise HTTPException(status_code=400, detail="items empty")

        # gerçek POS'a komut (device.py)
        r = dev.start_sale([i.dict() for i in body.items], body.note)
        if not (isinstance(r, dict) and r.get("ok", False)):
            raise HTTPException(status_code=502, detail="pos_start_failed")

        sale_id = str(uuid.uuid4())
        sales[sale_id] = {
            "items": [i.dict() for i in body.items],
            "paid": 0.0,
            "last": None,
            "note": body.note or None
        }
        return {"ok": True, "sale_id": sale_id}
    except PosError as e:
        log.warning(f"POS error: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log.error("bridge_start_exception:\n" + traceback.format_exc())
        raise HTTPException(status_code=500, detail="bridge_start_exception")

# ---- Pay Card ----
@app.post("/sale/pay/card")
def sale_pay_card(body: PayReq):
    try:
        ctx = sales.get(body.sale_id)
        if not ctx:
            raise HTTPException(status_code=400, detail="invalid_sale_id")
        r = dev.pay_card(float(body.amount), int(body.installment or 1))
        if not (isinstance(r, dict) and r.get("ok", False)):
            raise HTTPException(status_code=502, detail="pos_pay_failed")
        ctx["paid"] += float(body.amount)
        ctx["last"] = r
        return {"ok": True, **r}
    except PosError as e:
        log.warning(f"POS error: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        log.error("bridge_pay_exception:\n" + traceback.format_exc())
        raise HTTPException(status_code=500, detail="bridge_pay_exception")

# ---- Pay Cash (opsiyonel) ----
@app.post("/sale/pay/cash")
def sale_pay_cash(body: CashReq):
    ctx = sales.get(body.sale_id)
    if not ctx:
        raise HTTPException(status_code=400, detail="invalid_sale_id")
    ctx["paid"] += float(body.amount)
    ctx["last"] = {"method": "cash", "amount": float(body.amount)}
    return {"ok": True}

# ---- Close ----
@app.post("/sale/close")
def sale_close(body: CloseReq):
    try:
        ctx = sales.get(body.sale_id)
        if not ctx:
            raise HTTPException(status_code=400, detail="invalid_sale_id")
        r = dev.close_sale()
        if not (isinstance(r, dict) and r.get("ok", False)):
            raise HTTPException(status_code=502, detail="pos_close_failed")
        return {"ok": True}
    except PosError as e:
        log.warning(f"POS error: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        log.error("bridge_close_exception:\n" + traceback.format_exc())
        raise HTTPException(status_code=500, detail="bridge_close_exception")

# ---- Last Result (opsiyonel) ----
@app.get("/sale/last_result")
def last_result():
    if not sales:
        return {"ok": True, "last": None}
    k = next(reversed(sales.keys()))
    return {"ok": True, "sale_id": k, "result": sales[k].get("last")}

if __name__ == "__main__":
    # CLI: python bridge_server.py --listen 127.0.0.1:7080 --pos 192.168.1.100:4444 --timeout 10
    import argparse
    import uvicorn
    import logging

    parser = argparse.ArgumentParser(description="Hugin Bridge HTTP server")
    parser.add_argument("--listen", default="127.0.0.1:7080", help="host:port to listen (HTTP)")
    parser.add_argument("--pos", default="127.0.0.1:4444", help="POS address host:port")
    parser.add_argument("--timeout", type=float, default=10.0, help="POS socket timeout (s)")
    args = parser.parse_args()

    # Uygulama modülü import edilirken POS’a bağlanıyorsa, argümanları env ile geçiriyoruz.
    # (bridge_server içi Device init env’den okuyorsa bunlar işe yarar; değilse zaten import sırasında logta ‘Device bound…’ görmüşsünüzdür.)
    try:
        pos_host, pos_port = args.pos.split(":")
        os.environ["HUGIN_POS_HOST"] = pos_host
        os.environ["HUGIN_POS_PORT"] = pos_port
        os.environ["HUGIN_POS_TIMEOUT"] = str(args.timeout)
    except Exception:
        pass

    host, port = args.listen.split(":")
    logging.getLogger("hugin-bridge").info("Starting HTTP on %s:%s", host, port)

    # Not: module:app formatıyla çalıştırmak, yeniden import gerekmeden ‘app’i kullanır.
    uvicorn.run("bridge_server:app", host=host, port=int(port), log_level="info")
