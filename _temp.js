const window = {location:{reload:()=>{}}, addEventListener:()=>{}}; 
const document = {getElementById:()=>null, addEventListener:()=>{}}; 
const sessionStorage = {getItem:()=>null, setItem:()=>null}; 
const console = {log:()=>{}, warn:()=>{}, error:()=>{}}; 
const io = () => ({on:()=>{}}); 




      const sound = document.getElementById('notificationSound');







      // --- Audio unlock (iOS/Chrome autoplay kısıtı) ---



      const UNLOCK_KEY = 'nx_audio_unlocked';



      let audioCtx = null;







      function showUnlock() {



        const layer = document.getElementById('nx-audio-unlock');



        if (layer) layer.style.display = 'flex';



      }



      function hideUnlock() {



        const layer = document.getElementById('nx-audio-unlock');



        if (layer) layer.style.display = 'none';



      }



      async function unlockAudio() {



        try {



          // 1) <audio> play ile dene



          if (sound) {



            sound.muted = false;



            sound.currentTime = 0;



            await sound.play().catch(() => { });



          }



          // 2) WebAudio ile minik bip (bazı cihazlar bunu “gesture” sayar)



          if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();



          if (audioCtx.state === 'suspended') await audioCtx.resume();



          const o = audioCtx.createOscillator();



          const g = audioCtx.createGain();



          o.connect(g); g.connect(audioCtx.destination);



          g.gain.setValueAtTime(0.0001, audioCtx.currentTime);



          g.gain.exponentialRampToValueAtTime(0.2, audioCtx.currentTime + 0.01);



          o.frequency.value = 880; // kısa tiz bip



          o.start();



          o.stop(audioCtx.currentTime + 0.06);



          sessionStorage.setItem(UNLOCK_KEY, '1');



          hideUnlock();



        } catch (e) {



          // Başarısızsa tekrar iste



          showUnlock();



        }



      }







      document.getElementById('nx-audio-btn')?.addEventListener('click', unlockAudio);



      // Kullanıcı herhangi bir etkileşim yaptığında da deneyelim



      ['click', 'touchstart', 'keydown'].forEach(ev => window.addEventListener(ev, () => {



        if (sessionStorage.getItem(UNLOCK_KEY) !== '1') unlockAudio();



      }, { once: false, passive: true }));







      // --- Ses çalma + refresh akışı ---



      async function playBeepThen(cb) {
        try {
          if (sound) {
            sound.muted = false;
            sound.currentTime = 0;
            // Await the play promise to make sure it actually starts playing
            await sound.play();
            // If it succeeded, we know user allowed it
            sessionStorage.setItem(UNLOCK_KEY, '1');
            hideUnlock();
          }
        } catch (e) {
          console.warn("Auto-play engellendi:", e);
          if (sessionStorage.getItem(UNLOCK_KEY) !== '1') {
            showUnlock();
          }

          // WebAudio fallback
          if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
          if (audioCtx.state === 'suspended') {
            await audioCtx.resume().catch(() => { });
          }
          try {
            if (audioCtx.state !== 'suspended') {
              const o = audioCtx.createOscillator();
              const g = audioCtx.createGain();
              o.connect(g); g.connect(audioCtx.destination);
              g.gain.setValueAtTime(0.0001, audioCtx.currentTime);
              g.gain.exponentialRampToValueAtTime(0.5, audioCtx.currentTime + 0.01);
              o.frequency.value = 880;
              o.start();
              o.stop(audioCtx.currentTime + 0.2); // bip
            }
          } catch (we) { console.error("Web audio fallback failed", we); }
        } finally {
          // ALWAYS execute cb() to refresh the table, but only AFTER we tried playing sound
          if (cb) cb();
        }
      }







      async function softRefresh() {



        try {



          const currentTbody = document.getElementById('stationBody');



          if (!currentTbody) { location.reload(); return; }



          const url = new URL(window.location.href);



          url.searchParams.set('partial', '1');



          url.searchParams.set('_', Date.now());



          const res = await fetch(url.toString(), { headers: { 'X-Requested-With': 'fetch', 'Cache-Control': 'no-cache' } });



          if (!res.ok) throw new Error('partial fetch failed');



          const html = await res.text();



          const temp = document.createElement('template');



          temp.innerHTML = html.trim();



          const newBody = temp.content.querySelector('tbody');



          if (!newBody) throw new Error('tbody missing');



          currentTbody.replaceWith(newBody);



          newBody.id = 'stationBody';



        } catch (err) {



          console.warn('[station] soft refresh fail -> full reload', err);



          location.reload();



        }



      }







      // --- Sayfa yüklenince otomatik bip ---



      window.addEventListener('pageshow', () => {



        // Eğer ses kilidi yoksa overlay göster; varsa direkt bip



        if (sessionStorage.getItem(UNLOCK_KEY) === '1') {



          playBeepThen(null);



        } else {



          showUnlock();



        }



      });







      // --- Socket.IO bağlan ---



      let socket = null;



      try {



        socket = io();



        socket.on('connect', () => console.log('[station] connected'));



        socket.on('disconnect', () => console.log('[station] disconnected'));
      } catch (e) { console.warn('[station] socket init failed', e); }

      if (socket) {
        socket.on('yeni_siparis', data => {
          console.log('[station] yeni_siparis', data);
          playBeepThen(() => softRefresh());
        });
        socket.on('order:updated', p => {
          console.log('[station] order:updated', p);
          playBeepThen(() => softRefresh());
        });
        socket.on('items_cancelled', p => {
          console.log('[station] items_cancelled', p);
          softRefresh();
        });
      }

      document.addEventListener('submit', async (e) => {



        const f = e.target.closest('form.inline-update'); if (!f) return;



        e.preventDefault();



        const btn = f.querySelector('button'); if (btn) btn.disabled = true;



        try {



          const res = await fetch(f.action, { method: 'POST' });



          if (!res.ok) throw new Error('update failed');



          await softRefresh();



        } catch (err) { console.warn(err); location.reload(); }



      });



    