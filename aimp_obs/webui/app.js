/* ==========================================================================
   AIMP PRISM DECK — Interactive 60/120FPS Audio Visualizer, 3D Vinyl Tilt,
   Magnetic Controls, View Transitions Theme Ripple, 1:1 OBS Studio & QR
   ========================================================================== */

(() => {
  const $ = (id) => document.getElementById(id);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  const state = {
    view: "stage",
    theme: "dark",
    snap: null,
    overlay: {},
    themesMeta: {},
    fonts: [],
    server: { running: false, url: "http://127.0.0.1:8765/", port: 8765 },
    mobile: { enabled: false, url: "", pending: [], approved: [] },
    floating: false,
    coverTs: -1,
    coverDataUrl: "",
    palette: { primary: "#ff9f19", secondary: "#38bdf8", glow: "#a855f7" },
    anchorPos: 0,
    anchorWall: performance.now(),
    playing: false,
    seeking: false,
    pausedHidden: false,
    lastTitle: "",
    lastLyricKey: "",
    lastQrUrl: "",
  };

  const THEME_SWATCHES = {
    modern: "#ff9f19",
    glass: "#5cc8ff",
    minimal: "#94a3b8",
    neon: "#ff2da0",
    spotify: "#1ed760",
    light: "#2563eb",
    bar: "#f59e0b",
    center: "#a855f7",
  };

  const ACCENT_PRESETS = ["#ff9f19", "#1ed760", "#5cc8ff", "#ff2da0", "#2563eb", "#ffffff"];
  const POS_ITEMS = [
    ["top-left", "左上"], ["top-center", "上"], ["top-right", "右上"],
    ["left", "左"], ["center", "中"], ["right", "右"],
    ["bottom-left", "左下"], ["bottom-center", "下"], ["bottom-right", "右下"],
  ];
  const SWITCH_ITEMS = [
    ["hide_cover", "隐藏封面"], ["hide_title", "隐藏标题"],
    ["hide_state", "隐藏状态"], ["hide_progress", "隐藏进度"],
    ["hide_lyrics", "隐藏歌词"], ["hide_when_stopped", "停止隐藏"],
    ["demo", "演示模式"],
  ];

  // -------------------- Bridge helper --------------------
  function api() {
    return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
  }

  async function callApi(name, ...args) {
    const bridge = api();
    if (!bridge || typeof bridge[name] !== "function") return null;
    try {
      return await bridge[name](...args);
    } catch (err) {
      console.warn("API error:", name, err);
      return null;
    }
  }

  function formatTime(ms) {
    if (!ms || ms < 0) return "0:00";
    const total = Math.floor(ms / 1000);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    const pad = (n) => (n < 10 ? "0" + n : "" + n);
    return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
  }

  function toast(msg) {
    const stack = $("toastStack");
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = msg;
    stack.appendChild(el);
    setTimeout(() => {
      el.classList.add("out");
      setTimeout(() => el.remove(), 260);
    }, 2100);
  }

  // -------------------- Particle Click Burst FX --------------------
  const fxCanvas = $("fxCanvas");
  const fxCtx = fxCanvas.getContext("2d");
  const burstParticles = [];

  function resizeFxCanvas() {
    const dpr = window.devicePixelRatio || 1;
    fxCanvas.width = Math.floor(window.innerWidth * dpr);
    fxCanvas.height = Math.floor(window.innerHeight * dpr);
    fxCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  window.addEventListener("resize", resizeFxCanvas);
  resizeFxCanvas();

  function spawnBurst(x, y, count = 16) {
    const colors = [state.palette.primary, state.palette.secondary, "#ffffff"];
    for (let i = 0; i < count; i++) {
      const ang = (Math.PI * 2 * i) / count + (Math.random() - 0.5) * 0.4;
      const spd = 1.6 + Math.random() * 3.8;
      burstParticles.push({
        x, y,
        vx: Math.cos(ang) * spd,
        vy: Math.sin(ang) * spd,
        life: 1.0,
        size: 1.8 + Math.random() * 2.6,
        color: colors[i % colors.length],
      });
    }
  }

  // -------------------- 64-Band Radial Spectrum + Stardust Engine --------------------
  const specCanvas = $("spectrumCanvas");
  const specCtx = specCanvas.getContext("2d");
  const BANDS = 64;
  const barVals = new Float32Array(BANDS);
  const barPeaks = new Float32Array(BANDS);
  const stardust = Array.from({ length: 28 }, (_, i) => ({
    angle: (Math.PI * 2 * i) / 28 + Math.random(),
    dist: 108 + Math.random() * 54,
    speed: 0.14 + Math.random() * 0.36,
    spin: (Math.random() - 0.5) * 0.008,
    size: 1 + Math.random() * 2.1,
    alpha: 0.25 + Math.random() * 0.55,
  }));

  function setupSpectrumCanvas() {
    const dpr = window.devicePixelRatio || 1;
    specCanvas.width = Math.floor(344 * dpr);
    specCanvas.height = Math.floor(344 * dpr);
    specCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  setupSpectrumCanvas();

  function renderFrame(now) {
    requestAnimationFrame(renderFrame);
    if (state.pausedHidden || document.hidden) return;

    // 1. Update click burst FX
    if (burstParticles.length > 0) {
      fxCtx.clearRect(0, 0, window.innerWidth, window.innerHeight);
      for (let i = burstParticles.length - 1; i >= 0; i--) {
        const p = burstParticles[i];
        p.x += p.vx;
        p.y += p.vy;
        p.vx *= 0.94;
        p.vy *= 0.94;
        p.life -= 0.032;
        if (p.life <= 0) {
          burstParticles.splice(i, 1);
          continue;
        }
        fxCtx.globalAlpha = p.life;
        fxCtx.fillStyle = p.color;
        fxCtx.beginPath();
        fxCtx.arc(p.x, p.y, p.size * p.life, 0, Math.PI * 2);
        fxCtx.fill();
      }
      fxCtx.globalAlpha = 1;
    }

    // 2. Smooth 60/120FPS interpolated seek bar while playing
    if (state.playing && !state.seeking && state.snap && state.snap.duration_ms > 0) {
      const est = state.anchorPos + (now - state.anchorWall);
      const ratio = clamp(est / state.snap.duration_ms, 0, 1);
      updateSeekVisual(ratio, est);
      if (state.snap.lyrics_synced && state.snap.lyrics_words && state.snap.lyrics_words.length) {
        updateKaraokeHighlight(est);
      }
    }

    // 3. Radial Spectrum & Stardust (only draw when stage view is active)
    if (state.view !== "stage") return;
    const t = now * 0.001;
    const cx = 172, cy = 172;
    const baseR = 112;
    specCtx.clearRect(0, 0, 344, 344);

    const grad = specCtx.createLinearGradient(24, 24, 320, 320);
    grad.addColorStop(0, state.palette.primary);
    grad.addColorStop(0.55, state.palette.secondary);
    grad.addColorStop(1, state.palette.glow);

    // Subtle outer orbital ring
    specCtx.strokeStyle = state.theme === "light" ? "rgba(15,23,42,0.08)" : "rgba(255,255,255,0.08)";
    specCtx.lineWidth = 1;
    specCtx.beginPath();
    specCtx.arc(cx, cy, baseR - 2, 0, Math.PI * 2);
    specCtx.stroke();

    // Stardust drifting outward
    for (const s of stardust) {
      s.angle += s.spin * (state.playing ? 1.8 : 0.45);
      s.dist += s.speed * (state.playing ? 1.15 : 0.25);
      if (s.dist > 168) {
        s.dist = 104 + Math.random() * 14;
        s.angle = Math.random() * Math.PI * 2;
      }
      const fade = 1 - Math.abs((s.dist - 134) / 36);
      specCtx.globalAlpha = clamp(fade * s.alpha, 0, 0.85);
      specCtx.fillStyle = state.palette.primary;
      specCtx.beginPath();
      specCtx.arc(cx + Math.cos(s.angle) * s.dist, cy + Math.sin(s.angle) * s.dist, s.size, 0, Math.PI * 2);
      specCtx.fill();
    }
    specCtx.globalAlpha = 1;

    // 64 harmonic spectrum rays
    specCtx.strokeStyle = grad;
    specCtx.lineCap = "round";
    specCtx.lineWidth = 2.6;
    const beat = state.playing
      ? 0.58 + 0.42 * Math.pow(0.5 + 0.5 * Math.sin(t * 4.4), 2)
      : 0.12;

    for (let i = 0; i < BANDS; i++) {
      const ang = (i / BANDS) * Math.PI * 2 - Math.PI / 2;
      let target = 0.07 + 0.04 * Math.sin(t * 1.4 + i * 0.35);
      if (state.playing) {
        const w1 = Math.sin(t * 5.2 + i * 0.42);
        const w2 = Math.cos(t * 8.1 - i * 0.71);
        const w3 = Math.sin(t * 2.9 + i * 1.15);
        const env = 0.55 + 0.45 * Math.sin((i / BANDS) * Math.PI * 4 + t);
        target = clamp((0.26 + 0.32 * (w1 * 0.5 + 0.5) + 0.25 * (w2 * 0.5 + 0.5) + 0.18 * (w3 * 0.5 + 0.5)) * beat * env, 0.08, 1.0);
      }
      barVals[i] += (target - barVals[i]) * (target > barVals[i] ? 0.28 : 0.12);
      barPeaks[i] = Math.max(barVals[i], barPeaks[i] - 0.009);

      const len = 6 + barVals[i] * 42;
      const x1 = cx + Math.cos(ang) * baseR;
      const y1 = cy + Math.sin(ang) * baseR;
      const x2 = cx + Math.cos(ang) * (baseR + len);
      const y2 = cy + Math.sin(ang) * (baseR + len);

      specCtx.globalAlpha = state.playing ? 0.88 : 0.36;
      specCtx.beginPath();
      specCtx.moveTo(x1, y1);
      specCtx.lineTo(x2, y2);
      specCtx.stroke();

      if (state.playing && barPeaks[i] > 0.2) {
        const px = cx + Math.cos(ang) * (baseR + 10 + barPeaks[i] * 42);
        const py = cy + Math.sin(ang) * (baseR + 10 + barPeaks[i] * 42);
        specCtx.globalAlpha = 0.75;
        specCtx.fillStyle = "#ffffff";
        specCtx.beginPath();
        specCtx.arc(px, py, 1.35, 0, Math.PI * 2);
        specCtx.fill();
      }
    }
    specCtx.globalAlpha = 1;
  }
  requestAnimationFrame(renderFrame);

  // -------------------- Cursor Spotlight + 3D Vinyl Tilt + Magnetic Buttons --------------------
  document.addEventListener("pointermove", (e) => {
    document.documentElement.style.setProperty("--mx", e.clientX + "px");
    document.documentElement.style.setProperty("--my", e.clientY + "px");
  });

  const tiltEl = $("turntableTilt");
  tiltEl.addEventListener("pointermove", (e) => {
    const r = tiltEl.getBoundingClientRect();
    const nx = (e.clientX - r.left) / r.width - 0.5;
    const ny = (e.clientY - r.top) / r.height - 0.5;
    tiltEl.style.transform = `rotateY(${(nx * 20).toFixed(2)}deg) rotateX(${(-ny * 20).toFixed(2)}deg) scale(1.03)`;
    tiltEl.style.setProperty("--gx", ((nx + 0.5) * 100).toFixed(1) + "%");
    tiltEl.style.setProperty("--gy", ((ny + 0.5) * 100).toFixed(1) + "%");
  });
  tiltEl.addEventListener("pointerleave", () => {
    tiltEl.style.transform = "rotateY(0deg) rotateX(0deg) scale(1)";
  });

  document.querySelectorAll(".mag-btn").forEach((btn) => {
    btn.addEventListener("pointermove", (e) => {
      const r = btn.getBoundingClientRect();
      const dx = (e.clientX - (r.left + r.width / 2)) * 0.24;
      const dy = (e.clientY - (r.top + r.height / 2)) * 0.24;
      btn.style.transform = `translate3d(${dx.toFixed(1)}px, ${dy.toFixed(1)}px, 0) scale(1.06)`;
    });
    btn.addEventListener("pointerleave", () => {
      btn.style.transform = "";
    });
    btn.addEventListener("click", (e) => {
      spawnBurst(e.clientX, e.clientY, btn.id === "btnPlay" ? 22 : 12);
    });
  });

  // -------------------- GPU View Transitions Theme Toggle --------------------
  function applyThemeVisual(mode) {
    state.theme = mode === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", state.theme);
  }

  async function toggleTheme(evt) {
    const next = state.theme === "dark" ? "light" : "dark";
    const btn = $("btnTheme");
    const rect = btn.getBoundingClientRect();
    const ox = evt ? evt.clientX : rect.left + rect.width / 2;
    const oy = evt ? evt.clientY : rect.top + rect.height / 2;
    const maxR = Math.hypot(Math.max(ox, window.innerWidth - ox), Math.max(oy, window.innerHeight - oy));

    if (document.startViewTransition) {
      const vt = document.startViewTransition(() => {
        applyThemeVisual(next);
      });
      vt.ready.then(() => {
        document.documentElement.animate(
          { clipPath: [`circle(0px at ${ox}px ${oy}px)`, `circle(${maxR}px at ${ox}px ${oy}px)`] },
          { duration: 520, easing: "cubic-bezier(0.22, 1, 0.36, 1)", pseudoElement: "::view-transition-new(root)" }
        );
      });
    } else {
      applyThemeVisual(next);
    }
    await callApi("set_ui_theme", next);
    toast(next === "light" ? "已切换 · 极光白瓷" : "已切换 · 暗夜黑胶");
  }

  // -------------------- Floating Dynamic Island Dock --------------------
  const dockItems = Array.from(document.querySelectorAll(".dock-item"));
  const dockIndicator = $("dockIndicator");

  function moveDockIndicator(activeBtn) {
    if (!activeBtn) return;
    dockIndicator.style.width = activeBtn.offsetWidth + "px";
    dockIndicator.style.transform = `translateX(${activeBtn.offsetLeft - 5}px)`;
  }

  function switchView(target) {
    if (!target) return;
    state.view = target;
    dockItems.forEach((b) => {
      const on = b.dataset.target === target;
      b.classList.toggle("active", on);
      if (on) moveDockIndicator(b);
    });
    document.querySelectorAll(".view").forEach((v) => {
      v.classList.toggle("active", v.dataset.view === target);
    });
    $("miniPlayer").classList.toggle("visible", target !== "stage");
    if (target === "mobile") refreshMobileView();
    if (target === "studio") syncObsPreview();
  }

  dockItems.forEach((b) => b.addEventListener("click", () => switchView(b.dataset.target)));
  window.addEventListener("resize", () => {
    const cur = dockItems.find((b) => b.classList.contains("active"));
    moveDockIndicator(cur);
  });

  // -------------------- Seek Bar Interaction --------------------
  const seekTrack = $("seekTrack");
  const seekFill = $("seekFill");
  const seekThumb = $("seekThumb");
  const seekTip = $("seekHoverTip");

  function updateSeekVisual(ratio, msOverride) {
    const pct = (clamp(ratio, 0, 1) * 100).toFixed(2) + "%";
    seekFill.style.width = pct;
    seekThumb.style.left = pct;
    if (typeof msOverride === "number") {
      $("timeCur").textContent = formatTime(msOverride);
    }
    $("obsSimFill").style.width = pct;
  }

  function ratioFromEvent(e) {
    const r = seekTrack.getBoundingClientRect();
    return clamp((e.clientX - r.left) / Math.max(1, r.width), 0, 1);
  }

  seekTrack.addEventListener("pointermove", (e) => {
    const ratio = ratioFromEvent(e);
    const dur = (state.snap && state.snap.duration_ms) || 0;
    seekTip.style.left = (ratio * 100).toFixed(1) + "%";
    seekTip.textContent = formatTime(dur * ratio);
    if (state.seeking) {
      updateSeekVisual(ratio, dur * ratio);
    }
  });

  seekTrack.addEventListener("pointerdown", (e) => {
    state.seeking = true;
    seekTrack.classList.add("dragging");
    seekTrack.setPointerCapture(e.pointerId);
    const ratio = ratioFromEvent(e);
    const dur = (state.snap && state.snap.duration_ms) || 0;
    updateSeekVisual(ratio, dur * ratio);
  });

  seekTrack.addEventListener("pointerup", async (e) => {
    if (!state.seeking) return;
    state.seeking = false;
    seekTrack.classList.remove("dragging");
    const ratio = ratioFromEvent(e);
    const dur = (state.snap && state.snap.duration_ms) || 0;
    state.anchorPos = dur * ratio;
    state.anchorWall = performance.now();
    await callApi("seek", ratio);
  });

  // -------------------- Lyrics Renderer (with word-by-word karaoke support) --------------------
  function renderLyrics(snap) {
    const badge = $("lyricBadge");
    const prevEl = $("lyricPrev");
    const curEl = $("lyricCur");
    const nextEl = $("lyricNext");

    const cur = snap.lyrics_current || "";
    const nxt = snap.lyrics_next || "";
    const full = snap.lyrics_full || [];
    const words = snap.lyrics_words || [];

    if (snap.lyrics_synced) {
      badge.textContent = words.length ? "逐字同步" : "LRC 同步";
      badge.classList.add("synced");
      const curLines = cur.split("\n").filter(Boolean);
      const mainLine = curLines[0] || "";
      const transLine = curLines.slice(1).join(" · ");
      const nextMain = (nxt.split("\n").filter(Boolean)[0]) || "";
      const key = `${cur}||${nxt}||${words.length}`;
      if (key !== state.lastLyricKey) {
        const oldMain = curEl.dataset.mainText || "";
        if (oldMain && oldMain !== mainLine) {
          prevEl.textContent = oldMain;
        }
        state.lastLyricKey = key;
        curEl.dataset.mainText = mainLine;
        if (words.length) {
          const wordHtml = words
            .map((w, i) => {
              const wt = Array.isArray(w) ? w[0] : (w && typeof w.t === "number" ? w.t : 0);
              const ws = Array.isArray(w) ? w[1] : (w && w.s != null ? w.s : "");
              return `<span class="kw-word" data-idx="${i}" data-t="${wt}">${escapeHtml(ws)}</span>`;
            })
            .join("");
          curEl.innerHTML = transLine
            ? `<div class="lyric-main">${wordHtml}</div><div class="lyric-trans">${escapeHtml(transLine)}</div>`
            : `<div class="lyric-main">${wordHtml}</div>`;
        } else {
          curEl.innerHTML = transLine
            ? `<div class="lyric-main">${escapeHtml(mainLine || "（纯音乐 / 间奏中）")}</div><div class="lyric-trans">${escapeHtml(transLine)}</div>`
            : `<div class="lyric-main">${escapeHtml(mainLine || "（纯音乐 / 间奏中）")}</div>`;
        }
        curEl.classList.remove("pop");
        void curEl.offsetWidth;
        curEl.classList.add("pop");
        nextEl.textContent = nextMain || "···";
      }
      if (words.length) {
        updateKaraokeHighlight(snap.position_ms || 0);
      }
    } else if (full.length) {
      badge.textContent = "纯文本歌词";
      badge.classList.remove("synced");
      prevEl.textContent = full[full.length - 3] || "";
      curEl.textContent = full[full.length - 2] || full[0] || "";
      nextEl.textContent = full[full.length - 1] || "";
    } else {
      badge.textContent = "无歌词";
      badge.classList.remove("synced");
      prevEl.textContent = "";
      curEl.textContent = "暂无实时歌词";
      nextEl.textContent = "支持同名 .lrc 与音频内嵌歌词";
    }
  }

  function updateKaraokeHighlight(posMs) {
    const spans = $("lyricCur").querySelectorAll(".kw-word");
    if (!spans.length) return;
    const firstT = Number(spans[0].dataset.t || 0);
    if (posMs < firstT) {
      // Before first word timestamp (or mismatched demo offset): keep line crisp & lit.
      spans.forEach((sp) => {
        sp.classList.add("lit");
        sp.classList.remove("active");
      });
      return;
    }
    let activeIdx = -1;
    spans.forEach((sp, i) => {
      const t = Number(sp.dataset.t || 0);
      if (posMs >= t) activeIdx = i;
    });
    spans.forEach((sp, i) => {
      sp.classList.toggle("lit", i < activeIdx);
      sp.classList.toggle("active", i === activeIdx);
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  // -------------------- Apply Live Palette & State Snapshot --------------------
  function applyPalette(pal) {
    if (!pal) return;
    state.palette = pal;
    const root = document.documentElement.style;
    root.setProperty("--c-primary", pal.primary || "#ff9f19");
    root.setProperty("--c-secondary", pal.secondary || "#38bdf8");
    root.setProperty("--c-glow", pal.glow || "#a855f7");
  }

  function applyCover(dataUrl) {
    if (!dataUrl) return;
    state.coverDataUrl = dataUrl;
    $("coverImg").src = dataUrl;
    $("vinylCenterArt").src = dataUrl;
    $("miniCover").src = dataUrl;
    $("obsSimCoverImg").src = dataUrl;
    const sleeve = document.querySelector(".sleeve-frame");
    sleeve.classList.remove("cover-pop");
    void sleeve.offsetWidth;
    sleeve.classList.add("cover-pop");
  }

  const SVG_PLAY = '<path d="M8 5.2v13.6L19 12 8 5.2z"/>';
  const SVG_PAUSE = '<rect x="6.5" y="5" width="4" height="14" rx="1.4"/><rect x="13.5" y="5" width="4" height="14" rx="1.4"/>';

  function applySnapshot(payload) {
    if (!payload) return;
    const snap = payload.snapshot;
    if (snap) {
      state.snap = snap;
      const isPlaying = snap.state === "playing";
      state.playing = isPlaying;
      state.anchorPos = snap.position_ms || 0;
      state.anchorWall = performance.now();
      document.body.classList.toggle("is-playing", isPlaying);

      // Status pill
      const pill = $("statusPill");
      pill.className = "status-pill " + (
        !snap.connected ? "offline" : isPlaying ? "playing" : snap.state === "paused" ? "paused" : "ready"
      );
      $("statusText").textContent = !snap.connected ? "未连接" : isPlaying ? "LIVE 播放中" : snap.state === "paused" ? "已暂停" : "已就绪";

      // Title / Artist with kinetic reveal on track change
      const title = snap.title || "等待音乐信号";
      const artistAlbum = [snap.artist, snap.album].filter(Boolean).join(" · ");
      const artist = (!snap.connected && !state.overlay.demo)
        ? "请启动 AIMP，或点击右上角「演示」体验全息动效"
        : (artistAlbum || "未知艺术家");
      const meta = [snap.genre, snap.year].filter(Boolean).join(" · ") || (state.overlay.demo ? "DEMO SHOWCASE" : "AIMP STUDIO");
      $("metaTag").textContent = meta;

      if (title !== state.lastTitle) {
        state.lastTitle = title;
        const tEl = $("trackTitle");
        const aEl = $("trackArtist");
        tEl.textContent = title;
        aEl.textContent = artist;
        tEl.classList.remove("reveal");
        aEl.classList.remove("reveal");
        void tEl.offsetWidth;
        tEl.classList.add("reveal");
        aEl.classList.add("reveal");
      } else {
        $("trackArtist").textContent = artist;
      }

      $("miniTitle").textContent = title;
      $("miniArtist").textContent = artist;
      $("playIcon").innerHTML = isPlaying ? SVG_PAUSE : SVG_PLAY;
      $("miniPlayIcon").innerHTML = isPlaying ? SVG_PAUSE : SVG_PLAY;

      if (!state.seeking) {
        updateSeekVisual(snap.progress || 0, snap.position_ms || 0);
      }
      $("timeDur").textContent = snap.duration || "0:00";

      renderLyrics(snap);
    }

    if (payload.cover_data_url) {
      state.coverTs = payload.cover_ts;
      applyCover(payload.cover_data_url);
    }
    if (payload.palette) {
      applyPalette(payload.palette);
    }
    if (typeof payload.floating === "boolean") {
      state.floating = payload.floating;
      $("chipFloat").classList.toggle("active", state.floating);
    }
    if (payload.server) {
      state.server = payload.server;
      syncServerUi();
    }
    if (payload.overlay) {
      state.overlay = payload.overlay;
      $("chipDemo").classList.toggle("active", !!state.overlay.demo);
    }
    if (typeof payload.pending_count === "number") {
      const b = $("dockMobileBadge");
      b.textContent = payload.pending_count;
      b.classList.toggle("show", payload.pending_count > 0);
    }
    if (state.view === "studio") {
      syncObsPreview();
    }
  }

  // -------------------- Studio Controls & 1:1 OBS Preview --------------------
  function buildStudioControls() {
    // 8 Theme buttons
    const tg = $("themeGrid");
    tg.innerHTML = "";
    Object.entries(state.themesMeta).forEach(([key, meta]) => {
      const btn = document.createElement("button");
      btn.className = "theme-chip";
      btn.dataset.themeKey = key;
      btn.innerHTML = `<span class="theme-dot" style="background:${THEME_SWATCHES[key] || '#ff9f19'}"></span><span>${meta.label}</span>`;
      btn.addEventListener("click", () => patchOverlay({ theme: key }, `已切换主题：${meta.label}`));
      tg.appendChild(btn);
    });

    // 9-grid position matrix
    const pm = $("posMatrix");
    pm.innerHTML = "";
    POS_ITEMS.forEach(([key, label]) => {
      const btn = document.createElement("button");
      btn.className = "pos-btn";
      btn.dataset.pos = key;
      btn.textContent = label;
      btn.addEventListener("click", () => patchOverlay({ pos: key }));
      pm.appendChild(btn);
    });

    // Cover side buttons
    document.querySelectorAll("#coverSideGroup .seg-btn").forEach((btn) => {
      btn.addEventListener("click", () => patchOverlay({ coverside: btn.dataset.side }));
    });

    // Accent swatches
    const sw = $("accentSwatches");
    sw.innerHTML = "";
    ACCENT_PRESETS.forEach((col) => {
      const b = document.createElement("button");
      b.className = "swatch-btn";
      b.style.background = col;
      b.dataset.color = col;
      b.addEventListener("click", () => patchOverlay({ accent: col, accent2: col }));
      sw.appendChild(b);
    });

    // Visibility switches
    const sg = $("switchGrid");
    sg.innerHTML = "";
    SWITCH_ITEMS.forEach(([key, label]) => {
      const lab = document.createElement("label");
      lab.className = "sw-item";
      lab.innerHTML = `<input type="checkbox" data-sw="${key}"/><span>${label}</span>`;
      lab.querySelector("input").addEventListener("change", (e) => {
        patchOverlay({ [key]: e.target.checked });
      });
      sg.appendChild(lab);
    });

    // Preview backdrop switcher
    document.querySelectorAll(".bg-opt").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".bg-opt").forEach((x) => x.classList.remove("active"));
        btn.classList.add("active");
        const stage = $("obsStage");
        stage.classList.remove("pbg-dark", "pbg-light", "pbg-grid");
        stage.classList.add("pbg-" + btn.dataset.pbg);
      });
    });
  }

  async function patchOverlay(patch, toastMsg) {
    Object.assign(state.overlay, patch);
    syncStudioControls();
    syncObsPreview();
    const res = await callApi("update_overlay", patch);
    if (res && res.overlay) {
      state.overlay = res.overlay;
      syncStudioControls();
      syncObsPreview();
    }
    if (toastMsg) toast(toastMsg);
  }

  function syncStudioControls() {
    const c = state.overlay || {};
    document.querySelectorAll(".theme-chip").forEach((b) => b.classList.toggle("active", b.dataset.themeKey === c.theme));
    document.querySelectorAll(".pos-btn").forEach((b) => b.classList.toggle("active", b.dataset.pos === c.pos));
    document.querySelectorAll("#coverSideGroup .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.side === c.coverside));
    document.querySelectorAll(".swatch-btn").forEach((b) => b.classList.toggle("active", b.dataset.color.toLowerCase() === (c.accent || "").toLowerCase()));
    $("chipDemo").classList.toggle("active", !!c.demo);

    $("lblBgHex").textContent = c.bg ? c.bg : "自定义";
    $("lblPanelHex").textContent = c.panel ? c.panel : "自定义";
    $("lblCurrentFont").textContent = c.lyric_font || "默认字体";

    $("inWidth").value = c.width || "";
    $("inFontsize").value = c.fontsize || "";
    $("inMargin").value = c.margin ?? 20;
    $("inRadius").value = c.radius || "";
    $("inCoverRadius").value = c.coverradius || "";

    document.querySelectorAll("#switchGrid input").forEach((inp) => {
      inp.checked = !!c[inp.dataset.sw];
    });
  }

  function syncObsPreview() {
    const c = state.overlay || {};
    const snap = state.snap || {};
    const stage = $("obsStage");
    const card = $("obsCard");

    // Position class
    stage.className = stage.className.replace(/\bpos-[a-z-]+\b/g, "").trim() + ` pos-${c.pos || "bottom-left"}`;

    // Theme & layout classes
    const theme = c.theme || "modern";
    card.className = `obs-sim-card theme-${theme}`;
    if (theme === "bar") card.classList.add("layout-bar");
    const effectiveSide = theme === "center" ? "top" : (c.coverside || "left");
    card.classList.add(`side-${effectiveSide}`);

    // Custom overrides
    card.style.setProperty("--obs-accent", c.accent || "");
    card.style.setProperty("--obs-panel", c.panel || "");
    card.style.setProperty("--obs-radius", c.radius ? `${Math.min(30, c.radius)}px` : "");
    card.style.setProperty("--obs-cover-radius", c.coverradius ? `${Math.min(28, c.coverradius)}px` : "");
    stage.style.backgroundColor = c.bg || "";

    // Text & Visibility
    $("obsSimCover").classList.toggle("is-hidden", !!c.hide_cover);
    $("obsSimState").classList.toggle("is-hidden", !!c.hide_state);
    $("obsSimTitle").classList.toggle("is-hidden", !!c.hide_title);
    $("obsSimProg").classList.toggle("is-hidden", !!c.hide_progress);
    $("obsSimLyric").classList.toggle("is-hidden", !!c.hide_lyrics);

    $("obsSimTitle").textContent = snap.title || "Midnight Prism";
    $("obsSimArtist").textContent = [snap.artist, snap.album].filter(Boolean).join(" · ") || "AIMP Studio";
    $("obsSimState").textContent = snap.state === "playing" ? "● 播放中" : snap.state === "paused" ? "● 已暂停" : "● 待机中";
    $("obsSimLyric").textContent = snap.lyrics_current || "此刻星光穿过玻璃棱镜…";
    $("obsSimLyric").style.fontFamily = c.lyric_font ? `"${c.lyric_font}", sans-serif` : "";
  }

  // -------------------- Font Picker Modal --------------------
  function openFontModal() {
    $("fontModal").classList.add("open");
    $("fontSearch").value = "";
    renderFontList("");
    setTimeout(() => $("fontSearch").focus(), 40);
  }
  function closeFontModal() {
    $("fontModal").classList.remove("open");
  }
  function renderFontList(keyword) {
    const kw = (keyword || "").trim().toLowerCase();
    const list = $("fontList");
    list.innerHTML = "";
    const cur = state.overlay.lyric_font || "";
    const filtered = state.fonts.filter((f) => f.toLowerCase().includes(kw)).slice(0, 140);
    filtered.forEach((name) => {
      const btn = document.createElement("button");
      btn.className = "font-opt" + (name === cur ? " active" : "");
      btn.innerHTML = `<span style="font-family:'${escapeHtml(name)}', sans-serif">${escapeHtml(name)}</span><span style="font-size:11px;opacity:0.6;font-family:'${escapeHtml(name)}', sans-serif">歌词 Aa</span>`;
      btn.addEventListener("mouseenter", () => {
        $("fontPreviewSample").style.fontFamily = `"${name}", sans-serif`;
      });
      btn.addEventListener("click", () => {
        patchOverlay({ lyric_font: name }, `歌词字体：${name}`);
        closeFontModal();
      });
      list.appendChild(btn);
    });
  }

  // -------------------- Server & Export UI --------------------
  function syncServerUi() {
    const s = state.server || {};
    const running = !!s.running;
    $("chipServer").classList.toggle("running", running);
    $("chipServerText").textContent = running ? `:${s.port}` : "已停";
    $("obsUrlCode").textContent = s.url || `http://127.0.0.1:${s.port || 8765}/`;
    $("btnToggleServer").textContent = running ? "停止服务" : "启动服务";
  }

  // -------------------- Mobile & Pure-JS Zero-Dep QR Code SVG --------------------
  async function refreshMobileView() {
    const data = await callApi("get_mobile_state");
    if (!data) return;
    state.mobile = data;
    $("chkMobileEnabled").checked = !!data.enabled;
    $("lblMobileToggle").textContent = data.enabled ? "已开启" : "已关闭";
    $("mobileUrlCode").textContent = data.url || "";
    $("mobileHint").textContent = data.enabled
      ? "手机连接已开启！用相机扫描左侧二维码打开，iOS Safari 可「添加到主屏幕」全屏遥控。"
      : "手机连接当前已关闭。开启后服务会自动监听局域网，首次连接的设备需在下方点击「同意」。";

    if (data.url && data.url !== state.lastQrUrl) {
      state.lastQrUrl = data.url;
      $("qrContainer").innerHTML = makeQrSvg(data.url);
    }

    const pending = data.pending || [];
    const approved = data.approved || [];
    $("pendingCountTag").textContent = pending.length;
    $("approvedCountTag").textContent = approved.length;
    const badge = $("dockMobileBadge");
    badge.textContent = pending.length;
    badge.classList.toggle("show", pending.length > 0);

    const pList = $("pendingList");
    pList.innerHTML = pending.length ? "" : '<div class="empty-tip">暂无待审核设备</div>';
    pending.forEach((d) => {
      const row = document.createElement("div");
      row.className = "device-row";
      row.innerHTML = `
        <div><div class="device-name">${escapeHtml(d.name || "移动设备")}</div><div class="device-id">${escapeHtml((d.id || "").slice(0, 10))}</div></div>
        <div class="device-acts">
          <button class="glass-btn primary">同意</button>
          <button class="glass-btn">拒绝</button>
        </div>`;
      const [btnOk, btnNo] = row.querySelectorAll("button");
      btnOk.addEventListener("click", async () => {
        await callApi("device_action", "approve", d.id);
        toast("已授权该移动设备");
        refreshMobileView();
      });
      btnNo.addEventListener("click", async () => {
        await callApi("device_action", "reject", d.id);
        toast("已拒绝设备请求");
        refreshMobileView();
      });
      pList.appendChild(row);
    });

    const aList = $("approvedList");
    aList.innerHTML = approved.length ? "" : '<div class="empty-tip">暂无已授权设备</div>';
    approved.forEach((d) => {
      const row = document.createElement("div");
      row.className = "device-row";
      row.innerHTML = `
        <div><div class="device-name">${escapeHtml(d.name || "移动设备")}</div><div class="device-id">${escapeHtml((d.id || "").slice(0, 10))}</div></div>
        <div class="device-acts"><button class="glass-btn danger">移除</button></div>`;
      row.querySelector("button").addEventListener("click", async () => {
        await callApi("device_action", "remove", d.id);
        toast("已移除设备授权");
        refreshMobileView();
      });
      aList.appendChild(row);
    });
  }

  // Minimal RFC-compliant QR Code Version 2/3/4 Byte-Mode Level-L SVG generator (handles URLs up to 78 bytes)
  function makeQrSvg(text) {
    const bytes = Array.from(new TextEncoder().encode(text));
    // Pick smallest version (2..5) Level L
    const VERS = [
      { v: 2, size: 25, dataCw: 34, ecCw: 10, align: [18] },
      { v: 3, size: 29, dataCw: 55, ecCw: 15, align: [22] },
      { v: 4, size: 33, dataCw: 80, ecCw: 20, align: [26] },
      { v: 5, size: 37, dataCw: 108, ecCw: 26, align: [30] },
    ];
    const spec = VERS.find((x) => bytes.length + 3 <= x.dataCw) || VERS[VERS.length - 1];
    const bits = [];
    const pushBits = (val, n) => { for (let i = n - 1; i >= 0; i--) bits.push((val >> i) & 1); };
    pushBits(0b0100, 4); // Byte mode
    pushBits(bytes.length, 8);
    bytes.forEach((b) => pushBits(b, 8));
    pushBits(0, Math.min(4, spec.dataCw * 8 - bits.length));
    while (bits.length % 8) bits.push(0);
    const cw = [];
    for (let i = 0; i < bits.length; i += 8) {
      let b = 0;
      for (let j = 0; j < 8; j++) b = (b << 1) | bits[i + j];
      cw.push(b);
    }
    for (let i = 0; cw.length < spec.dataCw; i++) cw.push(i % 2 === 0 ? 0xec : 0x11);

    // GF(256) Reed-Solomon
    const exp = new Uint8Array(512), log = new Uint8Array(256);
    for (let x = 1, i = 0; i < 255; i++) {
      exp[i] = x; log[x] = i;
      x = (x << 1) ^ (x & 0x80 ? 0x11d : 0);
    }
    for (let i = 255; i < 512; i++) exp[i] = exp[i - 255];
    const mul = (a, b) => (a && b ? exp[log[a] + log[b]] : 0);
    let gen = [1];
    for (let i = 0; i < spec.ecCw; i++) {
      const next = new Array(gen.length + 1).fill(0);
      for (let j = 0; j < gen.length; j++) {
        next[j] ^= gen[j];
        next[j + 1] ^= mul(gen[j], exp[i]);
      }
      gen = next;
    }
    const rem = new Array(spec.ecCw).fill(0);
    for (const b of cw) {
      const factor = b ^ rem.shift();
      rem.push(0);
      for (let j = 0; j < spec.ecCw; j++) rem[j] ^= mul(gen[j + 1], factor);
    }
    const allCw = cw.concat(rem);

    const N = spec.size;
    const grid = Array.from({ length: N }, () => new Int8Array(N).fill(-1));
    const func = Array.from({ length: N }, () => new Uint8Array(N));
    const setF = (r, c, v) => { if (r >= 0 && c >= 0 && r < N && c < N) { grid[r][c] = v; func[r][c] = 1; } };

    const finder = (r0, c0) => {
      for (let dr = -1; dr <= 7; dr++) for (let dc = -1; dc <= 7; dc++) {
        const inside = dr >= 0 && dr <= 6 && dc >= 0 && dc <= 6;
        const dark = inside && (dr === 0 || dr === 6 || dc === 0 || dc === 6 || (dr >= 2 && dr <= 4 && dc >= 2 && dc <= 4));
        setF(r0 + dr, c0 + dc, dark ? 1 : 0);
      }
    };
    finder(0, 0); finder(0, N - 7); finder(N - 7, 0);
    for (let i = 8; i < N - 8; i++) { setF(6, i, i % 2 === 0 ? 1 : 0); setF(i, 6, i % 2 === 0 ? 1 : 0); }
    for (const a of spec.align) {
      for (let dr = -2; dr <= 2; dr++) for (let dc = -2; dc <= 2; dc++) {
        setF(a + dr, a + dc, Math.max(Math.abs(dr), Math.abs(dc)) !== 1 ? 1 : 0);
      }
    }
    // Reserve format areas + dark module
    for (let i = 0; i <= 8; i++) {
      if (!func[8][i]) setF(8, i, 0);
      if (!func[i][8]) setF(i, 8, 0);
    }
    for (let i = 0; i < 8; i++) { setF(8, N - 1 - i, 0); setF(N - 1 - i, 8, 0); }
    setF(N - 8, 8, 1);

    // Place data bits with mask 0 ((r + c) % 2 === 0)
    let bitIdx = 0;
    for (let right = N - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      const up = ((right + 1) & 2) === 0;
      for (let step = 0; step < N; step++) {
        const r = up ? N - 1 - step : step;
        for (let k = 0; k < 2; k++) {
          const c = right - k;
          if (func[r][c]) continue;
          const b = bitIdx < allCw.length * 8 ? (allCw[bitIdx >> 3] >> (7 - (bitIdx & 7))) & 1 : 0;
          bitIdx++;
          grid[r][c] = b ^ (((r + c) & 1) === 0 ? 1 : 0);
        }
      }
    }
    // Format bits for Level L (01) + Mask 0 (000) => 0x77C4
    const fmt = 0x77c4;
    for (let i = 0; i <= 5; i++) setF(8, i, (fmt >> (14 - i)) & 1);
    setF(8, 7, (fmt >> 8) & 1); setF(8, 8, (fmt >> 7) & 1); setF(7, 8, (fmt >> 6) & 1);
    for (let i = 0; i < 6; i++) setF(5 - i, 8, (fmt >> (5 - i)) & 1);
    for (let i = 0; i < 8; i++) setF(8, N - 8 + i, (fmt >> (7 - i)) & 1);
    for (let i = 0; i < 7; i++) setF(N - 1 - i, 8, (fmt >> (14 - i)) & 1);

    let paths = "";
    for (let r = 0; r < N; r++) {
      for (let c = 0; c < N; c++) {
        if (grid[r][c] === 1) paths += `M${c},${r}h1v1h-1z`;
      }
    }
    return `<svg viewBox="-1 -1 ${N + 2} ${N + 2}" xmlns="http://www.w3.org/2000/svg"><rect x="-1" y="-1" width="${N + 2}" height="${N + 2}" fill="#fff"/><path d="${paths}" fill="#0f172a"/></svg>`;
  }

  // -------------------- Event Bindings --------------------
  function bindEvents() {
    $("btnTheme").addEventListener("click", (e) => toggleTheme(e));
    $("btnMin").addEventListener("click", () => callApi("window_minimize"));
    $("btnClose").addEventListener("click", () => callApi("window_close"));

    $("chipFloat").addEventListener("click", async () => {
      const res = await callApi("toggle_floating");
      if (res) {
        state.floating = !!res.floating;
        $("chipFloat").classList.toggle("active", state.floating);
        toast(state.floating ? "已开启桌面悬浮窗 (Ctrl+Shift+L 锁定)" : "已关闭桌面悬浮窗");
      }
    });

    $("chipDemo").addEventListener("click", async () => {
      const res = await callApi("toggle_demo");
      if (res) {
        state.overlay.demo = !!res.demo;
        syncStudioControls();
        toast(res.demo ? "已开启演示模式 ✨" : "已关闭演示模式");
        pollOnce();
      }
    });

    $("chipServer").addEventListener("click", () => switchView("broadcast"));

    $("btnPrev").addEventListener("click", () => callApi("player_cmd", "prev"));
    $("btnPlay").addEventListener("click", () => callApi("player_cmd", "playpause"));
    $("btnNext").addEventListener("click", () => callApi("player_cmd", "next"));
    $("btnStop").addEventListener("click", () => callApi("player_cmd", "stop"));
    $("miniPlayBtn").addEventListener("click", () => callApi("player_cmd", "playpause"));
    $("miniNextBtn").addEventListener("click", () => callApi("player_cmd", "next"));

    // Studio bindings
    $("btnStudioBrowser").addEventListener("click", () => callApi("open_url", "overlay"));
    $("btnStudioReset").addEventListener("click", async () => {
      const res = await callApi("reset_overlay");
      if (res && res.overlay) {
        state.overlay = res.overlay;
        syncStudioControls();
        syncObsPreview();
        toast("已恢复默认覆盖页样式");
      }
    });

    $("pickAccent").addEventListener("input", (e) => patchOverlay({ accent: e.target.value, accent2: e.target.value }));
    $("pickBg").addEventListener("input", (e) => patchOverlay({ bg: e.target.value }));
    $("pickPanel").addEventListener("input", (e) => patchOverlay({ panel: e.target.value }));
    $("btnClearBg").addEventListener("click", () => patchOverlay({ bg: "" }, "背景已设为透明"));
    $("btnClearPanel").addEventListener("click", () => patchOverlay({ panel: "" }, "面板已恢复主题默认"));

    [
      ["inWidth", "width", 0],
      ["inFontsize", "fontsize", 0],
      ["inMargin", "margin", 20],
      ["inRadius", "radius", 0],
      ["inCoverRadius", "coverradius", 0],
    ].forEach(([id, key, def]) => {
      $(id).addEventListener("change", (e) => {
        const val = parseInt(e.target.value, 10);
        patchOverlay({ [key]: Number.isFinite(val) ? Math.max(0, val) : def });
      });
    });

    $("btnOpenFontPicker").addEventListener("click", openFontModal);
    $("btnCloseFontModal").addEventListener("click", closeFontModal);
    $("fontModal").addEventListener("click", (e) => { if (e.target === $("fontModal")) closeFontModal(); });
    $("fontSearch").addEventListener("input", (e) => renderFontList(e.target.value));
    $("btnFontDefault").addEventListener("click", () => {
      patchOverlay({ lyric_font: "" }, "已恢复默认字体");
      closeFontModal();
    });

    // Broadcast bindings
    $("btnCopyObsUrl").addEventListener("click", async () => {
      await callApi("copy_text", $("obsUrlCode").textContent);
      toast("已复制 OBS 浏览器源地址");
    });
    $("btnOpenOverlay").addEventListener("click", () => callApi("open_url", "overlay"));
    $("btnOpenGallery").addEventListener("click", () => callApi("open_url", "preview"));
    $("btnSaveRuntime").addEventListener("click", async () => {
      const res = await callApi(
        "save_runtime",
        parseInt($("inPort").value, 10) || 8765,
        parseInt($("inRefresh").value, 10) || 300,
        $("inExportDir").value.trim()
      );
      if (res && res.ok) toast("运行参数已保存");
    });
    $("btnToggleServer").addEventListener("click", async () => {
      const port = parseInt($("inPort").value, 10) || 8765;
      const res = await callApi("toggle_server", port);
      if (res) {
        if (res.error) {
          toast(res.error);
        } else {
          state.server = res.server;
          $("inPort").value = state.server.port;
          syncServerUi();
          toast(state.server.running ? `服务已启动 :${state.server.port}` : "本地服务已停止");
        }
      }
    });
    $("btnChooseExport").addEventListener("click", async () => {
      const res = await callApi("choose_export_dir");
      if (res && res.path) {
        $("inExportDir").value = res.path;
        toast("已更新导出目录");
      }
    });
    $("btnOpenExport").addEventListener("click", () => callApi("open_export_dir"));

    // Mobile bindings
    $("chkMobileEnabled").addEventListener("change", async (e) => {
      const res = await callApi("toggle_mobile", e.target.checked);
      if (res) {
        toast(res.enabled ? "已开启局域网手机连接" : "已关闭局域网手机连接");
        refreshMobileView();
      }
    });
    $("btnCopyMobileUrl").addEventListener("click", async () => {
      await callApi("copy_text", $("mobileUrlCode").textContent);
      toast("已复制手机遥控地址");
    });

    // Global hotkeys
    document.addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      if (e.code === "Space") { e.preventDefault(); callApi("player_cmd", "playpause"); }
      else if (e.key === "1") switchView("stage");
      else if (e.key === "2") switchView("studio");
      else if (e.key === "3") switchView("broadcast");
      else if (e.key === "4") switchView("mobile");
      else if (e.key.toLowerCase() === "d") $("chipDemo").click();
      else if (e.key.toLowerCase() === "f") $("chipFloat").click();
      else if (e.key.toLowerCase() === "t") toggleTheme();
      else if (e.key === "Escape") closeFontModal();
    });
  }

  // -------------------- Polling & Lifecycle --------------------
  async function pollOnce() {
    if (state.pausedHidden) return;
    const data = await callApi("poll_state", state.coverTs);
    if (data) applySnapshot(data);
  }

  window.__PRISM_SET_PAUSED__ = (paused) => {
    state.pausedHidden = !!paused;
    if (!paused) pollOnce();
  };

  window.__PRISM_SWITCH_VIEW__ = (v) => switchView(v);

  async function bootstrap() {
    bindEvents();
    const data = await callApi("get_bootstrap");
    if (data) {
      applyThemeVisual(data.ui_theme || "dark");
      state.themesMeta = data.themes || {};
      state.fonts = data.fonts || [];
      state.overlay = data.overlay || {};
      state.server = data.server || state.server;
      $("inPort").value = state.server.port || 8765;
      $("inRefresh").value = data.refresh_ms || 300;
      $("inExportDir").value = data.export_dir || "";

      buildStudioControls();
      syncStudioControls();
      syncServerUi();
      applySnapshot(data);
      refreshMobileView();
    }
    requestAnimationFrame(() => moveDockIndicator(dockItems[0]));
    setInterval(pollOnce, 320);
    setInterval(() => {
      if (!state.pausedHidden && (state.view === "mobile" || state.mobile.enabled)) {
        refreshMobileView();
      }
    }, 2400);
  }

  if (window.pywebview && window.pywebview.api) {
    bootstrap();
  } else {
    window.addEventListener("pywebviewready", bootstrap);
  }
})();
