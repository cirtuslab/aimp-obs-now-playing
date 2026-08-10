"""Mobile (iPhone) read-only now-playing page: portrait + landscape.

First connection requires approval in the GUI (device auth). Once approved the
page receives a token and can read state and send playback controls. Includes
the same lyric rolling animation and smooth progress as the OBS browser source.
"""

from __future__ import annotations

MOBILE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="dark">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="AIMP Now Playing">
<link rel="manifest" href="/m/manifest.webmanifest">
<title>AIMP Now Playing</title>
<style>
  :root { color-scheme: dark; --bg:#0f1218; --text:#f2f3f7; --dim:#9aa3b5; --accent:#ff9f19; --accent2:#ffd08a; }
  * { box-sizing:border-box; margin:0; padding:0; }
  html, body { height:100%; height:100vh; height:100dvh; }
  body { background:var(--bg); color:var(--text); font-family:-apple-system, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif; overflow:hidden; }
  .wrap {
    height:100%; height:100vh; height:100dvh;
    padding: max(14px, env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) max(14px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left));
    display:flex; flex-direction:column;
  }
  .cover-wrap { display:flex; justify-content:center; padding:14px 0 10px; }
  .cover { width:min(56vw, 250px); aspect-ratio:1; border-radius:18px; object-fit:cover; background:#202633; box-shadow:0 12px 34px rgba(0,0,0,.45); }
  .meta { text-align:center; min-width:0; }
  .title { font-size:21px; font-weight:700; line-height:1.3; word-break:break-word; }
  .sub { margin-top:6px; font-size:14px; color:var(--dim); word-break:break-word; }
  .state { display:inline-block; margin-top:10px; font-size:12px; letter-spacing:.08em; color:var(--accent); border:1px solid var(--accent); padding:3px 12px; border-radius:999px; }
  .progress { margin-top:16px; }
  .bar { height:6px; border-radius:3px; background:#262d3b; overflow:hidden; }
  .bar i { display:block; height:100%; width:0; background:linear-gradient(90deg, var(--accent), var(--accent2)); transition:width 0.25s linear; }
  .times { display:flex; justify-content:space-between; margin-top:5px; font-size:12px; color:var(--dim); font-variant-numeric:tabular-nums; }
  .lyrics { flex:1 1 auto; min-height:0; margin-top:16px; overflow:hidden; display:flex; align-items:flex-end; }
  .lyrics-inner { position:relative; width:100%; min-height:44px; }
  .lyric-cur, .lyric-next {
    position:absolute; left:0; right:0; top:0;
    white-space:pre-wrap; word-break:break-word;
    will-change:transform, opacity;
  }
  .lyric-cur { font-size:18px; line-height:1.5; font-weight:600; }
  .lyric-cur .lw { font-weight:400; }
  .lyric-cur .lw.active { font-weight:800; color:var(--accent); }
  .lyric-next { font-size:14px; color:var(--dim); line-height:1.45; }
  .lyrics-none { color:var(--dim); font-size:14px; line-height:1.5; }
  @media (orientation: landscape) {
    .wrap { flex-direction:row; align-items:center; gap:24px; }
    .cover-wrap { padding:0; flex:0 0 auto; }
    .cover { width:min(32vh, 230px); }
    .right { flex:1 1 auto; min-width:0; height:100%; height:100dvh; display:flex; flex-direction:column; justify-content:center; }
    .meta { text-align:left; }
    .state { margin-top:8px; }
    .progress { margin-top:12px; }
    .lyrics { margin-top:12px; flex:0 1 auto; max-height:46%; align-items:flex-start; }
  }
  /* auth overlay */
  #authOverlay {
    position:fixed; inset:0; z-index:50; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:14px;
    background:rgba(10,13,20,.92); backdrop-filter:blur(6px); text-align:center; padding:24px;
  }
  #authOverlay .dot { width:46px; height:46px; border-radius:50%; border:3px solid var(--accent); border-top-color:transparent; animation:spin 1s linear infinite; }
  @keyframes spin { to { transform:rotate(360deg); } }
  #authStatus { font-size:15px; color:var(--text); line-height:1.5; white-space:pre-wrap; }
  #authRetry { display:none; font-size:14px; color:var(--accent); background:transparent; border:1px solid var(--accent); padding:8px 18px; border-radius:999px; }
  /* control */
  #ctrlBtn {
    position:fixed; right:max(14px, env(safe-area-inset-right)); bottom:max(14px, env(safe-area-inset-bottom));
    z-index:40; width:40px; height:40px; border-radius:50%; border:1px solid rgba(255,255,255,.18);
    background:rgba(30,36,50,.55); color:var(--dim); font-size:16px; opacity:.5;
  }
  #ctrlPanel {
    position:fixed; right:max(14px, env(safe-area-inset-right)); bottom:max(64px, calc(env(safe-area-inset-bottom) + 50px));
    z-index:39; display:none; gap:8px; background:rgba(20,25,36,.9); border:1px solid rgba(255,255,255,.12);
    border-radius:14px; padding:10px 12px;
  }
  #ctrlPanel.on { display:flex; }
  #ctrlPanel button { min-width:44px; height:44px; border-radius:10px; border:none; background:#2a3140; color:var(--text); font-size:17px; }
  #ctrlPanel button:active { background:#39415a; }
