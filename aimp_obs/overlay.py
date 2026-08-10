"""OBS Browser Source overlay: multiple themes, custom colors and layout."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict

THEMES = {
    "modern": {
        "label": "Modern 深色",
        "layout": "card",
        "width": 460,
        "desc": "默认深色卡片，橙色强调色，适合 16:9",
    },
    "glass": {
        "label": "Glass 毛玻璃",
        "layout": "card",
        "width": 460,
        "desc": "半透明毛玻璃 + 青紫渐变，适合浅色直播画面",
    },
    "minimal": {
        "label": "Minimal 极简",
        "layout": "card",
        "width": 440,
        "desc": "无面板透明文字，只有细进度条",
    },
    "neon": {
        "label": "Neon 霓虹",
        "layout": "card",
        "width": 480,
        "desc": "暗紫底 + 品红/青色霓虹光，适合音乐直播",
    },
    "spotify": {
        "label": "Spotify 风格",
        "layout": "card",
        "width": 440,
        "desc": "纯黑卡片 + 绿色强调，紧凑稳重",
    },
    "light": {
        "label": "Light 亮色",
        "layout": "card",
        "width": 460,
        "desc": "白色卡片 + 蓝色强调，适合深色直播画面",
    },
    "bar": {
        "label": "Bar 横条",
        "layout": "bar",
        "width": 720,
        "desc": "横向紧凑条，封面在左，适合 16:9 底部",
    },
    "center": {
        "label": "Center 竖屏",
        "layout": "center",
        "width": 420,
        "desc": "封面居中置顶，适合 9:16 竖屏",
    },
}


@dataclass
class OverlayConfig:
    """Live-adjustable overlay settings shared by the GUI and the browser source."""

    theme: str = "modern"
    pos: str = "bottom-left"
    coverside: str = "left"
    bg: str = ""
    panel: str = ""
    accent: str = ""
    accent2: str = ""
    text: str = ""
    dim: str = ""
    width: int = 0
    fontsize: int = 0
    margin: int = 20
    radius: int = 0
    coverradius: int = 0
    lyric_font: str = ""
    hide_cover: bool = False
    hide_title: bool = False
    hide_state: bool = False
    hide_progress: bool = False
    hide_lyrics: bool = False
    hide_when_stopped: bool = False
    demo: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def update_from_dict(self, data: Dict[str, Any]) -> None:
        for key, value in (data or {}).items():
            if hasattr(self, key):
                setattr(self, key, value)

THEME_CSS = """
body[data-theme="modern"] {
  --panel-bg: rgba(16, 19, 27, 0.84);
  --panel-border: rgba(255, 255, 255, 0.09);
  --panel-blur: 14px;
  --accent: #ff9f19;
  --accent2: #ffd08a;
  --text: #f2f3f7;
  --dim: rgba(242, 243, 247, 0.62);
  --radius: 18px;
  --cover-radius: 12px;
  --shadow: 0 8px 30px rgba(0, 0, 0, 0.35);
  --title-weight: 700;
  --title-transform: none;
}
body[data-theme="glass"] {
  --panel-bg: rgba(22, 30, 44, 0.40);
  --panel-border: rgba(255, 255, 255, 0.18);
  --panel-blur: 18px;
  --accent: #5cc8ff;
  --accent2: #b18cff;
  --text: #ffffff;
  --dim: rgba(255, 255, 255, 0.66);
  --radius: 22px;
  --cover-radius: 16px;
  --shadow: 0 10px 40px rgba(0, 0, 0, 0.30);
  --title-weight: 600;
  --title-transform: none;
}
body[data-theme="minimal"] {
  --panel-bg: transparent;
  --panel-border: transparent;
  --panel-blur: 0px;
  --accent: #ffffff;
  --accent2: rgba(255, 255, 255, 0.55);
  --text: #ffffff;
  --dim: rgba(255, 255, 255, 0.55);
  --radius: 0px;
  --cover-radius: 6px;
  --shadow: none;
  --title-weight: 600;
  --title-transform: none;
}
body[data-theme="neon"] {
  --panel-bg: rgba(10, 6, 22, 0.90);
  --panel-border: rgba(255, 45, 160, 0.42);
  --panel-blur: 10px;
  --accent: #ff2da0;
  --accent2: #00e5ff;
  --text: #f6f2ff;
  --dim: rgba(246, 242, 255, 0.55);
  --radius: 16px;
  --cover-radius: 10px;
  --shadow: 0 0 34px rgba(255, 45, 160, 0.28);
  --title-weight: 800;
  --title-transform: uppercase;
}
body[data-theme="spotify"] {
  --panel-bg: rgba(18, 18, 18, 0.92);
  --panel-border: rgba(255, 255, 255, 0.06);
  --panel-blur: 6px;
  --accent: #1ed760;
  --accent2: #1ed760;
  --text: #ffffff;
  --dim: rgba(255, 255, 255, 0.55);
  --radius: 10px;
  --cover-radius: 6px;
  --shadow: 0 6px 24px rgba(0, 0, 0, 0.45);
  --title-weight: 700;
  --title-transform: none;
}
body[data-theme="light"] {
  --panel-bg: rgba(250, 251, 255, 0.92);
  --panel-border: rgba(20, 30, 60, 0.08);
  --panel-blur: 10px;
  --accent: #2563eb;
  --accent2: #38bdf8;
  --text: #111827;
  --dim: rgba(17, 24, 39, 0.55);
  --radius: 18px;
  --cover-radius: 12px;
  --shadow: 0 8px 30px rgba(15, 23, 42, 0.16);
  --title-weight: 700;
  --title-transform: none;
}
body[data-theme="bar"] {
  --panel-bg: rgba(16, 19, 27, 0.86);
  --panel-border: rgba(255, 255, 255, 0.10);
  --panel-blur: 12px;
  --accent: #ff9f19;
  --accent2: #ffd08a;
  --text: #f2f3f7;
  --dim: rgba(242, 243, 247, 0.62);
  --radius: 14px;
  --cover-radius: 8px;
  --shadow: 0 6px 24px rgba(0, 0, 0, 0.35);
  --title-weight: 700;
  --title-transform: none;
}
body[data-theme="center"] {
  --panel-bg: rgba(22, 30, 44, 0.42);
  --panel-border: rgba(255, 255, 255, 0.16);
  --panel-blur: 16px;
  --accent: #5cc8ff;
  --accent2: #b18cff;
  --text: #ffffff;
  --dim: rgba(255, 255, 255, 0.64);
  --radius: 24px;
  --cover-radius: 18px;
  --shadow: 0 10px 40px rgba(0, 0, 0, 0.30);
  --title-weight: 700;
  --title-transform: none;
}
"""

OVERLAY_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>AIMP Now Playing</title>
<style>
  :root {
    --accent: #ff9f19;
    --accent2: #ffd08a;
    --panel-bg: rgba(16, 19, 27, 0.84);
    --panel-border: rgba(255, 255, 255, 0.09);
    --panel-blur: 14px;
    --text: #f2f3f7;
    --dim: rgba(242, 243, 247, 0.62);
    --radius: 18px;
    --cover-radius: 12px;
    --shadow: 0 8px 30px rgba(0, 0, 0, 0.35);
    --font-size: 15px;
    --lyric-font: "Segoe UI", "Microsoft YaHei";
    --max-width: 460px;
    --margin: 20px;
    --title-weight: 700;
    --title-transform: none;
  }
__THEME_CSS__
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { background: transparent; overflow: hidden; }
  body {
    display: flex;
    width: 100vw;
    height: 100vh;
    padding: var(--margin);
    font-family: "Segoe UI", "Microsoft YaHei", system-ui, -apple-system, sans-serif;
    font-size: var(--font-size);
    color: var(--text);
  }
  body[data-pos="bottom-left"]    { justify-content: flex-start; align-items: flex-end; }
  body[data-pos="bottom-center"]  { justify-content: center; align-items: flex-end; }
  body[data-pos="bottom-right"]   { justify-content: flex-end; align-items: flex-end; }
  body[data-pos="top-left"]       { justify-content: flex-start; align-items: flex-start; }
  body[data-pos="top-center"]     { justify-content: center; align-items: flex-start; }
  body[data-pos="top-right"]      { justify-content: flex-end; align-items: flex-start; }
  body[data-pos="center"]         { justify-content: center; align-items: center; }
  body[data-pos="left"]           { justify-content: flex-start; align-items: center; }
  body[data-pos="right"]          { justify-content: flex-end; align-items: center; }

  .panel {
    width: min(100%, var(--max-width));
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-radius: var(--radius);
    padding: 16px 18px 14px;
    backdrop-filter: blur(var(--panel-blur));
    box-shadow: var(--shadow);
    transition: opacity 0.35s ease;
  }
  .panel.hidden { opacity: 0; }

  /* ---------- card layout (default) ---------- */
  .layout-card .top { display: flex; gap: 14px; align-items: center; }
  .layout-card[data-cover="right"] .top { flex-direction: row-reverse; }
  .layout-card[data-cover="top"] .top { flex-direction: column; text-align: center; }
  .layout-card[data-cover="top"] .meta { text-align: center; }
  .layout-card .cover-wrap { width: 96px; height: 96px; flex: 0 0 auto; }

  /* ---------- bar layout (wide, 16:9) ---------- */
  .layout-bar { --max-width: 720px; }
  .layout-bar .top { display: flex; gap: 13px; align-items: center; }
  .layout-bar .cover-wrap { width: 62px; height: 62px; flex: 0 0 auto; }
  .layout-bar .title { font-size: 1.05em; }
  .layout-bar .sub { margin-top: 2px; font-size: 0.82em; }
  .layout-bar .state { margin-top: 5px; }
  .layout-bar .progress { margin-top: 9px; }
  .layout-bar .lyrics { display: none; }

  /* ---------- center layout (portrait, 9:16) ---------- */
  .layout-center { --max-width: 420px; }
  .layout-center .top {
    display: flex; flex-direction: column; align-items: center; gap: 12px;
  }
  .layout-center .cover-wrap { width: 150px; height: 150px; flex: 0 0 auto; }
  .layout-center .meta { text-align: center; }
  .layout-center .title { white-space: normal; }
  .layout-center .sub { white-space: normal; text-align: center; }
  .layout-center .state { display: inline-block; }
  .layout-center .progress { margin-top: 14px; }
  .layout-center .lyrics { margin-top: 14px; text-align: center; }

  .cover-wrap {
    border-radius: var(--cover-radius);
    overflow: hidden;
    background: rgba(255, 255, 255, 0.06);
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.30);
  }
  .cover-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .meta { min-width: 0; flex: 1 1 auto; }
  .title {
    font-size: 1.16em;
    font-weight: var(--title-weight);
    text-transform: var(--title-transform);
    line-height: 1.3;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sub {
    margin-top: 4px;
    font-size: 0.88em;
    color: var(--dim);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .state {
    display: inline-block;
    margin-top: 8px;
    font-size: 0.70em;
    letter-spacing: 0.05em;
    color: var(--accent);
    border: 1px solid var(--accent);
    padding: 2px 9px;
    border-radius: 999px;
    opacity: 0.9;
  }
  .progress { margin-top: 13px; }
  .bar {
    height: 5px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.13);
    overflow: hidden;
  }
  body[data-theme="light"] .bar { background: rgba(15, 23, 42, 0.10); }
  .bar > i {
    display: block;
    height: 100%;
    width: 0%;
    border-radius: 999px;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    transition: width 0.25s linear;
  }
  body[data-theme="neon"] .bar > i { box-shadow: 0 0 12px var(--accent); }
  .times {
    display: flex;
    justify-content: space-between;
    margin-top: 5px;
    font-size: 0.74em;
    color: var(--dim);
    font-variant-numeric: tabular-nums;
  }
  .lyrics { position: relative; min-height: 60px; margin-top: 12px; overflow: hidden; }
  .lyric-cur {
    position: absolute; left: 0; right: 0; top: 0;
    font-size: 1.0em;
    line-height: 1.45;
    color: var(--text);
    font-family: var(--lyric-font), sans-serif;
    white-space: pre-wrap;
    word-break: break-word;
    will-change: transform, opacity, color;
  }
  .lyric-next {
    position: absolute; left: 0; right: 0; top: 0;
    font-size: 0.82em;
    line-height: 1.4;
    color: var(--dim);
    font-family: var(--lyric-font), sans-serif;
    white-space: pre-wrap;
    word-break: break-word;
    will-change: transform, opacity, color;
  }
  .lyric-cur .lw, .lyric-next .lw {
    font-weight: 400;
    transition: color 0.25s ease, font-weight 0.25s ease;
  }
  .lyric-cur .lw.active, .lyric-next .lw.active { font-weight: 800; color: var(--accent); }
  .lyrics-none { color: var(--dim); font-size: 0.85em; font-family: var(--lyric-font), sans-serif; }
  .lyrics-unsynced { color: var(--dim); font-size: 0.84em; line-height: 1.5; font-family: var(--lyric-font), sans-serif; }

  body[data-hide-cover="1"] .cover-wrap { display: none; }
  body[data-hide-title="1"] .title { display: none; }
  body[data-hide-state="1"] .state { display: none; }
  body[data-hide-progress="1"] .progress { display: none; }
  body[data-hide-lyrics="1"] .lyrics { display: none; }
  body[data-show-lyrics="1"] .lyrics { display: block; }
</style>
</head>
<body data-pos="bottom-left" data-theme="modern" class="layout-card">
  <div class="panel" id="panel">
    <div class="top">
      <div class="cover-wrap" id="coverWrap">
        <img id="cover" alt="cover">
      </div>
      <div class="meta">
        <div class="title" id="title">—</div>
        <div class="sub" id="sub">—</div>
        <span class="state" id="state">等待 AIMP</span>
      </div>
    </div>
    <div class="progress">
      <div class="bar"><i id="barFill"></i></div>
      <div class="times">
        <span id="tCur">0:00</span>
        <span id="tDur">0:00</span>
      </div>
    </div>
    <div class="lyrics" id="lyricsBox">
      <div class="lyric-cur" id="lyricCur"></div>
      <div class="lyric-next" id="lyricNext"></div>
      <div class="lyrics-none" id="lyricNone" style="display:none">暂无歌词</div>
      <div class="lyrics-unsynced" id="lyricUnsynced" style="display:none"></div>
    </div>
  </div>
<script>
(() => {
  const urlParams = new URLSearchParams(location.search);
  const root = document.documentElement;
  const body = document.body;
  const layouts = { modern: 'card', glass: 'card', minimal: 'card', neon: 'card', spotify: 'card', light: 'card', bar: 'bar', center: 'center' };

  const $ = id => document.getElementById(id);
  const el = {
    panel: $('panel'), cover: $('cover'), title: $('title'), sub: $('sub'),
    state: $('state'), bar: $('barFill'), tCur: $('tCur'), tDur: $('tDur'),
    cur: $('lyricCur'), next: $('lyricNext'), none: $('lyricNone'),
    unsynced: $('lyricUnsynced'), lyricsBox: $('lyricsBox')
  };
  let params = new URLSearchParams();

  function buildParams(cfg) {
    params = new URLSearchParams();
    const set = (k, v) => {
      if (v !== undefined && v !== null && v !== '') params.set(k, String(v));
    };
    if (cfg) {
      set('theme', cfg.theme);
      set('pos', cfg.pos);
      set('coverside', cfg.coverside);
      set('bg', cfg.bg);
      set('panel', cfg.panel);
      set('accent', cfg.accent);
      set('accent2', cfg.accent2);
      set('text', cfg.text);
      set('dim', cfg.dim);
      if (cfg.width) set('width', cfg.width);
      if (cfg.fontsize) set('fontsize', cfg.fontsize);
      if (cfg.margin) set('margin', cfg.margin);
      if (cfg.radius) set('radius', cfg.radius);
      if (cfg.coverradius) set('coverradius', cfg.coverradius);
      set('lyricfont', cfg.lyric_font);
      if (cfg.hide_cover) set('cover', 'off');
      if (cfg.hide_title) set('title', 'off');
      if (cfg.hide_state) set('state', 'off');
      if (cfg.hide_progress) set('progress', 'off');
      if (cfg.hide_lyrics) set('lyrics', 'off');
      if (cfg.hide_when_stopped) set('hide', 'stopped');
      if (cfg.demo) set('demo', '1');
    }
    // explicit URL parameters always win over GUI config
    for (const [k, v] of urlParams) params.set(k, v);
  }

  function applyParams() {
    const theme = params.get('theme') || 'modern';
    const layout = layouts[theme] || 'card';
    body.dataset.theme = theme;
    body.className = 'layout-' + layout;
    body.dataset.pos = params.get('pos') || 'bottom-left';
    body.dataset.hideCover = params.get('cover') === 'off' || params.get('hidecover') === '1' ? '1' : '0';
    body.dataset.hideTitle = params.get('title') === 'off' ? '1' : '0';
    body.dataset.hideState = params.get('state') === 'off' ? '1' : '0';
    body.dataset.hideProgress = params.get('progress') === 'off' ? '1' : '0';
    body.dataset.hideLyrics = params.get('lyrics') === 'off' ? '1' : '0';
    body.dataset.showLyrics = params.get('lyrics') === 'on' ? '1' : '0';

    const set = (name, value) => { if (value) root.style.setProperty(name, value); };
    set('--accent', params.get('accent'));
    set('--accent2', params.get('accent2'));
    set('--panel-bg', params.get('panel'));
    set('--text', params.get('text'));
    set('--dim', params.get('dim'));
    set('--radius', params.get('radius') ? params.get('radius') + 'px' : null);
    set('--cover-radius', params.get('coverradius') ? params.get('coverradius') + 'px' : null);
    set('--font-size', params.get('fontsize') ? params.get('fontsize') + 'px' : null);
    set('--max-width', params.get('width') ? params.get('width') + 'px' : null);
    set('--margin', params.get('margin') ? params.get('margin') + 'px' : null);
    const lf = params.get('lyricfont');
    if (lf) root.style.setProperty('--lyric-font', '"' + lf + '"');
    if (params.get('bg')) body.style.background = params.get('bg');
    else body.style.background = '';

    const coverSide = params.get('coverside') || (layout === 'center' ? 'top' : 'left');
    body.dataset.cover = coverSide;
  }

  const fmt = ms => {
    ms = Math.max(0, Math.floor((ms || 0) / 1000));
    const h = Math.floor(ms / 3600), m = Math.floor(ms % 3600 / 60), s = ms % 60;
    return h ? h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0') : m + ':' + String(s).padStart(2, '0');
  };
  const esc = s => (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  let topEl = $('lyricCur');
  let botEl = $('lyricNext');
  let lyricTimer = null;
  let pendingTop = null;
  let pendingBot = '';
  let pendingTopWords = [];
  let currentWords = [];
  let activeWordIdx = -1;
  let lastSnap = null;
  let displayPos = 0;
  let lastFrameAt = 0;
  let lastTrackKey = '';
  const LYR_GAP = 4;

  function setContent(node, text, words) {
    if (words && words.length >= 2) {
      // Words cover the original line; keep any extra lines (e.g. translation) as plain tail.
      const joined = words.map(w => w.s).join('');
      const tail = text.length > joined.length ? text.slice(joined.length) : '';
      const html = words.map((w, i) => '<span class="lw" data-i="' + i + '">' + esc(w.s) + '</span>').join('') + esc(tail);
      if (node.innerHTML !== html) node.innerHTML = html;
    } else {
      if (node.textContent !== text) node.textContent = text;
    }
    activeWordIdx = -1;
  }

  function layoutLyrics() {
    const topH = topEl.offsetHeight || 22;
    const botH = botEl.offsetHeight || 18;
    topEl.style.top = '0px';
    topEl.style.fontSize = '1em';
    topEl.style.color = 'var(--text)';
    botEl.style.top = (topH + LYR_GAP) + 'px';
    botEl.style.fontSize = '0.82em';
    botEl.style.color = 'var(--dim)';
    el.lyricsBox.style.height = (topH + LYR_GAP + botH) + 'px';
  }

  // Rolling transition: the bottom line slides up into the top slot while the
  // old top line slides out, and the new next line fades in at the bottom.
  function rollLyrics(newTop, newBot, newTopWords) {
    const oldTop = topEl.textContent;
    if (!oldTop) {
      setContent(topEl, newTop, newTopWords);
      currentWords = newTopWords || [];
      botEl.textContent = newBot;
      pendingTop = null;
      pendingBot = '';
      pendingTopWords = [];
      layoutLyrics();
      topEl.style.transition = 'none';
      topEl.style.opacity = '0';
      void topEl.offsetHeight;
      topEl.style.transition = 'opacity 0.25s ease';
      topEl.style.opacity = '1';
      return;
    }
    if (lyricTimer) { clearTimeout(lyricTimer); lyricTimer = null; }
    pendingTop = newTop;
    pendingTopWords = newTopWords || [];
    pendingBot = newBot;
    const distance = (topEl.offsetHeight || 22) + LYR_GAP;
    layoutLyrics();

    topEl.style.transition = 'transform 0.28s ease-in, opacity 0.28s ease-in';
    botEl.style.transition = 'transform 0.28s ease-out, opacity 0.28s ease-out, color 0.28s ease-out, font-size 0.28s ease-out';
    topEl.style.transform = 'translateY(-' + distance + 'px)';
    topEl.style.opacity = '0';
    botEl.style.transform = 'translateY(-' + distance + 'px)';
    botEl.style.opacity = '1';
    botEl.style.color = 'var(--text)';
    botEl.style.fontSize = '1em';

    lyricTimer = setTimeout(() => {
      topEl.style.transition = 'none';
      botEl.style.transition = 'none';

      // old bottom becomes the new top line
      setContent(botEl, pendingTop, pendingTopWords);
      currentWords = pendingTopWords;
      botEl.style.top = '0px';
      botEl.style.transform = 'translateY(0)';
      botEl.style.opacity = '1';
      botEl.style.color = 'var(--text)';
      botEl.style.fontSize = '1em';

      // old top becomes the new bottom line and fades in
      topEl.textContent = pendingBot;
      const newTopH = botEl.offsetHeight || 22;
      topEl.style.top = (newTopH + LYR_GAP) + 'px';
      topEl.style.transform = 'translateY(14px)';
      topEl.style.opacity = '0';
      topEl.style.color = 'var(--dim)';
      topEl.style.fontSize = '0.82em';
      void topEl.offsetHeight;
      topEl.style.transition = 'transform 0.3s ease-out, opacity 0.3s ease-out';
      topEl.style.transform = 'translateY(0)';
      topEl.style.opacity = '1';

      [topEl, botEl] = [botEl, topEl];
      layoutLyrics();
      lyricTimer = null;
      pendingTop = null;
      pendingBot = '';
      pendingTopWords = [];
    }, 290);
  }

  function render(s) {
    lastSnap = s;
    el.panel.classList.toggle('hidden', params.get('hide') === 'stopped' && s.state !== 'playing');
    el.title.textContent = s.title || (s.connected ? '未知曲目' : '未检测到 AIMP');
    const subParts = [s.artist, s.album].filter(Boolean);
    el.sub.textContent = subParts.length ? subParts.join(' · ') : (s.connected ? '暂无专辑信息' : '请先启动 AIMP');
    el.state.textContent = s.state_text || '';
    el.state.style.display = s.connected ? '' : 'none';
    el.cover.src = '/cover.png?t=' + (s.cover_ts || 0);
    el.bar.style.width = Math.max(0, Math.min(100, (s.progress || 0) * 100)) + '%';
    el.tCur.textContent = s.position || '0:00';
    el.tDur.textContent = s.duration || '0:00';

    const cur = s.lyrics_current || '';
    const nxt = s.lyrics_next || '';
    const words = Array.isArray(s.lyrics_words) ? s.lyrics_words : [];
    el.unsynced.style.display = 'none';
    if (s.lyrics_synced) {
      topEl.style.display = cur ? '' : 'none';
      botEl.style.display = nxt ? '' : 'none';
      if (cur && cur !== topEl.textContent) {
        if (lyricTimer) {
          if (cur === pendingTop) {
            pendingBot = nxt;
          } else {
            clearTimeout(lyricTimer);
            lyricTimer = null;
            pendingTop = null;
            pendingBot = '';
            topEl.style.transition = 'none';
            botEl.style.transition = 'none';
            topEl.style.transform = 'translateY(0)';
            botEl.style.transform = 'translateY(0)';
            topEl.style.opacity = '1';
            botEl.style.opacity = '1';
            topEl.style.color = '';
            botEl.style.color = '';
            layoutLyrics();
            rollLyrics(cur, nxt, words);
          }
        } else {
          rollLyrics(cur, nxt, words);
        }
      } else {
        if (topEl.textContent !== cur) setContent(topEl, cur, words);
        currentWords = words;
        if (botEl.textContent !== nxt) botEl.textContent = nxt;
        layoutLyrics();
      }
      el.none.style.display = (!cur && !nxt) ? '' : 'none';
    } else {
      currentWords = [];
      if (Array.isArray(s.lyrics_full) && s.lyrics_full.length) {
        topEl.style.display = 'none';
        botEl.style.display = 'none';
        el.unsynced.style.display = '';
        el.lyricsBox.style.height = 'auto';
        const block = esc(s.lyrics_full.slice(-6).join('\n'));
        if (el.unsynced._last !== block) {
          el.unsynced._last = block;
          el.unsynced.style.transition = 'none';
          el.unsynced.style.opacity = '0';
          void el.unsynced.offsetHeight;
          el.unsynced.innerHTML = block;
          el.unsynced.style.transition = 'opacity 0.35s ease';
          el.unsynced.style.opacity = '1';
        }
        el.none.style.display = 'none';
      } else {
        topEl.style.display = 'none';
        botEl.style.display = 'none';
        el.unsynced._last = '';
        el.lyricsBox.style.height = 'auto';
        el.none.style.display = '';
      }
    }
  }

  // Word-level bolding for Enhanced LRC: highlight the word that is playing now.
  function wordHighlightLoop() {
    if (lastSnap) {
      // Monotonic position: advance in real time while playing, follow the
      // server when it is ahead, and only step back on a real seek (>0.8s).
      const now = Date.now();
      const serverPos = lastSnap.position_ms || 0;
      if (lastSnap.track_key !== lastTrackKey) {
        lastTrackKey = lastSnap.track_key || '';
        displayPos = serverPos;
        lastFrameAt = now;
      } else if (lastSnap.state === 'playing') {
        if (lastFrameAt > 0) displayPos += now - lastFrameAt;
        if (serverPos > displayPos) displayPos = serverPos;
        else if (displayPos - serverPos > 1500) displayPos = serverPos;
        const dur = lastSnap.duration_ms || 0;
        if (dur > 0 && displayPos > dur) displayPos = dur;
      } else {
        displayPos = serverPos;
      }
      lastFrameAt = now;

      if (currentWords.length >= 2) {
        const pos = displayPos;
        let idx = -1;
        for (let i = 0; i < currentWords.length; i++) {
          if (currentWords[i].t <= pos) idx = i;
          else break;
        }
        const spans = topEl.querySelectorAll('.lw');
        for (let i = 0; i < spans.length; i++) {
          spans[i].classList.toggle('active', i <= idx);
        }
      }
    }
    requestAnimationFrame(wordHighlightLoop);
  }
  requestAnimationFrame(wordHighlightLoop);

  // ---- demo mode: preview without AIMP ----
  function runDemo() {
    const demoLyrics = [
      { t: 0, text: '♪ 示例歌词第一行\n（示例翻译）', words: [{t:0,s:'♪ 示'},{t:900,s:'例'},{t:1700,s:'歌'},{t:2500,s:'词'},{t:3300,s:'第一'},{t:4500,s:'行'}] },
      { t: 12000, text: '♪ 示例歌词第二行', words: [{t:12000,s:'♪ 示例'},{t:13200,s:'歌词'},{t:14600,s:'第二行'}] },
      { t: 24000, text: '♪ 示例歌词第三行', words: [{t:24000,s:'♪ 示例'},{t:25200,s:'歌词'},{t:26600,s:'第三行'}] },
      { t: 36000, text: '♪ 示例歌词第四行', words: [{t:36000,s:'♪ 示例'},{t:37200,s:'歌词'},{t:38600,s:'第四行'}] },
      { t: 48000, text: '♪ 示例歌词第五行', words: [{t:48000,s:'♪ 示例'},{t:49200,s:'歌词'},{t:50600,s:'第五行'}] },
      { t: 60000, text: '♪ 示例歌词第六行', words: [{t:60000,s:'♪ 示例'},{t:61200,s:'歌词'},{t:62600,s:'第六行'}] }
    ];
    const dur = 180000;
    let t = 0;
    demoTimer = setInterval(() => {
      t = (t + 1000) % dur;
      let cur = '', nxt = '', curWords = [];
      for (let i = 0; i < demoLyrics.length; i++) {
        if (demoLyrics[i].t <= t) { cur = demoLyrics[i].text; curWords = demoLyrics[i].words; }
        if (demoLyrics[i].t > t) { nxt = demoLyrics[i].text; break; }
      }
      render({
        connected: true, state: 'playing', state_text: '播放中',
        title: '示例歌曲 Example Song', artist: '示例歌手', album: '示例专辑',
        position_ms: t, updated_at: Date.now() / 1000,
        position: fmt(t), duration: fmt(dur), progress: t / dur,
        lyrics_synced: true, lyrics_current: cur, lyrics_next: nxt, lyrics_words: curWords,
        cover_ts: 1
      });
    }, 1000);
  }

  let pollTimer = null;
  let demoTimer = null;

  async function poll() {
    try {
      const res = await fetch('/api/state?ts=' + Date.now(), { cache: 'no-store' });
      if (res.ok) render(await res.json());
    } catch (e) {
      el.state.textContent = '服务未连接';
    }
    if (demoTimer) return;
    pollTimer = setTimeout(poll, 250);
  }

  function startPoll() {
    if (demoTimer) { clearInterval(demoTimer); demoTimer = null; }
    if (!pollTimer) poll();
  }

  function startDemo() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    if (!demoTimer) runDemo();
  }

  function syncMode() {
    if (params.get('demo') === '1') startDemo();
    else startPoll();
  }

  async function pollConfig() {
    try {
      const res = await fetch('/api/config?ts=' + Date.now(), { cache: 'no-store' });
      if (res.ok) {
        buildParams(await res.json());
        applyParams();
        syncMode();
      }
    } catch (e) {}
    setTimeout(pollConfig, 1500);
  }

  buildParams(null);
  applyParams();
  syncMode();
  pollConfig();
})();
</script>
</body>
</html>
"""

