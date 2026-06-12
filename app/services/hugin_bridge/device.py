# device.py
import os, socket, logging
from contextlib import closing

log = logging.getLogger("hugin-bridge.device")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(h)
log.setLevel(logging.INFO)

# ---- Konfig (ENV ile oynayacağız) ----
POS_HOST     = os.getenv("POS_HOST", "192.168.1.100")
POS_PORT     = int(os.getenv("POS_PORT", "4444"))
POS_TIMEOUT  = float(os.getenv("POS_TIMEOUT", "10"))

# El sıkışma: 1=ENQ/ACK yap, 0=atma
USE_HANDSHAKE = os.getenv("HUGIN_USE_HANDSHAKE", "1") == "1"

# Çerçeve tipi:
#   "STX_ETX_LRC"  => STX + payload + ETX + LRC (XOR)
#   "CRLF"         => payload + \r\n (bazı cihazlar böyle ister)
FRAME_MODE   = os.getenv("HUGIN_FRAME_MODE", "STX_ETX_LRC").upper()

# LRC Kapsamı:
#   "PAYLOAD"      => XOR(payload)
#   "PAYLOAD_ETX"  => XOR(payload + ETX)    (sık görülür)
#   "STX_PAYLOAD_ETX" => XOR(STX+payload+ETX)
LRC_SCOPE    = os.getenv("HUGIN_LRC_SCOPE", "PAYLOAD_ETX").upper()

# Cevap nasıl biter:
#   "STX_ETX_LRC"  => STX..ETX sonra 1 byte LRC bekle
#   "CRLF"         => \r\n görünce bitir
RESP_MODE    = os.getenv("HUGIN_RESP_MODE", "STX_ETX_LRC").upper()

# Kontrol karakterleri
ENQ, ACK, NAK, EOT, STX, ETX = 0x05, 0x06, 0x15, 0x04, 0x02, 0x03
CR, LF = 0x0D, 0x0A

class PosError(Exception):
    pass

def _ensure_bytes(data) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("ascii", errors="ignore")
    raise TypeError(f"payload type must be bytes/str, got {type(data)}")

def _hex(b: bytes) -> str:
    return b.hex().upper()

def _xor_lrc(buf: bytes) -> int:
    x = 0
    for b in buf:
        x ^= (b & 0xFF)
    return x & 0xFF

def _connect():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(POS_TIMEOUT)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    s.connect((POS_HOST, POS_PORT))
    return s

def _handshake(s: socket.socket):
    if not USE_HANDSHAKE:
        return
    enq = bytes([ENQ])
    log.info(f">> ENQ [{_hex(enq)}]")
    s.sendall(enq)
    b = s.recv(1)
    if not b:
        raise PosError("no_handshake_byte")
    log.info(f"<< HS  [{_hex(b)}]")
    if b[0] == ACK:
        return
    if b[0] == NAK:
        raise PosError("device_NAK_on_handshake")
    raise PosError(f"unexpected_handshake_byte_{_hex(b)}")

def _build_frame(payload: bytes) -> bytes:
    payload = _ensure_bytes(payload)
    if FRAME_MODE == "CRLF":
        frame = payload + bytes([CR, LF])
        log.info(f">> FRAME [{_hex(frame)}] len={len(frame)} (CRLF)")
        return frame
    # STX_ETX_LRC
    base = bytes([STX]) + payload + bytes([ETX])
    if LRC_SCOPE == "PAYLOAD":
        lrc = _xor_lrc(payload)
    elif LRC_SCOPE == "STX_PAYLOAD_ETX":
        lrc = _xor_lrc(base)
    else:  # PAYLOAD_ETX (varsayılan)
        lrc = _xor_lrc(payload + bytes([ETX]))
    frame = base + bytes([lrc])
    log.info(f">> FRAME [{_hex(frame)}] len={len(frame)} (STX/ETX/LRC)")
    return frame

def _send(s: socket.socket, payload: bytes):
    frame = _build_frame(payload)
    s.sendall(frame)

