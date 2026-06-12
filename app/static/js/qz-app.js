// static/js/qz-app.js
(function () {
  const HOST_IP = '192.168.1.33';
  let securitySet = false;

  /* ======================= QZ SECURITY (senin uçların) ======================= */
  function setupSecurity() {
    if (securitySet || !window.qz) return;

    // SENİN /qz/cert ve /qz/sign uçların kullanılacak (hazır olanlar)
    qz.security.setCertificatePromise((resolve, reject) => {
      fetch('/qz/cert', { credentials: 'same-origin', cache: 'no-store' })
        .then(r => r.text()).then(resolve).catch(reject);
    });

    qz.security.setSignatureAlgorithm('SHA256');

    qz.security.setSignaturePromise(function (toSign) {
      return function (resolve, reject) {
        fetch('/qz/sign', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ call: toSign })
        })
        .then(async (r) => {
          const ct = r.headers.get('content-type') || '';
          if (ct.includes('application/json')) {
            const j = await r.json();
            if (j.signature) return resolve(String(j.signature));
            return reject(new Error(j.error || 'Signature JSON has no "signature"'));
          } else {
            const t = await r.text();
            return resolve(String((t || '').trim()));
          }
        })
        .catch(reject);
      };
    });

    securitySet = true;
  }

  /* ====== QZ CONNECT — eski tip { host, port, usingSecure } (8182/8181) ====== */
async function ensureConnected(host = HOST_IP) {
  setupSecurity();
  if (!window.qz) throw new Error('qz-tray.js yüklenemedi (script sırası?)');
  if (qz.websocket.isActive()) return;

  // Sayfa HTTPS ise WSS + 8181, HTTP ise WS + 8182
  const usingSecure = (location.protocol === 'https:');

  // QZ 2.x beklediği format: port nesnesi (DİZİLER!)
  const cfg = {
    host: [host],                           // dizi olması daha uyumlu
    usingSecure,
    port: {
      secure:   [8181, 8282, 8383, 8484],   // WSS denemeleri
      insecure: [8182, 8283, 8384, 8485]    // WS denemeleri
    },
    keepAlive: 60,
    retries: 1,
    delay: 1
  };

  console.log('[QZ] websocket.connect ->', cfg);
  await qz.websocket.connect(cfg);
  console.log('[QZ] bağlantı kuruldu ✓');
}

  /* ============================ Yardımcı (encode) ============================ */
  function hexText(str) {
    const enc = new TextEncoder();
    const bytes = enc.encode(String(str ?? ''));
    return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
  }

  /* === YENİ: Minimal ticket artık RASTER HTML döner (kalın + TR uyumlu) ===
     İMZA AYNI: { masa, siparisNo, satir } — çağıran kodu BOZMAYACAK. */
