"""Mobile (iPhone) now-playing page: portrait + landscape, multi-theme.

First connection requires approval in the GUI (device auth). Once approved the
page receives a token and can read state and send playback controls. Includes
lyric rolling animation, smooth progress, and a built-in theme picker.
"""

from __future__ import annotations

# Theme tokens consumed by CSS. Keep labels short — they appear in the picker.
MOBILE_THEMES = {
    "modern": {"label": "Modern", "desc": "深色卡片 · 橙色强调", "scheme": "dark"},
    "glass": {"label": "Glass", "desc": "毛玻璃 · 青紫渐变", "scheme": "dark"},
    "neon": {"label": "Neon", "desc": "霓虹发光 · 品红青色", "scheme": "dark"},
    "spotify": {"label": "Spotify", "desc": "纯黑 · 绿色强调", "scheme": "dark"},
    "light": {"label": "Light", "desc": "日间白底 · 蓝色强调", "scheme": "light"},
    "vinyl": {"label": "Vinyl", "desc": "黑胶暖调 · 圆形封面", "scheme": "dark"},
    "bloom": {"label": "Bloom", "desc": "封面全屏虚化沉浸", "scheme": "dark"},
}

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
  /* ---------- base tokens (theme overrides via body[data-theme]) ---------- */
  :root {
    --bg: #0f1218;
    --bg2: #0f1218;
    --text: #f2f3f7;
    --dim: #9aa3b5;
    --accent: #ff9f19;
    --accent2: #ffd08a;
    --bar-bg: #262d3b;
    --card: transparent;
    --border: transparent;
    --cover-radius: 18px;
    --cover-border: 0 solid transparent;
    --cover-shadow: 0 12px 34px rgba(0,0,0,.45);
    --title-weight: 700;
    --title-size: 21px;
    --lyric-cur: 18px;
    --lyric-next: 14px;
    --state-border: var(--accent);
    --ctrl-bg: rgba(30,36,50,.55);
    --ctrl-fg: var(--dim);
    --panel-bg: rgba(20,25,36,.92);
    --panel-border: rgba(255,255,255,.12);
    --btn-bg: #2a3140;
    --btn-active: #39415a;
    --backdrop-opacity: 0;
    --scrim: transparent;
    --groove: none;
  }
  * { box-sizing:border-box; margin:0; padding:0; }
  html, body { height:100%; height:100vh; height:100dvh; }
  body {
    background: linear-gradient(180deg, var(--bg), var(--bg2));
    color: var(--text);
    font-family: -apple-system, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif;
    overflow: hidden;
  }

  /* ---------- themes ---------- */
  body[data-theme="modern"] {
    --bg: #0f1218; --bg2: #0c0f15;
    --text: #f2f3f7; --dim: #9aa3b5;
    --accent: #ff9f19; --accent2: #ffd08a;
    --bar-bg: #262d3b;
    --cover-radius: 18px;
    --cover-shadow: 0 12px 34px rgba(0,0,0,.45);
  }
  body[data-theme="glass"] {
    --bg: #0b1220; --bg2: #1a1030;
    --text: #ffffff; --dim: rgba(255,255,255,.66);
    --accent: #5cc8ff; --accent2: #b18cff;
    --bar-bg: rgba(255,255,255,.14);
    --cover-radius: 22px;
    --cover-border: 1px solid rgba(255,255,255,.22);
    --cover-shadow: 0 14px 40px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.18);
    --ctrl-bg: rgba(255,255,255,.12);
    --panel-bg: rgba(18,24,40,.78);
    --panel-border: rgba(255,255,255,.16);
    --btn-bg: rgba(255,255,255,.12);
    --btn-active: rgba(255,255,255,.22);
    --title-weight: 600;
  }
  body[data-theme="neon"] {
    --bg: #0a0616; --bg2: #12081f;
    --text: #f6f2ff; --dim: rgba(246,242,255,.55);
    --accent: #ff2da0; --accent2: #00e5ff;
    --bar-bg: #3a2450;
    --cover-radius: 14px;
    --cover-border: 1px solid rgba(255,45,160,.55);
    --cover-shadow: 0 0 28px rgba(255,45,160,.35), 0 12px 30px rgba(0,0,0,.5);
    --ctrl-bg: rgba(40,16,55,.7);
    --panel-bg: rgba(12,6,24,.9);
    --panel-border: rgba(255,45,160,.35);
    --btn-bg: #2a1840;
    --btn-active: #3d2460;
    --title-weight: 800;
    --title-size: 22px;
  }
  body[data-theme="spotify"] {
    --bg: #000000; --bg2: #121212;
    --text: #ffffff; --dim: #b3b3b3;
    --accent: #1ed760; --accent2: #1ed760;
    --bar-bg: #535353;
    --cover-radius: 8px;
    --cover-shadow: 0 8px 24px rgba(0,0,0,.55);
    --title-weight: 700;
    --title-size: 20px;
    --lyric-cur: 17px;
    --ctrl-bg: rgba(40,40,40,.85);
    --panel-bg: #282828;
    --panel-border: #333;
    --btn-bg: #3e3e3e;
    --btn-active: #4a4a4a;
  }
  body[data-theme="light"] {
    --bg: #f4f6fb; --bg2: #e8ecf5;
    --text: #111827; --dim: #6b7280;
    --accent: #2563eb; --accent2: #38bdf8;
    --bar-bg: #e2e6ef;
    --cover-radius: 16px;
    --cover-shadow: 0 10px 28px rgba(15,23,42,.14);
    --ctrl-bg: rgba(255,255,255,.92);
    --ctrl-fg: #374151;
    --panel-bg: rgba(255,255,255,.96);
    --panel-border: rgba(15,23,42,.08);
    --btn-bg: #e8ecf4;
    --btn-active: #d9e0ec;
  }
  body[data-theme="vinyl"] {
    --bg: #1a1410; --bg2: #120e0b;
    --text: #f3ebe0; --dim: #b5a898;
    --accent: #e8a849; --accent2: #c45c26;
    --bar-bg: #2e2620;
    --cover-radius: 50%;
    --cover-border: 3px solid #2a2218;
    --cover-shadow: 0 0 0 5px #1a1410, 0 0 0 6px #3a3028, 0 16px 40px rgba(0,0,0,.55);
    --title-weight: 600;
    --title-size: 22px;
    --lyric-cur: 17px;
    --ctrl-bg: rgba(40,32,24,.8);
    --panel-bg: rgba(28,22,16,.94);
    --panel-border: rgba(232,168,73,.22);
    --btn-bg: #3a3028;
    --btn-active: #4a3c30;
    --groove: radial-gradient(circle at center, transparent 54%, rgba(0,0,0,.18) 55%, transparent 57%);
  }
  body[data-theme="bloom"] {
    --bg: #0a0c10; --bg2: #0a0c10;
    --text: #ffffff; --dim: rgba(255,255,255,.68);
    --accent: #ffffff; --accent2: rgba(255,255,255,.55);
    --bar-bg: rgba(255,255,255,.22);
    --cover-radius: 14px;
    --cover-shadow: 0 18px 50px rgba(0,0,0,.55);
    --backdrop-opacity: .55;
    --scrim: linear-gradient(180deg, rgba(0,0,0,.2) 0%, rgba(0,0,0,.55) 55%, rgba(0,0,0,.72) 100%);
    --title-weight: 700;
    --title-size: 23px;
    --lyric-cur: 19px;
    --ctrl-bg: rgba(0,0,0,.4);
    --panel-bg: rgba(0,0,0,.45);
    --panel-border: rgba(255,255,255,.12);
    --btn-bg: rgba(255,255,255,.14);
    --btn-active: rgba(255,255,255,.24);
  }

  /* ---------- layout ---------- */
  #bgBlur, #bgScrim {
    position: fixed; inset: 0; z-index: 0; pointer-events: none;
  }
  #bgBlur {
    background-size: cover; background-position: center;
    filter: blur(42px) saturate(1.35);
    transform: scale(1.18);
    opacity: 0;
    transition: opacity .55s ease, background-image .3s ease;
  }
  body[data-theme="bloom"] #bgBlur { opacity: var(--backdrop-opacity); }
  #bgScrim { background: var(--scrim); }

  .wrap {
    position: relative; z-index: 1;
    height:100%; height:100vh; height:100dvh;
    padding: max(14px, env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) max(14px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left));
    display:flex; flex-direction:column;
  }
  .cover-wrap { display:flex; justify-content:center; padding:14px 0 10px; position:relative; }
  .cover {
    width:min(56vw, 250px); aspect-ratio:1;
    border-radius: var(--cover-radius);
    border: var(--cover-border);
    object-fit:cover; background:#202633;
    box-shadow: var(--cover-shadow);
    position: relative; z-index: 1;
  }
  body[data-theme="vinyl"] .cover-wrap::before {
    content:""; position:absolute; width:min(56vw,250px); aspect-ratio:1;
    border-radius:50%; background: var(--groove); z-index:2; pointer-events:none;
  }
  body[data-theme="vinyl"] .cover-wrap::after {
    content:""; position:absolute; width:18px; height:18px; border-radius:50%;
    background:#c4b8a8; border:4px solid #1a1410; z-index:3; pointer-events:none;
    top:50%; left:50%; transform:translate(-50%,-50%);
    margin-top:0;
  }
  .meta { text-align:center; min-width:0; }
  .title {
    font-size: var(--title-size); font-weight: var(--title-weight);
    line-height:1.3; word-break:break-word;
  }
  body[data-theme="vinyl"] .title { font-family: Georgia, "Songti SC", "SimSun", serif; letter-spacing:.02em; }
  .sub { margin-top:6px; font-size:14px; color:var(--dim); word-break:break-word; }
  .state {
    display:inline-block; margin-top:10px; font-size:12px; letter-spacing:.08em;
    color:var(--accent); border:1px solid var(--state-border);
    padding:3px 12px; border-radius:999px;
  }
  body[data-theme="spotify"] .state { letter-spacing:0; font-weight:700; }
  body[data-theme="bloom"] .state {
    background: rgba(255,255,255,.12); border-color: transparent; color:#fff;
  }
  .progress { margin-top:16px; }
  .bar { height:6px; border-radius:3px; background:var(--bar-bg); overflow:hidden; }
  body[data-theme="spotify"] .bar { height:4px; border-radius:2px; }
  body[data-theme="vinyl"] .bar { height:5px; }
  .bar i {
    display:block; height:100%; width:0;
    background:linear-gradient(90deg, var(--accent), var(--accent2));
    transition:width 0.25s linear;
  }
  body[data-theme="spotify"] .bar i { background: var(--accent); }
  .times { display:flex; justify-content:space-between; margin-top:5px; font-size:12px; color:var(--dim); font-variant-numeric:tabular-nums; }
  .lyrics { flex:1 1 auto; min-height:0; margin-top:16px; overflow:hidden; display:flex; align-items:flex-end; }
  .lyrics-inner { position:relative; width:100%; min-height:44px; }
  .lyric-cur, .lyric-next {
    position:absolute; left:0; right:0; top:0;
    white-space:pre-wrap; word-break:break-word;
    will-change:transform, opacity;
  }
  .lyric-cur { font-size:var(--lyric-cur); line-height:1.5; font-weight:600; }
  .lyric-cur .lw { font-weight:400; transition:color 0.25s ease, font-weight 0.25s ease; }
  .lyric-cur .lw.active { font-weight:800; color:var(--accent); }
  body[data-theme="bloom"] .lyric-cur .lw.active { color:#fff; text-shadow:0 0 12px rgba(255,255,255,.35); }
  .lyric-next { font-size:var(--lyric-next); color:var(--dim); line-height:1.45; }
  .lyrics-none { color:var(--dim); font-size:14px; line-height:1.5; }

  @media (orientation: landscape) {
    .wrap { flex-direction:row; align-items:center; gap:24px; }
    .cover-wrap { padding:0; flex:0 0 auto; }
    .cover { width:min(32vh, 230px); }
    body[data-theme="vinyl"] .cover-wrap::before { width:min(32vh,230px); }
    .right { flex:1 1 auto; min-width:0; height:100%; height:100dvh; display:flex; flex-direction:column; justify-content:center; }
    .meta { text-align:left; }
    .state { margin-top:8px; }
    .progress { margin-top:12px; }
    .lyrics { margin-top:12px; flex:0 1 auto; max-height:46%; align-items:flex-start; }
  }

  /* ---------- auth ---------- */
  #authOverlay {
    position:fixed; inset:0; z-index:50; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:14px;
    background:rgba(10,13,20,.92); backdrop-filter:blur(6px); text-align:center; padding:24px;
  }
  body[data-theme="light"] #authOverlay { background:rgba(244,246,251,.94); }
  #authOverlay .dot {
    width:46px; height:46px; border-radius:50%;
    border:3px solid var(--accent); border-top-color:transparent;
    animation:spin 1s linear infinite;
  }
  @keyframes spin { to { transform:rotate(360deg); } }
  #authStatus { font-size:15px; color:var(--text); line-height:1.5; white-space:pre-wrap; }
  #authRetry {
    display:none; font-size:14px; color:var(--accent); background:transparent;
    border:1px solid var(--accent); padding:8px 18px; border-radius:999px;
  }

  /* ---------- floating controls ---------- */
  #ctrlBtn, #themeBtn {
    position:fixed; z-index:40; width:40px; height:40px; border-radius:50%;
    border:1px solid rgba(255,255,255,.18);
    background: var(--ctrl-bg); color: var(--ctrl-fg); font-size:16px; opacity:.72;
  }
  body[data-theme="light"] #ctrlBtn,
  body[data-theme="light"] #themeBtn { border-color: rgba(15,23,42,.1); }
  #ctrlBtn { right:max(14px, env(safe-area-inset-right)); bottom:max(14px, env(safe-area-inset-bottom)); }
  #themeBtn { left:max(14px, env(safe-area-inset-left)); bottom:max(14px, env(safe-area-inset-bottom)); }
  #ctrlPanel {
    position:fixed; right:max(14px, env(safe-area-inset-right)); bottom:max(64px, calc(env(safe-area-inset-bottom) + 50px));
    z-index:39; display:none; gap:8px;
    background: var(--panel-bg); border:1px solid var(--panel-border);
    backdrop-filter: blur(12px);
    border-radius:14px; padding:10px 12px;
  }
  #ctrlPanel.on { display:flex; }
  #ctrlPanel button {
    min-width:44px; height:44px; border-radius:10px; border:none;
    background: var(--btn-bg); color: var(--text); font-size:17px;
  }
  #ctrlPanel button:active { background: var(--btn-active); }

  /* ---------- theme sheet ---------- */
  #themeSheet {
    position:fixed; inset:0; z-index:45; display:none;
    background: rgba(0,0,0,.45); backdrop-filter: blur(4px);
    align-items:flex-end; justify-content:center;
  }
  #themeSheet.on { display:flex; }
  .theme-card {
    width:min(100%, 420px);
    background: var(--panel-bg); color: var(--text);
    border:1px solid var(--panel-border);
    border-radius:22px 22px 0 0;
    padding: 18px 16px calc(20px + env(safe-area-inset-bottom));
    backdrop-filter: blur(16px);
    box-shadow: 0 -10px 40px rgba(0,0,0,.35);
  }
  .theme-card h3 {
    font-size:13px; font-weight:600; letter-spacing:.08em;
    color:var(--dim); margin-bottom:12px; text-align:center;
  }
  .theme-list { display:flex; flex-direction:column; gap:8px; }
  .theme-item {
    display:flex; align-items:center; gap:12px;
    padding:10px 12px; border-radius:14px;
    background: transparent; border:1px solid transparent;
    color: var(--text); text-align:left; width:100%;
  }
  .theme-item.active {
    border-color: var(--accent);
    background: rgba(255,255,255,.06);
  }
  body[data-theme="light"] .theme-item.active { background: rgba(37,99,235,.08); }
  .theme-swatch {
    width:36px; height:36px; border-radius:50%; flex:0 0 auto;
    border:1px solid rgba(255,255,255,.15);
    box-shadow: inset 0 0 0 1px rgba(0,0,0,.15);
  }
  .theme-name { font-size:15px; font-weight:600; }
  .theme-desc { font-size:12px; color:var(--dim); margin-top:2px; }
  .theme-check { margin-left:auto; color:var(--accent); font-size:16px; opacity:0; }
  .theme-item.active .theme-check { opacity:1; }