GALLERY_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>AIMP Now Playing — 主题预览</title>
<style>
  body { margin: 0; background: #10131a; color: #eef1f8; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; padding: 24px; }
  h1 { font-size: 20px; margin: 0 0 6px; }
  p.hint { color: #8d95a8; font-size: 13px; margin: 0 0 20px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(430px, 1fr)); gap: 18px; }
  .card { background: #171b24; border: 1px solid #2b3140; border-radius: 14px; padding: 14px; }
  .card h3 { margin: 0 0 2px; font-size: 15px; }
  .card p { margin: 0 0 10px; color: #8d95a8; font-size: 12px; }
  iframe { width: 100%; height: 230px; border: 1px solid #262c3a; border-radius: 10px; background: transparent; }
  code { display: block; margin-top: 8px; font-size: 12px; color: #ffb44d; word-break: break-all; }
</style>
</head>
<body>
  <h1>AIMP Now Playing — 主题预览</h1>
  <p class="hint">每个卡片都是真实渲染的模拟数据（?demo=1）。把 code 里的参数追加到 OBS 浏览器源 URL 即可使用。</p>
  <div class="grid">
"""


def render_overlay() -> str:
    return OVERLAY_HTML.replace("__THEME_CSS__", THEME_CSS)


def render_gallery() -> str:
    cards = []
    for name, meta in THEMES.items():
        url = f"/?theme={name}&demo=1&pos=bottom-left&width={meta['width']}"
        cards.append(
            '<div class="card">'
            f"<h3>{meta['label']}</h3>"
            f"<p>{meta['desc']}</p>"
            f'<iframe src="{url}" loading="lazy"></iframe>'
            f"<code>theme={name}&amp;demo=1&amp;width={meta['width']}</code>"
            "</div>"
        )
    return GALLERY_HTML + "\n".join(cards) + "\n  </div>\n</body>\n</html>"