</style>
</head>
<body>
  <div id="authOverlay">
    <div class="dot"></div>
    <div id="authStatus">正在连接…</div>
    <button id="authRetry">重新申请</button>
  </div>

  <div class="wrap" id="mainWrap" style="display:none">
    <div class="cover-wrap"><img id="cover" class="cover" alt="cover"></div>
    <div class="right">
      <div class="meta">
        <div class="title" id="title">—</div>
        <div class="sub" id="sub">—</div>
        <span class="state" id="state">连接中…</span>
      </div>
      <div class="progress">
        <div class="bar"><i id="barFill"></i></div>
        <div class="times"><span id="tCur">0:00</span><span id="tDur">0:00</span></div>
      </div>
      <div class="lyrics" id="lyricsBox">
        <div class="lyrics-inner" id="lyricsInner">
          <div class="lyric-cur" id="lyricCur"></div>
          <div class="lyric-next" id="lyricNext"></div>
          <div class="lyrics-none" id="lyricNone" style="display:none">暂无歌词</div>
        </div>
      </div>
    </div>
  </div>

  <button id="ctrlBtn" title="播放控制">⏯</button>
  <div id="ctrlPanel">
    <button data-a="prev" title="上一首">⏮</button>
    <button data-a="playpause" title="播放/暂停">⏯</button>
    <button data-a="stop" title="停止">⏹</button>
    <button data-a="next" title="下一首">⏭</button>
  </div>