def _recv_stx_etx_lrc(s: socket.socket) -> bytes:
    # STX bekle
    b = s.recv(1)
    if not b or b[0] != STX:
        raise PosError(f"expected_STX_got_{_hex(b or b'')}")
    buf = bytearray()
    while True:
        ch = s.recv(1)
        if not ch:
            raise PosError("eof_before_ETX")
        if ch[0] == ETX:
            break
        buf.extend(ch)
    # LRC oku
    lrc_b = s.recv(1)
    if not lrc_b:
        raise PosError("missing_LRC")
    # LRC doğrula (aynı kural)
    payload = bytes(buf)
    if LRC_SCOPE == "PAYLOAD":
        calc = _xor_lrc(payload)
    elif LRC_SCOPE == "STX_PAYLOAD_ETX":
        calc = _xor_lrc(bytes([STX]) + payload + bytes([ETX]))
    else:
        calc = _xor_lrc(payload + bytes([ETX]))
    if lrc_b[0] != calc:
        raise PosError(f"lrc_mismatch recv={lrc_b[0]:02X} calc={calc:02X}")
    log.info(f"<< RESP_PAYLOAD [{_hex(payload)}] len={len(payload)}")
    return payload

def _recv_crlf(s: socket.socket) -> bytes:
    buf = bytearray()
    while True:
        ch = s.recv(1)
        if not ch:
            break
        buf.extend(ch)
        if len(buf) >= 2 and buf[-2:] == bytes([CR, LF]):
            break
    payload = bytes(buf[:-2]) if buf[-2:] == bytes([CR, LF]) else bytes(buf)
    log.info(f"<< RESP_LINE [{_hex(payload)}] len={len(payload)}")
    return payload

def _recv(s: socket.socket) -> bytes:
    if RESP_MODE == "CRLF":
        return _recv_crlf(s)
    return _recv_stx_etx_lrc(s)

# ---------- BURAYI .NET TESTİNDEKİ KOMUTLARA UYDUR ----------
def _payload_start(items: list[dict], note: str | None) -> bytes:
    # TODO: .NET’te POS’a giden gerçek gövde nasıl? Aynısını üret.
    # Şimdilik basit CSV benzeri bir örnek:
    lines = [f"SALE_START|{len(items)}"]
    for it in items:
        name = str(it.get("name","")) .replace("|","/")
        qty  = int(it.get("qty",1))
        price= float(it.get("price",0.0))
        lines.append(f"{name};{qty};{price:.2f}")
    if note:
        lines.append(f"NOTE;{note.replace('|','/')}")
    txt = "|".join(lines)
    return _ensure_bytes(txt)

def _payload_pay_card(amount: float, installment: int) -> bytes:
    return _ensure_bytes(f"PAY_CARD|{amount:.2f}|{int(max(1,installment))}")

def _payload_close() -> bytes:
    return b"CLOSE"

# ---------- Yüksek seviye API ----------
class Device:
    def __init__(self, host: str = POS_HOST, port: int = POS_PORT, timeout: float = POS_TIMEOUT):
        self.host = host; self.port = port; self.timeout = timeout

    def start_sale(self, items: list[dict], note: str | None = None) -> dict:
        try:
            with closing(_connect()) as s:
                _handshake(s)
                payload = _payload_start(items, note)
                _send(s, payload)
                resp = _recv(s)
                # TODO: resp parse (ör: b"OK|SALEID:123...")
                if resp.startswith(b"OK"):
                    return {"ok": True}
                return {"ok": False, "error": resp.decode('ascii','ignore')}
        except Exception as e:
            log.exception("start_sale_exception")
            raise

    def pay_card(self, amount: float, installment: int = 1) -> dict:
        try:
            with closing(_connect()) as s:
                _handshake(s)
                payload = _payload_pay_card(float(amount), int(installment or 1))
                _send(s, payload)
                resp = _recv(s)
                if resp.startswith(b"OK"):
                    # TODO: gerçek parse: batch/stan/auth_code’u resp’tan çıkar
                    return {"ok": True, "batch": "000001", "stan": "000002", "auth_code": "XXXXXX"}
                return {"ok": False, "error": resp.decode('ascii','ignore')}
        except Exception as e:
            log.exception("pay_card_exception")
            raise

    def close_sale(self) -> dict:
        try:
            with closing(_connect()) as s:
                _handshake(s)
                payload = _payload_close()
                _send(s, payload)
                resp = _recv(s)
                if resp.startswith(b"OK"):
                    return {"ok": True}
                return {"ok": False, "error": resp.decode('ascii','ignore')}
        except Exception as e:
            log.exception("close_sale_exception")
            raise