function buildMinimalTicket({ masa, siparisNo, satir, waiter_name, note, created_at_str } = {}) {
  // Saat (hh:mm) — p.created_at varsa onu kullan, yoksa şimdi
  function fmtTime(ts){
    try{
      if (!ts) throw 0;
      const d = new Date(ts);
      const hh = String(d.getHours()).padStart(2,'0');
      const mm = String(d.getMinutes()).padStart(2,'0');
      return `${hh}:${mm}`;
    }catch{
      const d = new Date();
      const hh = String(d.getHours()).padStart(2,'0');
      const mm = String(d.getMinutes()).padStart(2,'0');
      return `${hh}:${mm}`;
    }
  }
  const when = fmtTime(created_at_str);

  const html = `
    <div style="
      font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,'Helvetica Neue','Noto Sans','Liberation Sans',sans-serif;
      width:260px; line-height:1.3; font-weight:800; word-wrap:break-word; overflow-wrap:break-word;">
      
      ${siparisNo ? `<div style="text-align:center;font-size:20px;margin:0 0 6px;">SİPARİŞ NO: ${String(siparisNo).toUpperCase()}</div>` : ``}
      ${waiter_name ? `<div style="text-align:center;font-size:20px;margin:2px 0;">Garson: ${waiter_name}</div>` : ``}
      <div style="font-size:20px;margin:2px 0;">Saat: ${when}</div>
      <div style="font-size:20px;margin:2px 0 6px;">Masa: ${masa ?? '-'}</div>

      <hr style="border:0;border-top:2px dashed #000;margin:8px 0;">

      ${satir ? `<div style="font-size:24px;margin:8px 0;">${satir}</div>` : ``}
      ${note ? `<div style="font-size:20px;margin-top:4px;">Not: ${note}</div>` : ``}

      <hr style="border:0;border-top:2px dashed #000;margin:10px 0;">
      <div style="text-align:center;font-size:16px;">NEXA • Afiyet olsun</div>
    </div>
  `;

  return [{
    type: 'pixel',     // raster HTML -> TR karakter + kalın büyük yazı sorunsuz
    format: 'html',
    flavor: 'plain',
    data: html
  }];
}
  /* ================== Printer eşlemesi (bar → cay) ================== */
  function mapPrinterName(name) {
    const raw = String(name || 'adisyon').toLowerCase().trim();
    const m = {
      bar: 'cay',
      nargile: 'nargile',
      mutfak: 'mutfak',
      adisyon: 'adisyon'
    };
    return m[raw] || raw;
  }

  /* ====================== Güvenli Yazdırma Kuyruğu ====================== */
  const printQueue = [];
  let printing = false;

  async function enqueuePrintFor(printerName, dataArr, jobName = 'AutoTicket') {
    const mapped = mapPrinterName(printerName);

    if (typeof mapped !== 'string' || !mapped.trim()) {
      throw new Error('Geçersiz yazıcı adı');
    }
    if (!Array.isArray(dataArr) || dataArr.length === 0 || !dataArr[0]) {
      throw new Error('Boş yazdırma verisi');
    }
    dataArr.forEach((d, i) => {
      if (!d || typeof d !== 'object') throw new Error(`Yazdırma item[${i}] nesne değil`);
      if (!('type' in d) || !('data' in d)) throw new Error(`Yazdırma item[${i}] 'type' veya 'data' eksik`);
    });

    printQueue.push({ printerName: mapped.trim(), dataArr, jobName });
    if (printing) return;

    printing = true;
    try {
      await ensureConnected();
      while (printQueue.length) {
        const job = printQueue.shift();
        if (!job || !Array.isArray(job.dataArr) || !job.dataArr[0]) {
          console.warn('[QZ QUEUE] Bozuk job atlandı:', job);
          continue;
        }
        // ÖNEMLİ: rasterize:true — HTML bitmap’e çevrilsin (TR + Bold)
        const cfg = qz.configs.create({ name: job.printerName }, {
          jobName: job.jobName,
          copies: 1,
          rasterize: true
        });
        try {
          console.log('[QZ] print ->', { printer: job.printerName, job: job.jobName, items: job.dataArr.length });
          await qz.print(cfg, job.dataArr);
          console.log('[QZ] print ✓');
        } catch (perJobErr) {
          console.error('[QZ PRINT SINGLE JOB ERROR]', perJobErr, job);
        }
      }
    } catch (e) {
      console.error('[QZ QUEUE ERROR]', e);
      alert('Yazdırma kuyruğu hatası: ' + (e?.message || e));
    } finally {
      printing = false;
    }
  }

  /* ======================= Otomatik Yazdırma (Socket) ======================= */
  function initAutoPrint(socket) {
    if (!socket) { console.warn('[auto-print] socket yok'); return; }
    try { socket.off && socket.off('yeni_siparis'); } catch {}

    socket.on('yeni_siparis', async (payload) => {
      try {
        console.log('[auto-print] item_added payload:', payload);

        if (typeof window.qzEnsure             !== 'function' ||
            typeof window.qzPrintTicket        !== 'function' ||
            typeof window.qzBuildMinimalTicket !== 'function') {
          console.warn('[auto-print] qz helperları yok (qz-app.js doğru sırayla mı yüklendi?)');
          return;
        }

        const it       = payload?.item || {};
        const vis      = (payload?.visible_for ?? it.visible_for ?? 'adisyon');
        const qty      = Number(it.qty ?? 1);
        const name     = String(it.name ?? it.product_name ?? '').trim();
        const masaId   = payload?.table_id;
        const orderId  = payload?.order_id;

        if (!name) {
          console.warn('[auto-print] ürün adı boş, atlandı', payload);
          return;
        }

        await window.qzEnsure();

        // ÇAĞRI İSMİ DEĞİŞMEDİ → buildMinimalTicket artık raster HTML döndürüyor
        const line    = `${qty} x ${name}`.trim();
        const dataArr = window.qzBuildMinimalTicket({ masa: masaId, siparisNo: orderId, satir: line });

        if (!Array.isArray(dataArr) || !dataArr[0] || !dataArr[0].data) {
          console.warn('[auto-print] dataArr boş/bozuk, atlandı:', dataArr, payload);
          return;
        }

        await window.qzPrintTicket(vis, dataArr, `Ürün #${it.product_id ?? ''}`);
        console.log('[auto-print] yazdırıldı →', vis, line);
      } catch (e) {
        console.error('[auto-print] item_added hata:', e, payload);
      }
    });

    // istersen burada 'order:updated' da dinleyebilirsin — aynı akışla
  }

  /* ========================== MANUAL ADİSYON ========================== */
  async function printAdisyon(masaId, btn) {
    const setBusy = (busy) => {
      if (!btn) return;
      btn.disabled = !!busy;
      btn.classList.toggle('nx-btn-secondary', !!busy);
      btn.classList.toggle('nx-btn-teal', !busy);
      btn.textContent = busy ? '⏳ Yazdırılıyor…' : (btn.dataset._oldlabel || '🖨️ Adisyon Yazdır');
    };

    try {
      setBusy(true);
      if (!window.qz) throw new Error('qz-tray.js yüklenemedi (script sırası?)');

      await ensureConnected();

      const resp = await fetch(`/masa/${masaId}/adisyon-yazdir`, { credentials: 'same-origin', cache: 'no-store' });
      const text = await resp.text();
      let job;
      try { job = JSON.parse(text); }
      catch { throw new Error('Adisyon endpoint JSON yerine HTML döndürüyor (login olabilir)'); }
      if (!job?.ok) throw new Error(job?.error || 'Adisyon bulunamadı');

      let dataArr = [];
      if (Array.isArray(job.qzPayload) && job.qzPayload.length) dataArr = job.qzPayload;
      else if (job.type && job.data) dataArr = [{ type: String(job.type), format: String(job.format || 'plain'), data: job.data }];

      if (!dataArr.length) throw new Error('Backend yazdırma içeriği göndermedi.');

      const printerName = mapPrinterName(job.visible_for || job.printer || 'adisyon');
      await enqueuePrintFor(printerName, dataArr, `Adisyon #${masaId}`);

      if (btn) {
        btn.dataset._oldlabel = '🖨️ Adisyon Yazdır';
        btn.textContent = '✅ Yazdırıldı';
        setTimeout(() => btn.textContent = '🖨️ Adisyon Yazdır', 1200);
      }
    } catch (e) {
      console.error('[QZ PRINT ERROR]', e);
      alert('Yazdırma hatası: ' + (e?.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function qzSelfTest() {
    try {
      if (!window.qz) throw new Error('qz-tray.js yok');
      await ensureConnected();
      const cfg = qz.configs.create({ name: 'adisyon' }, { jobName: 'SelfTest', rasterize: true });
      await qz.print(cfg, [{ type: 'html', format: 'plain', data: '<div style="font-size:22px;font-weight:800">QZ Test ✅</div>' }]);
      console.log('Self-test OK');
    } catch (e) {
      console.error('Self-test hata', e);
      alert('Self-test hata: ' + (e?.message || e));
    }
  }

  // ---- PUBLIC EXPORTS ----
  window.printAdisyon         = printAdisyon;
  window.qzSelfTest           = qzSelfTest;
  window.initAutoPrint        = initAutoPrint;
  window.qzEnsure             = ensureConnected;
  window.qzPrintTicket        = (printer, data, job='AutoTicket') => enqueuePrintFor(printer, data, job);
  window.qzBuildMinimalTicket = buildMinimalTicket;

  // ---- QZ disconnect on unload ----
  window.addEventListener('beforeunload', () => {
    if (qz?.websocket?.isActive()) qz.websocket.disconnect().catch(() => {});
  });
})();
