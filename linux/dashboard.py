#!/usr/bin/env python3
"""Optional offline local dashboard for DARKMAP-Q.

Serves a live-canvas web page (localhost, no cloud).
Polls /api/status every 500 ms and draws obstacle points, the path, and the
rover directly onto an HTML5 canvas — no PNG reload, no page refresh.

Run:
    pip install Flask
    python3 dashboard.py --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import argparse
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(REPO_ROOT, "data", "logs")
STATUS_JSON = os.path.join(LOG_DIR, "status.json")
CAMERA_FRAME = os.path.join(LOG_DIR, "camera_frame.jpg")


def _read_status() -> dict:
    if os.path.exists(STATUS_JSON):
        try:
            with open(STATUS_JSON, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass
    return {}


PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>DARKMAP-Q</title>
  <style>
    /* Offline-first: no web-font CDN. Falls back to system + monospace stacks. */

    :root {
      --bg:       #080c10;
      --surface:  #0e1520;
      --surface2: #131d2e;
      --border:   #1e2d42;
      --border2:  #253446;
      --text:     #d4e4f7;
      --muted:    #566a82;
      --green:    #22d3a0;
      --blue:     #4ea8ff;
      --red:      #ff5470;
      --amber:    #f5a623;
      --teal:     #0ef0c4;
      --glow-g:   rgba(34,211,160,.18);
      --glow-b:   rgba(78,168,255,.18);
      --glow-r:   rgba(255,84,112,.22);
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
    }

    /* ── TOP NAV ─────────────────────────────────────────────── */
    nav {
      display: flex; align-items: center; gap: 14px;
      padding: 0 24px; height: 52px;
      background: rgba(14,21,32,.92);
      border-bottom: 1px solid var(--border);
      backdrop-filter: blur(12px);
      position: sticky; top: 0; z-index: 10;
    }
    .nav-logo {
      font-size: 15px; font-weight: 700; letter-spacing: 2px;
      color: var(--text);
    }
    .nav-logo span { color: var(--teal); }
    .nav-sep { flex: 1; }
    .nav-tag {
      display: flex; align-items: center; gap: 6px;
      padding: 4px 11px; border-radius: 999px;
      font-size: 11px; font-weight: 600; letter-spacing: .5px;
      border: 1px solid;
    }
    .tag-offline {
      background: rgba(34,211,160,.08);
      border-color: rgba(34,211,160,.25);
      color: var(--green);
    }
    .tag-mode {
      background: rgba(78,168,255,.08);
      border-color: rgba(78,168,255,.25);
      color: var(--blue);
    }
    .tag-detect {
      background: rgba(245,166,35,.08);
      border-color: rgba(245,166,35,.25);
      color: var(--amber);
      font-family: 'JetBrains Mono', monospace;
    }
    .tag-detect.off { color: var(--muted); border-color: var(--border2); background: transparent; }
    .pulse-dot {
      width: 7px; height: 7px; border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 6px var(--green);
      animation: pulse 2s ease-in-out infinite;
    }
    @keyframes pulse {
      0%,100% { opacity: 1; }
      50%      { opacity: .35; }
    }

    /* ── PAGE BODY ───────────────────────────────────────────── */
    .page {
      padding: 12px 24px 12px;
      height: calc(100vh - 52px);   /* fill below the nav bar */
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    /* ── RISK BANNER ─────────────────────────────────────────── */
    .risk-banner {
      display: inline-flex; align-items: center; gap: 12px;
      padding: 8px 14px; border-radius: 10px; margin-bottom: 10px;
      font-size: 13px; font-weight: 600; border: 1px solid;
      align-self: flex-start;
      transition: background .3s, border-color .3s, color .3s;
    }
    .risk-icon { font-size: 16px; }
    .risk-clear  { background:rgba(34,211,160,.06); border-color:rgba(34,211,160,.2); color:var(--green); }
    .risk-medium { background:rgba(245,166,35,.06); border-color:rgba(245,166,35,.25); color:var(--amber); }
    .risk-high   { background:rgba(255,84,112,.08); border-color:rgba(255,84,112,.3);  color:var(--red);
                   animation: flash .8s step-end infinite; }
    @keyframes flash { 0%,100%{opacity:1} 50%{opacity:.6} }

    /* ── TOP BAR (stat cards + recon detections) ─────────────── */
    .topbar {
      display: flex; align-items: stretch; gap: 10px;
      margin-bottom: 10px; flex-shrink: 0;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
      gap: 10px; flex: 1;
    }
    /* detections panel sits flush to the right inside the topbar */
    .det-panel {
      flex-shrink: 0; width: 400px;
      padding: 8px 14px;
      display: flex; align-items: center;
    }
    .det-strip-inner {
      display: flex; align-items: center; gap: 12px; width: 100%;
    }
    .det-strip-title { min-width: 80px; }
    .det-panel .people-counter {
      margin-bottom: 0; padding: 4px 10px; flex-shrink: 0;
    }
    .det-panel .people-num { font-size: 22px; }
    .det-panel .people-label { font-size: 10px; }
    .det-panel .det-counts { display: none; }
    .card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 9px 13px;
      transition: border-color .2s;
    }
    .card:hover { border-color: var(--border2); }
    .card-label {
      font-size: 10px; font-weight: 500; letter-spacing: .8px;
      text-transform: uppercase; color: var(--muted);
    }
    .card-val {
      font-size: 20px; font-weight: 700; margin-top: 5px;
      line-height: 1.2; color: var(--text);
      word-break: break-all; overflow-wrap: anywhere;
    }
    .card-val.sm { font-size: 14px; font-weight: 600; }
    .card-val.mono {
      font-family: 'JetBrains Mono', monospace;
      font-size: 13px;
    }
    .c-green  { color: var(--green); }
    .c-blue   { color: var(--blue); }
    .c-amber  { color: var(--amber); }
    .c-red    { color: var(--red); }
    .c-muted  { color: var(--muted); }

    /* ── MAIN LAYOUT ─────────────────────────────────────────── */
    .layout {
      display: grid;
      grid-template-columns: 1fr 400px;
      gap: 10px;
      flex: 1;
      min-height: 0;
      overflow: hidden;
    }
    .layout > .panel { overflow: hidden; }
    @media (max-width: 840px) { .layout { grid-template-columns: 1fr; } }

    /* ── PANELS ──────────────────────────────────────────────── */
    .panel {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 14px; padding: 16px 18px; overflow: hidden;
    }
    .panel-header {
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 14px;
    }
    .panel-title {
      font-size: 11px; font-weight: 600; letter-spacing: .8px;
      text-transform: uppercase; color: var(--muted);
    }
    .panel-sub {
      font-size: 11px; color: var(--muted);
      font-family: 'JetBrains Mono', monospace;
    }

    /* ── MAP CANVAS ──────────────────────────────────────────── */
    .layout > .panel {
      display: flex; flex-direction: column;
      height: 100%;
    }
    .map-wrap {
      position: relative; width: 100%;
      border-radius: 10px; overflow: hidden;
      background: #060d16;
      flex: 1;
      min-height: 0;
      min-height: 200px;  /* fallback so it's never invisible */
    }
    #mapCanvas {
      position: absolute; inset: 0;
      width: 100%; height: 100%;
      display: block;
    }
    .map-no-data {
      position: absolute; inset: 0;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      color: var(--muted); font-size: 13px; gap: 8px;
    }
    .map-no-data svg { opacity: .3; }

    /* ── RADAR CANVAS ────────────────────────────────────────── */
    .radar-wrap {
      width: 100%; aspect-ratio: 1;
      max-height: 200px;
      border-radius: 10px; overflow: hidden;
      background: #060d16;
    }
    #radarCanvas { width: 100%; height: 100%; display: block; }

    /* ── EVENT LOG ───────────────────────────────────────────── */
    .events {
      max-height: 120px; overflow-y: auto;
      scrollbar-width: thin;
      scrollbar-color: var(--border2) transparent;
    }
    .event {
      display: flex; gap: 8px; align-items: baseline;
      padding: 5px 0; border-bottom: 1px solid #0d1824;
      font-size: 11.5px;
      font-family: 'JetBrains Mono', monospace;
    }
    .event:last-child { border-bottom: none; }
    .ev-ts { color: var(--muted); flex-shrink: 0; font-size: 10px; }
    .ev-msg { color: var(--text); word-break: break-all; }
    .ev-warn .ev-msg { color: var(--amber); }
    .ev-crit .ev-msg { color: var(--red); }
    .no-events { color: var(--muted); font-size: 12px; padding: 6px 0; }

    /* ── DETECTIONS ──────────────────────────────────────────── */
    .det-counts {
      display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px;
    }
    .det-chip {
      display: flex; align-items: center; gap: 5px;
      padding: 3px 9px; border-radius: 999px;
      font-size: 11px; font-weight: 600;
      border: 1px solid var(--border2); background: var(--surface2);
    }
    .det-swatch { width: 8px; height: 8px; border-radius: 2px; transform: rotate(45deg); }
    .det-list { display: none; }  /* moved out of topbar; hidden */
    .det-row {
      display: flex; gap: 8px; align-items: baseline;
      padding: 5px 0; border-bottom: 1px solid #0d1824;
      font-size: 11.5px; font-family: 'JetBrains Mono', monospace;
    }
    .det-row:last-child { border-bottom: none; }
    .det-ts { color: var(--muted); flex-shrink: 0; font-size: 10px; }
    .det-label { font-weight: 600; }
    .det-meta { color: var(--muted); margin-left: auto; flex-shrink: 0; }
    .det-note { color: var(--amber); font-size: 10px; }
    .no-det { color: var(--muted); font-size: 12px; padding: 6px 0; }

    /* ── PEOPLE COUNTER ──────────────────────────────────────── */
    .people-counter {
      display: flex; align-items: center; gap: 10px;
      padding: 8px 12px; margin-bottom: 8px;
      background: var(--surface2); border-radius: 10px;
      border: 1px solid var(--border2);
    }
    .people-icon { color: #ff5470; flex-shrink: 0; }
    .people-num {
      font-size: 28px; font-weight: 700; line-height: 1;
      color: #ff5470; font-family: 'JetBrains Mono', monospace;
      min-width: 2ch; text-align: center;
    }
    .people-label { font-size: 11px; color: var(--muted); line-height: 1.4; }
    /* compact detections panel — shrinks to fit content */
    .det-panel { flex-shrink: 0; }

    /* ── RECON DETECTIONS STRIP ──────────────────────────────── */
    .det-panel {
      flex-shrink: 0;
      padding: 10px 14px;
    }
    .det-strip-inner {
      display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
    }
    .det-strip-title {
      display: flex; flex-direction: column; gap: 2px; min-width: 100px;
    }
    .det-strip .people-counter {
      margin-bottom: 0; padding: 6px 12px; flex-shrink: 0;
    }
    .det-strip .people-num { font-size: 24px; }
    .det-strip .det-counts { margin-bottom: 0; display: flex; gap: 6px; flex-wrap: wrap; }
    .det-list-inline {
      display: flex; flex-wrap: wrap; gap: 6px;
      max-height: none; overflow: visible;
    }
    .det-list-inline .no-det { font-size: 11px; color: var(--muted); }

    /* ── CAMERA FEED ─────────────────────────────────────────── */
    .cam-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; }
    .cam-wrap {
      position: relative; width: 100%;
      border-radius: 10px; overflow: hidden;
      background: #060d16;
      aspect-ratio: 16/9;   /* matches webcam native — no cropping, no bars */
      flex-shrink: 0;
    }
    #camImg {
      width: 100%; height: 100%;
      object-fit: contain; display: none; width: 100%; height: 100%;
    }
    .cam-placeholder {
      color: var(--muted); font-size: 12px;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      gap: 8px; width: 100%; height: 100%;
      position: absolute; inset: 0;
    }
    .cam-placeholder svg { opacity: .3; }

    /* ── RIGHT COLUMN ────────────────────────────────────────── */
    .right-col {
      display: flex; flex-direction: column; gap: 10px;
      height: 100%; overflow-y: auto;
      scrollbar-width: none;
    }
    .right-col::-webkit-scrollbar { display: none; }
    .right-col .panel { flex-shrink: 0; }

    /* ── FOOTER ──────────────────────────────────────────────── */
    footer {
      margin-top: 18px;
      font-size: 11px; color: var(--muted);
      display: flex; align-items: center; gap: 6px;
    }
    .ft-dot {
      width: 5px; height: 5px; border-radius: 50%;
      background: var(--green); opacity: .7;
    }
  </style>
</head>
<body>

<nav>
  <span class="nav-logo">DARK<span>MAP</span>-Q</span>
  <div class="nav-sep"></div>
  <span class="nav-tag tag-detect" id="hdrDetect">DETECT: --</span>
  <span class="nav-tag tag-offline"><span class="pulse-dot"></span>OFFLINE</span>
  <span class="nav-tag tag-mode" id="hdrMode">STOP</span>
</nav>

<div class="page">

  <div class="risk-banner risk-clear" id="riskBanner">
    <span class="risk-icon" id="riskIcon">✓</span>
    <span id="riskText">CLEAR &nbsp;·&nbsp; Front: --</span>
  </div>

  <div class="topbar">
    <div class="cards">
      <div class="card">
        <div class="card-label">Scene</div>
        <div class="card-val sm c-green" id="cScene">--</div>
      </div>
      <div class="card">
        <div class="card-label">Obstacles</div>
        <div class="card-val" id="cObstacles">--</div>
      </div>
      <div class="card">
        <div class="card-label">Path pts</div>
        <div class="card-val" id="cPath">--</div>
      </div>
      <div class="card">
        <div class="card-label">Pose (cm)</div>
        <div class="card-val mono sm" id="cPose">--</div>
      </div>
      <div class="card">
        <div class="card-label">Heading</div>
        <div class="card-val sm" id="cTheta">--</div>
      </div>
      <div class="card">
        <div class="card-label">Last scan</div>
        <div class="card-val sm mono" id="cDist">--</div>
      </div>
      <div class="card">
        <div class="card-label">Last move</div>
        <div class="card-val sm mono" id="cAction">--</div>
      </div>
    </div>

    <!-- Recon detections — compact counter, right side of topbar -->
    <div class="panel det-panel">
      <div class="det-strip-inner">
        <div class="det-strip-title">
          <span class="panel-title">Recon detections</span>
          <span class="panel-sub" id="detFps">--</span>
        </div>
        <div class="people-counter" id="peopleCounter">
          <div class="people-num" id="peopleCount">0</div>
          <div class="people-label">people detected</div>
        </div>
        <div class="det-counts" id="detCounts"></div>
      </div>
    </div>
  </div><!-- /.topbar -->
  <!-- hidden det-list kept for JS compatibility -->
  <div id="detList" style="display:none"></div>

  <div class="layout">

    <!-- Map panel -->
    <div class="panel">
      <div class="panel-header">
        <span class="panel-title">Live map</span>
        <span class="panel-sub" id="mapUpdated">--</span>
      </div>
      <div class="map-wrap" id="mapWrap">
        <canvas id="mapCanvas"></canvas>
        <div class="map-no-data" id="mapNoData">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>
          </svg>
          Waiting for data…
        </div>
      </div>
    </div>

    <!-- Right column -->
    <div class="right-col">

      <!-- Radar -->
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">Ultrasonic sweep</span>
        </div>
        <div class="radar-wrap">
          <canvas id="radarCanvas"></canvas>
        </div>
      </div>

      <!-- Event log -->
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">Event log</span>
        </div>
        <div class="events" id="eventLog">
          <div class="no-events">Waiting for events…</div>
        </div>
      </div>

      <!-- Camera feed -->
      <div class="panel cam-panel">
        <div class="panel-header">
          <span class="panel-title">Camera feed</span>
          <span class="panel-sub" id="camStatus">--</span>
        </div>
        <div class="cam-wrap">
          <img id="camImg" alt="camera feed"/>
          <div class="cam-placeholder" id="camPlaceholder">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
            </svg>
            No camera frame
          </div>
        </div>
      </div>

    </div>
  </div>

  <footer>
    <div class="ft-dot"></div>
    Live canvas &nbsp;·&nbsp; polls /api/status every 500 ms &nbsp;·&nbsp; DARKMAP-Q offline system
  </footer>

</div><!-- .page -->

<script>
// ─────────────────────────────────────────────────────────────────────────────
// Canvas sizing — resize backing store only when CSS size actually changes.
// Setting canvas.width clears the canvas, so we track last known pixel size.
// ─────────────────────────────────────────────────────────────────────────────
const _canvasState = new WeakMap();

function ensureCanvasSize(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = Math.round(rect.width  * dpr);
  const h = Math.round(rect.height * dpr);
  if (w < 4 || h < 4) return false;   // not laid out yet — skip draw
  const prev = _canvasState.get(canvas);
  if (!prev || prev.w !== w || prev.h !== h) {
    canvas.width  = w;
    canvas.height = h;
    _canvasState.set(canvas, {w, h});
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function fmtDist(cm) {
  return (typeof cm === "number" && cm >= 0) ? cm.toFixed(0) + " cm" : "--";
}

function riskInfo(risk) {
  return {
    HIGH:   {cls:"risk-high",   icon:"⚠",  label:"HIGH"},
    MEDIUM: {cls:"risk-medium", icon:"◉",  label:"MEDIUM"},
  }[risk] || {cls:"risk-clear", icon:"✓", label:"CLEAR"};
}

function sceneColor(scene) {
  if (!scene || scene === "--") return "c-muted";
  if (scene.startsWith("WF_"))                          return "c-blue";
  if (scene === "DEAD_END" || scene === "WALL_AHEAD")   return "c-amber";
  if (scene === "OPEN_AREA" || scene === "CORRIDOR")    return "c-green";
  return "c-muted";
}

// ─────────────────────────────────────────────────────────────────────────────
// Map drawing  — persists the last frame that had real data so the canvas
// never goes blank between polls or when status.json is momentarily empty.
// ─────────────────────────────────────────────────────────────────────────────
let _lastMapData = null;
const COLORS = {
  bg:       "#060d16",
  grid:     "rgba(30,45,66,.7)",
  gridText: "rgba(86,106,130,.6)",
  obstacle: "#ff5470",
  path:     "#4ea8ff",
  rover:    "#22d3a0",
  roverBg:  "rgba(34,211,160,.15)",
  origin:   "rgba(78,168,255,.2)",
};

// Recon detection category -> color (matches mapper.py CATEGORY_COLORS).
const CATEGORY_COLORS = {
  human:       "#ff5470",
  bag:         "#f5a623",
  electronics: "#4ea8ff",
  environment: "#22d3a0",
};
function catColor(cat) { return CATEGORY_COLORS[cat] || "#c0c0c0"; }

function mapBounds(data) {
  const pts = [
    ...(data.obstacle_xy || []),
    ...(data.path || []),
    ...((data.detection_tags || []).map(t => [t.x, t.y])),
  ];
  if (data.pose) pts.push(data.pose);
  if (!pts.length) return {minX:-80, maxX:80, minY:-80, maxY:80};
  let minX=Infinity, maxX=-Infinity, minY=Infinity, maxY=-Infinity;
  pts.forEach(([x,y]) => {
    minX=Math.min(minX,x); maxX=Math.max(maxX,x);
    minY=Math.min(minY,y); maxY=Math.max(maxY,y);
  });
  const span = Math.max(maxX-minX, maxY-minY, 50);
  const pad  = span * 0.10 + 20;
  return {minX:minX-pad, maxX:maxX+pad, minY:minY-pad, maxY:maxY+pad};
}

function drawMap(data) {
  const canvas = document.getElementById("mapCanvas");
  const ctx = ensureCanvasSize(canvas);
  if (!ctx) return;

  // Keep the best frame we've ever received so the map never goes blank.
  const obs  = data.obstacle_xy || [];
  const path = data.path        || [];
  const tags = data.detection_tags || [];
  if (obs.length > 0 || path.length >= 2 || tags.length > 0) _lastMapData = data;
  const d = _lastMapData || data;   // draw from cache if current frame is empty

  const cssW = canvas.getBoundingClientRect().width;
  const cssH = canvas.getBoundingClientRect().height;
  const b    = mapBounds(d);
  const scX  = cssW / (b.maxX - b.minX);
  const scY  = cssH / (b.maxY - b.minY);
  const sc   = Math.min(scX, scY);
  const offX = (cssW - (b.maxX - b.minX) * sc) / 2;
  const offY = (cssH - (b.maxY - b.minY) * sc) / 2;

  const tx = x  => offX + (x  - b.minX) * sc;
  const ty = y  => cssH - offY - (y - b.minY) * sc;

  // Background
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, cssW, cssH);

  // Grid
  const step = pickGridStep(sc);
  ctx.strokeStyle = COLORS.grid;
  ctx.lineWidth   = .5;
  ctx.font        = `10px 'JetBrains Mono', monospace`;
  ctx.fillStyle   = COLORS.gridText;
  ctx.textAlign   = "left";
  for (let g = Math.floor(b.minX/step)*step; g <= b.maxX; g += step) {
    const px = tx(g);
    ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, cssH); ctx.stroke();
    if (g !== 0) ctx.fillText(g+"cm", px+2, 12);
  }
  for (let g = Math.floor(b.minY/step)*step; g <= b.maxY; g += step) {
    const py = ty(g);
    ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(cssW, py); ctx.stroke();
    if (g !== 0) ctx.fillText(g+"cm", 3, py-3);
  }

  // Origin cross
  ctx.strokeStyle = COLORS.origin;
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(tx(0)-8, ty(0)); ctx.lineTo(tx(0)+8, ty(0)); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(tx(0), ty(0)-8); ctx.lineTo(tx(0), ty(0)+8); ctx.stroke();

  // Obstacles (from cached frame `d`)
  const dObs = d.obstacle_xy || [];
  const dotR = Math.max(1.5, Math.min(3, sc * 1.5));
  ctx.fillStyle = COLORS.obstacle;
  dObs.forEach(([x,y]) => {
    ctx.beginPath();
    ctx.arc(tx(x), ty(y), dotR, 0, Math.PI*2);
    ctx.fill();
  });

  // Path
  const dPath = d.path || [];
  if (dPath.length >= 2) {
    ctx.strokeStyle = COLORS.path;
    ctx.lineWidth   = Math.max(1, Math.min(2, sc * 0.8));
    ctx.lineJoin    = "round";
    ctx.globalAlpha = 0.75;
    ctx.beginPath();
    ctx.moveTo(tx(dPath[0][0]), ty(dPath[0][1]));
    for (let i=1; i<dPath.length; i++) ctx.lineTo(tx(dPath[i][0]), ty(dPath[i][1]));
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  // Rover (always from live data so pose stays current)
  const roverSrc = (data.pose && data.pose.length === 2) ? data : d;
  if (roverSrc.pose && roverSrc.pose.length === 2) {
    const [rx,ry] = roverSrc.pose;
    const thetaRad = (roverSrc.theta_deg || 0) * Math.PI / 180;
    const cx = tx(rx), cy = ty(ry);
    const r  = Math.max(5, Math.min(9, sc * 3));

    ctx.beginPath(); ctx.arc(cx, cy, r+4, 0, Math.PI*2);
    ctx.fillStyle = COLORS.roverBg; ctx.fill();

    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI*2);
    ctx.fillStyle = COLORS.rover; ctx.fill();

    const al = r + 14;
    ctx.strokeStyle = COLORS.rover; ctx.lineWidth = 2.5;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + al*Math.cos(thetaRad), cy - al*Math.sin(thetaRad));
    ctx.stroke();
  }

  // Detection tags (camera + YOLO) — diamonds + labels, drawn on top.
  const dTags = d.detection_tags || [];
  dTags.forEach(t => {
    const px = tx(t.x), py = ty(t.y);
    const col = catColor(t.category);
    const s = 6;
    ctx.save();
    ctx.translate(px, py);
    ctx.rotate(Math.PI / 4);
    ctx.strokeStyle = col;
    ctx.lineWidth = 2;
    ctx.strokeRect(-s, -s, 2*s, 2*s);
    ctx.restore();
    ctx.fillStyle = col;
    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.textAlign = "left";
    ctx.fillText(t.label || t.category, px + 9, py + 3);
  });

  // "Waiting" overlay only shown before the very first frame of real data.
  document.getElementById("mapNoData").style.display = _lastMapData ? "none" : "flex";
}

function pickGridStep(sc) {
  // Target ~4-6 grid lines across the visible range.
  const candidates = [10,25,50,100,200,500];
  for (const s of candidates) {
    if (sc * s >= 40) return s;
  }
  return 500;
}

// ─────────────────────────────────────────────────────────────────────────────
// Radar drawing
// ─────────────────────────────────────────────────────────────────────────────
const RADAR_MAX = 130;

function drawRadar(lastScan) {
  const canvas = document.getElementById("radarCanvas");
  const ctx = ensureCanvasSize(canvas);
  if (!ctx) return;

  const cssW = canvas.getBoundingClientRect().width;
  const cssH = canvas.getBoundingClientRect().height;
  const cx = cssW/2, cy = cssH/2;
  const rMax = Math.min(cssW, cssH) * 0.38;

  // Background
  ctx.fillStyle = "#060d16";
  ctx.fillRect(0, 0, cssW, cssH);

  // Concentric range rings
  [1, 2/3, 1/3].forEach((f,i) => {
    ctx.beginPath();
    ctx.arc(cx, cy, rMax*f, 0, Math.PI*2);
    ctx.strokeStyle = i===0 ? "rgba(30,45,66,.9)" : "rgba(20,32,48,.7)";
    ctx.lineWidth = i===0 ? 1 : .5;
    ctx.setLineDash(i===0 ? [] : [3,4]);
    ctx.stroke();
    ctx.setLineDash([]);
  });

  // Labels
  ctx.font = "9px 'JetBrains Mono', monospace";
  ctx.fillStyle = "rgba(86,106,130,.7)";
  ctx.textAlign = "center";
  [RADAR_MAX, Math.round(RADAR_MAX*2/3), Math.round(RADAR_MAX/3)].forEach((v,i) => {
    const r = rMax * [1, 2/3, 1/3][i];
    ctx.fillText(v+"cm", cx+4, cy-r+12);
  });

  // Cardinal lines
  ctx.strokeStyle = "rgba(30,45,66,.8)"; ctx.lineWidth = .5;
  [0, 90, 180, 270].forEach(a => {
    const rad = a * Math.PI/180;
    ctx.beginPath();
    ctx.moveTo(cx + (rMax+2)*Math.sin(rad), cy - (rMax+2)*Math.cos(rad));
    ctx.lineTo(cx - (rMax+2)*Math.sin(rad), cy + (rMax+2)*Math.cos(rad));
    ctx.stroke();
  });

  // Direction labels
  ctx.font = "9px Inter, sans-serif";
  ctx.fillStyle = "rgba(86,106,130,.8)";
  ctx.fillText("FWD",  cx,    cy - rMax - 7);
  ctx.fillText("L",    cx - rMax - 10, cy + 3);
  ctx.fillText("R",    cx + rMax + 10, cy + 3);

  // Sweep beams
  if (lastScan && lastScan.length) {
    lastScan.forEach(([angleDeg, dist]) => {
      if (dist == null || dist < 0) return;
      const rad  = (90 - angleDeg) * Math.PI / 180;
      const frac = Math.min(dist, RADAR_MAX) / RADAR_MAX;
      const px   = cx + frac * rMax * Math.cos(rad);
      const py   = cy - frac * rMax * Math.sin(rad);

      // Beam line with gradient feel
      ctx.strokeStyle = "rgba(78,168,255,.4)";
      ctx.lineWidth   = 1;
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(px, py); ctx.stroke();

      // Hit dot
      ctx.beginPath(); ctx.arc(px, py, 4, 0, Math.PI*2);
      ctx.fillStyle   = "#ff5470"; ctx.fill();
      ctx.strokeStyle = "rgba(255,84,112,.3)"; ctx.lineWidth = 3;
      ctx.stroke();
    });
  }

  // Rover icon
  ctx.fillStyle = "#22d3a0";
  ctx.beginPath();
  ctx.moveTo(cx, cy-8); ctx.lineTo(cx-5, cy+5); ctx.lineTo(cx+5, cy+5);
  ctx.closePath(); ctx.fill();
  ctx.strokeStyle = "rgba(34,211,160,.3)"; ctx.lineWidth = 4;
  ctx.stroke();
}

// ─────────────────────────────────────────────────────────────────────────────
// Event log — accumulates ALL events client-side across every poll.
// De-duplicates by (ts + msg), sorts newest-first.
// ─────────────────────────────────────────────────────────────────────────────
const _eventLog = [];   // grows indefinitely; keyed by ts+msg
const _eventSeen = new Set();

function mergeEvents(newEvents) {
  if (!newEvents || !newEvents.length) return false;
  let added = false;
  newEvents.forEach(ev => {
    const key = (ev.ts || "") + "|" + (ev.msg || "");
    if (!_eventSeen.has(key)) {
      _eventSeen.add(key);
      _eventLog.push(ev);
      added = true;
    }
  });
  if (added) {
    // Sort descending by timestamp string (ISO / HH:MM:SS.mmm both sort correctly).
    _eventLog.sort((a, b) => (b.ts || "").localeCompare(a.ts || ""));
  }
  return added;
}

function renderEvents(events) {
  mergeEvents(events);
  const el = document.getElementById("eventLog");
  if (!_eventLog.length) {
    el.innerHTML = '<div class="no-events">Waiting for events…</div>';
    return;
  }
  el.innerHTML = _eventLog.map(ev => {
    const msg = ev.msg || "";
    const cls = /wf_corner|dead_end|high/i.test(msg) ? " ev-crit"
              : /corner|blocked|wf_/i.test(msg)       ? " ev-warn"
              : "";
    return `<div class="event${cls}">
      <span class="ev-ts">${ev.ts || ""}</span>
      <span class="ev-msg">${msg}</span>
    </div>`;
  }).join("");
}

// ─────────────────────────────────────────────────────────────────────────────
// Detections — counts + recent list + detector status badge.
// ─────────────────────────────────────────────────────────────────────────────
function renderDetector(data) {
  const det = data.detector || {};
  const badge = document.getElementById("hdrDetect");
  const fpsEl = document.getElementById("detFps");
  if (det.enabled) {
    badge.className = "nav-tag tag-detect";
    badge.textContent = `DETECT: ON ${det.fps ? det.fps.toFixed(0)+"fps" : ""}`.trim();
    fpsEl.textContent = det.fps ? det.fps.toFixed(1) + " fps" : "--";
  } else {
    badge.className = "nav-tag tag-detect off";
    badge.textContent = "DETECT: OFF";
    fpsEl.textContent = det.available === false ? "unavailable" : "off";
  }
}

function renderDetections(data) {
  const counts = data.detection_counts || {};
  const recent = data.detections || [];

  // Big people counter
  const peopleEl = document.getElementById("peopleCount");
  if (peopleEl) peopleEl.textContent = counts["human"] || 0;

  const countsEl = document.getElementById("detCounts");
  const cats = Object.keys(counts);
  countsEl.innerHTML = cats.length
    ? cats.map(c =>
        `<span class="det-chip">
           <span class="det-swatch" style="background:${catColor(c)}"></span>
           ${c} <span style="color:var(--muted)">${counts[c]}</span>
         </span>`).join("")
    : "";

  const listEl = document.getElementById("detList");
  if (!recent.length) {
    listEl.innerHTML = '<div class="no-det">No detections yet…</div>';
    return;
  }
  listEl.innerHTML = recent.map(d => {
    const dist = (typeof d.distance_cm === "number" && d.distance_cm >= 0)
      ? d.distance_cm.toFixed(0) + "cm"
      : '<span class="det-note">dist?</span>';
    const conf = typeof d.conf === "number" ? (d.conf*100).toFixed(0)+"%" : "--";
    return `<div class="det-row">
      <span class="det-ts">${d.ts || ""}</span>
      <span class="det-label" style="color:${catColor(d.category)}">${d.label || d.category}</span>
      <span class="det-meta">${conf} · ${dist}</span>
    </div>`;
  }).join("");
}

// ─────────────────────────────────────────────────────────────────────────────
// UI update
// ─────────────────────────────────────────────────────────────────────────────
function updateUI(data) {
  const mode  = data.mode  || "STOP";
  const scene = data.scene || "--";
  const risk  = data.risk  || "CLEAR";
  const ri    = riskInfo(risk);
  const pose  = data.pose;

  document.getElementById("hdrMode").textContent = mode;

  const banner = document.getElementById("riskBanner");
  banner.className = "risk-banner " + ri.cls;
  document.getElementById("riskIcon").textContent = ri.icon;
  document.getElementById("riskText").textContent =
    `${ri.label}  ·  Front: ${fmtDist(data.front_distance_cm)}`;

  const scEl = document.getElementById("cScene");
  scEl.textContent = scene;
  scEl.className   = "card-val sm " + sceneColor(scene);

  document.getElementById("cObstacles").textContent = data.obstacles  ?? "--";
  document.getElementById("cPath").textContent      = data.path_points ?? "--";
  document.getElementById("cPose").textContent      =
    (pose && pose.length === 2) ? `${pose[0].toFixed(0)}, ${pose[1].toFixed(0)}` : "--";
  document.getElementById("cTheta").textContent     =
    typeof data.theta_deg === "number" ? data.theta_deg.toFixed(0) + "°" : "--";
  document.getElementById("cDist").textContent      = fmtDist(data.last_distance_cm);
  document.getElementById("cAction").textContent    = data.last_action || "--";
  document.getElementById("mapUpdated").textContent = data.updated || "--";

  drawMap(data);
  drawRadar(data.last_scan);
  renderEvents(data.events);
  renderDetector(data);
  renderDetections(data);
}

// ─────────────────────────────────────────────────────────────────────────────
// Camera feed — always polls /api/camera/frame every 500 ms.
// Works whether the camera runs via pipeline.py or test_detector.py.
// ─────────────────────────────────────────────────────────────────────────────
function _showCamFrame(src) {
  const img = document.getElementById("camImg");
  const ph  = document.getElementById("camPlaceholder");
  img.onload  = () => { img.style.display = "block"; ph.style.display = "none"; };
  img.onerror = () => { img.style.display = "none";  ph.style.display = "flex"; };
  img.src = src;
}

async function pollCamera() {
  const stEl = document.getElementById("camStatus");
  try {
    const r = await fetch("/api/camera/frame?t=" + Date.now());
    if (r.ok && r.status !== 204) {
      stEl.textContent = "live";
      _showCamFrame("/api/camera/frame?t=" + Date.now());
    } else {
      stEl.textContent = "waiting…";
      document.getElementById("camImg").style.display = "none";
      document.getElementById("camPlaceholder").style.display = "flex";
    }
  } catch (_) {
    stEl.textContent = "err";
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Polling
// ─────────────────────────────────────────────────────────────────────────────
async function poll() {
  try {
    const r = await fetch("/api/status");
    if (r.ok) updateUI(await r.json());
  } catch (_) {}
}

// Redraw on resize without resetting data (use last polled value).
let _lastData = {};
const _origUpdateUI = updateUI;
window.updateUI = d => { _lastData = d; _origUpdateUI(d); };
window.addEventListener("resize", () => { if (_lastData) _origUpdateUI(_lastData); });

poll();
pollCamera();
setInterval(poll, 500);
setInterval(pollCamera, 500);
</script>
</body>
</html>"""


def create_app():
    try:
        from flask import Flask, Response, jsonify
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Flask is required. Install with: pip install Flask"
        ) from exc

    app = Flask(__name__)

    @app.route("/")
    def index():
        return Response(PAGE, mimetype="text/html")

    @app.route("/api/status")
    def api_status():
        return jsonify(_read_status())

    @app.route("/api/camera/frame")
    def api_camera_frame():
        if not os.path.exists(CAMERA_FRAME):
            return Response("", status=204)
        try:
            with open(CAMERA_FRAME, "rb") as fh:
                data = fh.read()
            return Response(data, mimetype="image/jpeg",
                            headers={"Cache-Control": "no-store, no-cache"})
        except OSError:
            return Response("", status=204)

    return app


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="DARKMAP-Q local dashboard")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    app = create_app()
    print(f"[dashboard] http://{args.host}:{args.port}  (offline)")
    print(f"[dashboard] status source: {STATUS_JSON}")
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
