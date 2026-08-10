"""Mobile (iPhone) read-only now-playing page: portrait + landscape."""

from __future__ import annotations

MOBILE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="dark">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>AIMP Now Playing</title>
<style>
  :root { color-scheme: dark; --bg:#0f1218; --text:#f2f3f7; --dim:#9aa3b5; --accent:#ff9f19; --accent2:#ffd08a; }
  * { box-sizing:border-box; margin:0; padding:0; }
  html, body { height:100%; }
  body { background:var(--bg); color:var(--text); font-family:-apple-system, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif; overflow:hidden; }
  .wrap {
    height:100%;
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
  .bar i { display:block; height:100%; width:0; background:linear-gradient(90deg, var(--accent), var(--accent2)); }
  .times { display:flex; justify-content:space-between; margin-top:5px; font-size:12px; color:var(--dim); font-variant-numeric:tabular-nums; }
  .lyrics { flex:1 1 auto; min-height:0; margin-top:16px; overflow:hidden; display:flex; flex-direction:column; justify-content:flex-end; }
  .lyric-cur { font-size:18px; line-height:1.5; font-weight:600; word-break:break-word; white-space:pre-wrap; }
  .lyric-cur .lw { font-weight:400; }
  .lyric-cur .lw.active { font-weight:800; color:var(--accent); }
  .lyric-next { margin-top:8px; font-size:14px; color:var(--dim); line-height:1.45; word-break:break-word; white-space:pre-wrap; }
  .lyrics-none { color:var(--dim); font-size:14px; line-height:1.5; }
  @media (orientation: landscape) {
    .wrap { flex-direction:row; align-items:center; gap:24px; }
    .cover-wrap { padding:0; flex:0 0 auto; }
    .cover { width:min(32vh, 230px); }
    .right { flex:1 1 auto; min-width:0; height:100%; display:flex; flex-direction:column; justify-content:center; }
    .meta { text-align:left; }
    .state { margin-top:8px; }
    .progress { margin-top:12px; }
    .lyrics { margin-top:12px; flex:0 1 auto; max-height:46%; justify-content:flex-start; }
  }
</style>
</head>
<body>
  <div class="wrap">
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
        <div class="lyric-cur" id="lyricCur"></div>
        <div class="lyric-next" id="lyricNext"></div>
        <div class="lyrics-none" id="lyricNone" style="display:none">暂无歌词</div>
      </div>
    </div>
  </div>
<script>
(() => {
  const $ = id => document.getElementById(id);
  const el = {
    cover: $('cover'), title: $('title'), sub: $('sub'), state: $('state'),
    bar: $('barFill'), tCur: $('tCur'), tDur: $('tDur'),
    cur: $('lyricCur'), next: $('lyricNext'), none: $('lyricNone'),
  };
  const fmt = ms => {
    ms = Math.max(0, Math.floor((ms || 0) / 1000));
    const h = Math.floor(ms / 3600), m = Math.floor(ms % 3600 / 60), s = ms % 60;
    return h ? h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0') : m + ':' + String(s).padStart(2, '0');
  };
  const esc = s => (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  let snap = null;
  let words = [];
  let activeIdx = -1;
  let curText = '';

  function renderWords() {
    if (words && words.length >= 2) {
      const joined = words.map(w => w.s).join('');
      const tail = curText.length > joined.length ? curText.slice(joined.length) : '';
      const html = words.map((w, i) => '<span class="lw" data-i="' + i + '">' + esc(w.s) + '</span>').join('') + esc(tail);
      if (el.cur.innerHTML !== html) { el.cur.innerHTML = html; activeIdx = -1; }
      el.cur.style.fontSize = '';
    } else {
      if (el.cur.textContent !== curText) { el.cur.textContent = curText; activeIdx = -1; }
      el.cur.style.fontSize = '';
    }
  }

  function render(s) {
    snap = s;
    el.title.textContent = s.title || (s.connected ? '未知曲目' : '未检测到 AIMP');
    const sub = [s.artist, s.album, s.genre].filter(Boolean).join(' · ');
    el.sub.textContent = sub || (s.connected ? '' : '');
    el.state.textContent = s.state_text || '';
    el.cover.src = '/cover.png?t=' + (s.cover_ts || 0);
    el.tDur.textContent = s.duration || fmt(s.duration_ms || 0);

    el.none.style.display = 'none';
    if (s.lyrics_synced) {
      curText = s.lyrics_current || '';
      words = Array.isArray(s.lyrics_words) ? s.lyrics_words : [];
      renderWords();
      el.next.textContent = s.lyrics_next || '';
      el.next.style.display = s.lyrics_next ? '' : 'none';
      if (!curText && !s.lyrics_next) el.none.style.display = '';
    } else if (Array.isArray(s.lyrics_full) && s.lyrics_full.length) {
      curText = s.lyrics_full.slice(-4).join('\\n');
      words = [];
      renderWords();
      el.next.style.display = 'none';
      el.cur.style.fontSize = '15px';
    } else {
      curText = '';
      words = [];
      renderWords();
      el.next.style.display = 'none';
      el.none.style.display = '';
    }
  }

  function tick() {
    if (snap) {
      let pos = snap.position_ms || 0;
      const dur = snap.duration_ms || 0;
      if (snap.state === 'playing') {
        pos += Date.now() - Math.round((snap.updated_at || Date.now() / 1000) * 1000);
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
      const res = await fetch('/api/state?ts=' + Date.now(), { cache: 'no-store' });
      if (res.ok) render(await res.json());
    } catch (e) {
      el.state.textContent = '服务未连接';
    }
    setTimeout(poll, 1200);
  }

  requestAnimationFrame(tick);
  poll();
})();
</script>
</body>
</html>
"""


def render_mobile() -> str:
    return MOBILE_HTML