</style>
</head>
<body data-theme="modern">
  <div id="bgBlur"></div>
  <div id="bgScrim"></div>

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

  <button id="themeBtn" title="主题">◐</button>
  <button id="ctrlBtn" title="播放控制">⏯</button>
  <div id="ctrlPanel">
    <button data-a="prev" title="上一首">⏮</button>
    <button data-a="playpause" title="播放/暂停">⏯</button>
    <button data-a="stop" title="停止">⏹</button>
    <button data-a="next" title="下一首">⏭</button>
  </div>

  <div id="themeSheet">
    <div class="theme-card">
      <h3>界面主题</h3>
      <div class="theme-list" id="themeList"></div>
    </div>
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
    themeBtn: $('themeBtn'), themeSheet: $('themeSheet'), themeList: $('themeList'),
    bgBlur: $('bgBlur'), metaScheme: document.querySelector('meta[name="color-scheme"]'),
  };
  const LS_ID = 'aimp_device_id';
  const LS_TOKEN = 'aimp_token';
  const LS_SECRET = 'aimp_device_secret';
  const LS_THEME = 'aimp_mobile_theme';
  const NL = String.fromCharCode(10);
  const LYR_GAP = 4;
  const THEMES = __THEMES_JSON__;

  const fmt = ms => {
    ms = Math.max(0, Math.floor((ms || 0) / 1000));
    const h = Math.floor(ms / 3600), m = Math.floor(ms % 3600 / 60), s = ms % 60;
    return h ? h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0') : m + ':' + String(s).padStart(2, '0');
  };
  const esc = s => (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const genId = () => 'dev-' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
  const genSecret = () => {
    try {
      const a = new Uint8Array(24);
      (crypto.getRandomValues || crypto.msGetRandomValues).call(crypto, a);
      return Array.from(a, b => ('0' + b.toString(16)).slice(-2)).join('');
    } catch (e) {
      return 'sec-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    }
  };

  let deviceId = localStorage.getItem(LS_ID) || '';
  let deviceSecret = localStorage.getItem(LS_SECRET) || '';
  let token = localStorage.getItem(LS_TOKEN) || '';
  let currentTheme = 'modern';

  // ---------- themes ----------
  const SWATCH = {
    modern: 'linear-gradient(135deg,#0f1218,#ff9f19)',
    glass: 'linear-gradient(135deg,#5cc8ff,#b18cff)',
    neon: 'linear-gradient(135deg,#ff2da0,#00e5ff)',
    spotify: 'linear-gradient(135deg,#000,#1ed760)',
    light: 'linear-gradient(135deg,#f4f6fb,#2563eb)',
    vinyl: 'linear-gradient(135deg,#1a1410,#e8a849)',
    bloom: 'linear-gradient(135deg,#1a1c22,#ffffff)',
  };

  function resolveThemeName() {
    const q = new URLSearchParams(location.search).get('theme');
    if (q && THEMES[q]) return q;
    const saved = localStorage.getItem(LS_THEME);
    if (saved && THEMES[saved]) return saved;
    return 'modern';
  }

  function applyThemeName(name, persist) {
    if (!THEMES[name]) name = 'modern';
    currentTheme = name;
    document.body.dataset.theme = name;
    const meta = THEMES[name] || {};
    if (el.metaScheme) el.metaScheme.setAttribute('content', meta.scheme === 'light' ? 'light' : 'dark');
    // iOS status bar: light themes want dark text on light translucent bar
    const sb = document.querySelector('meta[name="apple-mobile-web-app-status-bar-style"]');
    if (sb) sb.setAttribute('content', meta.scheme === 'light' ? 'default' : 'black-translucent');
    if (persist) localStorage.setItem(LS_THEME, name);
    document.querySelectorAll('.theme-item').forEach(n => {
      n.classList.toggle('active', n.dataset.theme === name);
    });
  }

  function buildThemeList() {
    el.themeList.innerHTML = '';
    Object.keys(THEMES).forEach(key => {
      const t = THEMES[key] || {};
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'theme-item';
      btn.dataset.theme = key;
      btn.innerHTML =
        '<span class="theme-swatch" style="background:' + (SWATCH[key] || '#444') + '"></span>' +
        '<span><span class="theme-name">' + esc(t.label || key) + '</span>' +
        '<span class="theme-desc">' + esc(t.desc || '') + '</span></span>' +
        '<span class="theme-check">✓</span>';
      btn.addEventListener('click', () => {
        applyThemeName(key, true);
        el.themeSheet.classList.remove('on');
      });
      el.themeList.appendChild(btn);
    });
  }

  el.themeBtn.addEventListener('click', () => el.themeSheet.classList.toggle('on'));
  el.themeSheet.addEventListener('click', e => {
    if (e.target === el.themeSheet) el.themeSheet.classList.remove('on');
  });

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

  // ---------- keep screen awake ----------
  let wakeLock = null;
  async function requestWakeLock() {
    try {
      if ('wakeLock' in navigator) {
        wakeLock = await navigator.wakeLock.request('screen');
        wakeLock.addEventListener('release', () => { wakeLock = null; });
      }
    } catch (e) {}
  }
  function releaseWakeLock() {
    if (wakeLock) {
      try { wakeLock.release(); } catch (e) {}
      wakeLock = null;
    }
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') requestWakeLock();
    else releaseWakeLock();
  });

  // ---------- device approval ----------
  async function ensureApproved() {
    if (!deviceId) {
      deviceId = genId();
      localStorage.setItem(LS_ID, deviceId);
    }
    if (!deviceSecret) {
      deviceSecret = genSecret();
      localStorage.setItem(LS_SECRET, deviceSecret);
    }
    try {
      await fetch('/api/device/register', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: deviceId, name: 'iPhone', secret: deviceSecret }),
      });
    } catch (e) {}
    for (;;) {
      const st = await apiGet('/api/device/status', { id: deviceId, secret: deviceSecret });
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
    localStorage.removeItem(LS_SECRET);
    location.reload();
  });

  // Optional accent tint from PC overlay config (does not replace the theme).
  async function applyAccentFromConfig() {
    try {
      const cfg = await apiGet('/api/config');
      const set = (k, v) => { if (v) document.documentElement.style.setProperty(k, v); };
      if (cfg.accent) set('--accent', cfg.accent);
      if (cfg.accent2) set('--accent2', cfg.accent2);
    } catch (e) {}
  }

  // ---------- playback control ----------
  el.ctrlBtn.addEventListener('click', () => el.ctrlPanel.classList.toggle('on'));
  el.ctrlPanel.querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', () => {
      apiPost('/api/control', { action: btn.getAttribute('data-a') });
    });
  });

  // ---------- lyrics ----------
  let snap = null;
  let displayPos = 0;
  let lastFrameAt = 0;
  let lastTrackKey = '';
  let words = [];
  let activeIdx = -1;
  let curText = '';
  let lyricTimer = null;
  let pendingTop = null;
  let pendingBot = '';
  let pendingTopWords = [];

  const cssPx = (name, fallback) => {
    const v = getComputedStyle(document.body).getPropertyValue(name).trim();
    return v || fallback;
  };

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
    const curSize = cssPx('--lyric-cur', '18px');
    const nextSize = cssPx('--lyric-next', '14px');
    el.cur.style.top = '0px';
    el.cur.style.fontSize = curSize;
    el.cur.style.color = 'var(--text)';
    el.next.style.top = (topH + LYR_GAP) + 'px';
    el.next.style.fontSize = nextSize;
    el.next.style.color = 'var(--dim)';
    el.inner.style.height = (topH + LYR_GAP + botH) + 'px';
  }

  function rollLyrics(newTop, newBot, newTopWords) {
    const curSize = cssPx('--lyric-cur', '18px');
    const nextSize = cssPx('--lyric-next', '14px');
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
    el.next.style.fontSize = curSize;

    lyricTimer = setTimeout(() => {
      el.cur.style.transition = 'none';
      el.next.style.transition = 'none';

      setContent(el.cur, pendingTop, pendingTopWords);
      words = pendingTopWords;
      el.cur.style.top = '0px';
      el.cur.style.transform = 'translateY(0)';
      el.cur.style.opacity = '1';
      el.cur.style.color = 'var(--text)';
      el.cur.style.fontSize = curSize;

      el.next.textContent = pendingBot;
      const newTopH = el.cur.offsetHeight || 26;
      el.next.style.top = (newTopH + LYR_GAP) + 'px';
      el.next.style.transform = 'translateY(0)';
      el.next.style.opacity = '0';
      el.next.style.color = 'var(--dim)';
      el.next.style.fontSize = nextSize;
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
    el.title.textContent = s.title || (s.connected ? '未知曲目' : '未检测到 AIMP');
    const sub = [s.artist, s.album, s.genre].filter(Boolean).join(' · ');
    el.sub.textContent = sub || '';
    el.state.textContent = s.state_text || '';
    const coverUrl = '/cover.png?t=' + (s.cover_ts || 0) + (token ? '&token=' + encodeURIComponent(token) : '');
    el.cover.src = coverUrl;
    if (currentTheme === 'bloom') {
      el.bgBlur.style.backgroundImage = 'url("' + coverUrl + '")';
    }
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
      const now = Date.now();
      const serverPos = snap.position_ms || 0;
      if (snap.track_key !== lastTrackKey) {
        lastTrackKey = snap.track_key || '';
        displayPos = serverPos;
        lastFrameAt = now;
      } else if (snap.state === 'playing') {
        if (lastFrameAt > 0) displayPos += now - lastFrameAt;
        if (serverPos > displayPos) displayPos = serverPos;
        else if (displayPos - serverPos > 1500) displayPos = serverPos;
        const dur = snap.duration_ms || 0;
        if (dur > 0 && displayPos > dur) displayPos = dur;
      } else {
        displayPos = serverPos;
      }
      lastFrameAt = now;
      const pos = displayPos;
      const dur = snap.duration_ms || 0;

      el.bar.style.width = (dur > 0 ? Math.max(0, Math.min(100, pos / dur * 100)) : 0) + '%';
      el.tCur.textContent = fmt(pos);
      if (words.length >= 2) {
        let idx = -1;
        for (let i = 0; i < words.length; i++) {
          if (words[i].t <= pos) idx = i;
          else break;
        }
        const spans = el.cur.querySelectorAll('.lw');
        for (let i = 0; i < spans.length; i++) {
          spans[i].classList.toggle('active', i <= idx);
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
    setTimeout(poll, 300);
  }

  function start() {
    applyThemeName(resolveThemeName(), false);
    applyAccentFromConfig();
    requestWakeLock();
    requestAnimationFrame(tick);
    poll();
  }

  // Paint theme immediately so first frame is correct (even before auth).
  buildThemeList();
  applyThemeName(resolveThemeName(), false);
  ensureApproved();
})();
</script>
</body>
</html>
"""


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
    import json
    themes_json = json.dumps(MOBILE_THEMES, ensure_ascii=False)
    return MOBILE_HTML.replace("__THEMES_JSON__", themes_json)


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