<script>
(() => {
  const $ = id => document.getElementById(id);
  const el = {
    overlay: $('authOverlay'), status: $('authStatus'), retry: $('authRetry'),
    wrap: $('mainWrap'), cover: $('cover'), title: $('title'), sub: $('sub'), state: $('state'),
    bar: $('barFill'), tCur: $('tCur'), tDur: $('tDur'),
    inner: $('lyricsInner'), cur: $('lyricCur'), next: $('lyricNext'), none: $('lyricNone'),
    ctrlBtn: $('ctrlBtn'), ctrlPanel: $('ctrlPanel'),
  };
  const LS_ID = 'aimp_device_id';
  const LS_TOKEN = 'aimp_token';
  const NL = String.fromCharCode(10);
  const LYR_GAP = 4;

  const fmt = ms => {
    ms = Math.max(0, Math.floor((ms || 0) / 1000));
    const h = Math.floor(ms / 3600), m = Math.floor(ms % 3600 / 60), s = ms % 60;
    return h ? h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0') : m + ':' + String(s).padStart(2, '0');
  };
  const esc = s => (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const genId = () => 'dev-' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);

  let deviceId = localStorage.getItem(LS_ID) || '';
  let token = localStorage.getItem(LS_TOKEN) || '';

  function apiGet(path, params) {
    const q = new URLSearchParams(params || {});
    if (token) q.set('token', token);
    return fetch(path + (q.toString() ? '?' + q.toString() : ''), { cache: 'no-store' })
      .then(r => r.json().catch(() => ({})));
  }
  function apiPost(path, body) {
    const q = new URLSearchParams();
    if (token) q.set('token', token);
    return fetch(path + (q.toString() ? '?' + q.toString() : ''), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    }).then(r => r.json().catch(() => ({})));
  }

  function setOverlay(text, retry) {
    el.status.textContent = text;
    el.retry.style.display = retry ? '' : 'none';
    el.overlay.style.display = 'flex';
  }

  // ---------- device approval ----------
  async function ensureApproved() {
    if (!deviceId) {
      deviceId = genId();
      localStorage.setItem(LS_ID, deviceId);
    }
    try {
      await fetch('/api/device/register', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: deviceId, name: 'iPhone' }),
      });
    } catch (e) {}
    for (;;) {
      const st = await apiGet('/api/device/status', { id: deviceId });
      if (st && st.approved && st.token) {
        token = st.token;
        localStorage.setItem(LS_TOKEN, token);
        el.overlay.style.display = 'none';
        el.wrap.style.display = 'flex';
        start();
        return;
      }
      if (st && st.rejected) {
        setOverlay('连接请求已被拒绝' + NL + '点击下方按钮重新申请', true);
        return;
      }
      if (st && st.ok === false && st.error) {
        setOverlay(st.error, false);
        return;
      }
      setOverlay('等待电脑端同意连接…', false);
      await new Promise(r => setTimeout(r, 2000));
    }
  }

  el.retry.addEventListener('click', () => {
    localStorage.removeItem(LS_ID);
    localStorage.removeItem(LS_TOKEN);
    location.reload();
  });

  // ---------- theme from overlay config ----------
  async function applyTheme() {
    try {
      const cfg = await apiGet('/api/config');
      const set = (k, v) => { if (v) document.documentElement.style.setProperty(k, v); };
      set('--accent', cfg.accent);
      set('--accent2', cfg.accent2);
      set('--text', cfg.text);
      set('--dim', cfg.dim);
      if (cfg.bg) document.body.style.background = cfg.bg;
    } catch (e) {}
  }

  // ---------- playback control ----------
  el.ctrlBtn.addEventListener('click', () => el.ctrlPanel.classList.toggle('on'));
  el.ctrlPanel.querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', () => {
      apiPost('/api/control', { action: btn.getAttribute('data-a') });
    });
  });

  // ---------- lyric rendering with rolling animation ----------
  let snap = null;
  let anchorMs = 0;   // position_ms at last snapshot
  let anchorAt = 0;   // device time when that snapshot arrived
  let words = [];
  let activeIdx = -1;
  let curText = '';
  let lyricTimer = null;
  let pendingTop = null;
  let pendingBot = '';
  let pendingTopWords = [];

  function setContent(node, text, wds) {
    if (wds && wds.length >= 2) {
      const joined = wds.map(w => w.s).join('');
      const tail = text.length > joined.length ? text.slice(joined.length) : '';
      const html = wds.map((w, i) => '<span class="lw" data-i="' + i + '">' + esc(w.s) + '</span>').join('') + esc(tail);
      if (node.innerHTML !== html) node.innerHTML = html;
    } else {
      if (node.textContent !== text) node.textContent = text;
    }
    activeIdx = -1;
  }

  function layoutLyrics() {
    const topH = el.cur.offsetHeight || 26;
    const botH = el.next.offsetHeight || 20;
    el.cur.style.top = '0px';
    el.cur.style.fontSize = '18px';
    el.cur.style.color = 'var(--text)';
    el.next.style.top = (topH + LYR_GAP) + 'px';
    el.next.style.fontSize = '14px';
    el.next.style.color = 'var(--dim)';
    el.inner.style.height = (topH + LYR_GAP + botH) + 'px';
  }

  function rollLyrics(newTop, newBot, newTopWords) {
    const oldTop = el.cur.textContent;
    if (!oldTop) {
      setContent(el.cur, newTop, newTopWords);
      words = newTopWords || [];
      el.next.textContent = newBot;
      pendingTop = null; pendingBot = ''; pendingTopWords = [];
      layoutLyrics();
      el.cur.style.transition = 'none';
      el.cur.style.opacity = '0';
      void el.cur.offsetHeight;
      el.cur.style.transition = 'opacity 0.25s ease';
      el.cur.style.opacity = '1';
      return;
    }
    if (lyricTimer) { clearTimeout(lyricTimer); lyricTimer = null; }
    pendingTop = newTop;
    pendingTopWords = newTopWords || [];
    pendingBot = newBot;
    const distance = (el.cur.offsetHeight || 26) + LYR_GAP;
    layoutLyrics();

    el.cur.style.transition = 'transform 0.28s ease-in, opacity 0.28s ease-in';
    el.next.style.transition = 'transform 0.28s ease-out, opacity 0.28s ease-out, color 0.28s ease-out, font-size 0.28s ease-out';
    el.cur.style.transform = 'translateY(-' + distance + 'px)';
    el.cur.style.opacity = '0';
    el.next.style.transform = 'translateY(-' + distance + 'px)';
    el.next.style.opacity = '1';
    el.next.style.color = 'var(--text)';
    el.next.style.fontSize = '18px';

    lyricTimer = setTimeout(() => {
      el.cur.style.transition = 'none';
      el.next.style.transition = 'none';

      setContent(el.cur, pendingTop, pendingTopWords);
      words = pendingTopWords;
      el.cur.style.top = '0px';
      el.cur.style.transform = 'translateY(0)';
      el.cur.style.opacity = '1';
      el.cur.style.color = 'var(--text)';
      el.cur.style.fontSize = '18px';

      el.next.textContent = pendingBot;
      const newTopH = el.cur.offsetHeight || 26;
      el.next.style.top = (newTopH + LYR_GAP) + 'px';
      el.next.style.transform = 'translateY(0)';
      el.next.style.opacity = '0';
      el.next.style.color = 'var(--dim)';
      el.next.style.fontSize = '14px';
      void el.next.offsetHeight;
      el.next.style.transition = 'transform 0.3s ease-out, opacity 0.3s ease-out';
      el.next.style.opacity = '1';

      layoutLyrics();
      lyricTimer = null;
      pendingTop = null;
      pendingBot = '';
      pendingTopWords = [];
    }, 290);
  }

  function render(s) {
    snap = s;
    anchorMs = s.position_ms || 0;
    anchorAt = Date.now();
    el.title.textContent = s.title || (s.connected ? '未知曲目' : '未检测到 AIMP');
    const sub = [s.artist, s.album, s.genre].filter(Boolean).join(' · ');
    el.sub.textContent = sub || (s.connected ? '' : '');
    el.state.textContent = s.state_text || '';
    el.cover.src = '/cover.png?t=' + (s.cover_ts || 0) + (token ? '&token=' + encodeURIComponent(token) : '');
    el.tDur.textContent = s.duration || fmt(s.duration_ms || 0);

    const cur = s.lyrics_current || '';
    const nxt = s.lyrics_next || '';
    const wds = Array.isArray(s.lyrics_words) ? s.lyrics_words : [];
    el.none.style.display = 'none';
    if (s.lyrics_synced) {
      el.next.style.display = nxt ? '' : 'none';
      if (cur && cur !== el.cur.textContent) {
        rollLyrics(cur, nxt, wds);
      } else {
        if (el.cur.textContent !== cur) setContent(el.cur, cur, wds);
        words = wds;
        if (el.next.textContent !== nxt) el.next.textContent = nxt;
        layoutLyrics();
      }
      if (!cur && !nxt) {
        el.inner.style.height = 'auto';
        el.none.style.display = '';
      }
    } else if (Array.isArray(s.lyrics_full) && s.lyrics_full.length) {
      curText = s.lyrics_full.slice(-4).join(NL);
      words = [];
      setContent(el.cur, curText, []);
      el.next.style.display = 'none';
      el.cur.style.fontSize = '15px';
      el.inner.style.height = 'auto';
    } else {
      curText = '';
      words = [];
      setContent(el.cur, '', []);
      el.next.style.display = 'none';
      el.inner.style.height = 'auto';
      el.none.style.display = '';
    }
  }

  function tick() {
    if (snap) {
      let pos = anchorMs;
      const dur = snap.duration_ms || 0;
      if (snap.state === 'playing') {
        pos += Date.now() - anchorAt;
        if (pos < 0) pos = 0;
        if (dur > 0 && pos > dur) pos = dur;
      }
      el.bar.style.width = (dur > 0 ? Math.max(0, Math.min(100, pos / dur * 100)) : 0) + '%';
      el.tCur.textContent = fmt(pos);
      if (words.length >= 2) {
        let idx = -1;
        for (let i = 0; i < words.length; i++) {
          if (words[i].t <= pos) idx = i;
          else break;
        }
        if (idx !== activeIdx) {
          activeIdx = idx;
          const spans = el.cur.querySelectorAll('.lw');
          for (let i = 0; i < spans.length; i++) {
            spans[i].classList.toggle('active', i <= idx);
          }
        }
      }
    }
    requestAnimationFrame(tick);
  }

  async function poll() {
    try {
      const res = await fetch('/api/state?ts=' + Date.now() + (token ? '&token=' + encodeURIComponent(token) : ''), { cache: 'no-store' });
      if (res.status === 403) {
        localStorage.removeItem(LS_TOKEN);
        location.reload();
        return;
      }
      if (res.ok) render(await res.json());
    } catch (e) {
      el.state.textContent = '服务未连接';
    }
    setTimeout(poll, 1200);
  }

  function start() {
    applyTheme();
    requestAnimationFrame(tick);
    poll();
  }

  ensureApproved();
})();
</script>
</body>
</html>
"""

MANIFEST = {
    "name": "AIMP Now Playing",
    "short_name": "AIMP",
    "start_url": "/m",
    "display": "standalone",
    "background_color": "#0f1218",
    "theme_color": "#0f1218",
    "icons": [
        {"src": "/m/icon.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
    ],
}


def render_manifest() -> str:
    import json
    return json.dumps(MANIFEST, ensure_ascii=False)


def mobile_icon_png() -> bytes:
    """512x512 PNG app icon (reuses the demo cover art)."""
    try:
        from .demo import demo_cover_bytes
        return demo_cover_bytes()
    except Exception:
        return b""


def render_mobile() -> str:
    return MOBILE_HTML
