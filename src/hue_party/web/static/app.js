"use strict";
const BLANK_COVER = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBTAA7";
const post = (url, body) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
               body: body ? JSON.stringify(body) : null });

const PALETTE_SWATCHES = {
  fiesta: "#ff4fa0",
  neon: "#8b6bff",
  sunset: "#ff8a4c",
  ice: "#5fd3ff",
};

let state = null;
let lastTrack = null;

const startCase = (name) =>
  name.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");

function pickerRow(el, items, active, onPick, { swatches = false } = {}) {
  el.replaceChildren(...items.map((name) => {
    const b = document.createElement("button");
    if (swatches) {
      const dot = document.createElement("span");
      dot.className = "swatch";
      dot.style.background = PALETTE_SWATCHES[name] || "#8b6bff";
      b.appendChild(dot);
      b.appendChild(document.createTextNode(startCase(name)));
    } else {
      b.textContent = startCase(name);
    }
    if (name === active) b.classList.add("active");
    b.onclick = () => onPick(name);
    return b;
  }));
}

function render(s) {
  state = s;
  pickerRow(document.getElementById("modes"), s.modes, s.mode,
            (m) => post("/api/mode", { mode: m }));
  pickerRow(document.getElementById("palettes"), s.palettes, s.palette,
            (p) => post("/api/palette", { palette: p }), { swatches: true });
  if (s.beat_engines) {
    document.getElementById("engines-section").hidden = false;
    pickerRow(document.getElementById("engines"), s.beat_engines, s.beat_engine,
              (b) => post("/api/beat_engine", { engine: b }));
  }

  const calibrate = document.getElementById("calibrate");
  calibrate.lastChild.textContent =
    s.calibration ? " Calibrating — tap to finish" : " Calibrate light delay";
  calibrate.classList.toggle("active", s.calibration);

  document.getElementById("offset").value = s.offset_ms;
  document.getElementById("offsetVal").textContent = `${s.offset_ms} ms`;
  document.getElementById("brightness").value = s.brightness_cap;
  document.getElementById("brightnessVal").textContent = `${Math.round(s.brightness_cap * 100)}%`;

  const track = document.getElementById("track");
  track.textContent = s.track || "";
  const cover = document.getElementById("cover");
  if (s.track) {
    if (s.track !== lastTrack) cover.src = `/api/art?t=${Date.now()}`;
    cover.classList.remove("empty");
  } else {
    cover.classList.add("empty");
    cover.src = BLANK_COVER;
  }
  lastTrack = s.track;

  document.getElementById("stop-party").disabled = !s.track;  // nothing to stop

  const dropBtn = document.getElementById("drop");
  const dropBar = document.getElementById("drop-bar");
  const dropFill = document.getElementById("drop-bar-fill");
  dropBtn.disabled = s.drop.active;
  dropBar.hidden = !s.drop.active;
  if (s.drop.active) {
    // Snap the bar to the server's remaining time, then let CSS drain it to zero.
    dropFill.style.transition = "none";
    dropFill.style.width = `${(s.drop.remaining_s / s.drop.duration_s) * 100}%`;
    void dropFill.offsetWidth;  // flush so the transition below animates from here
    dropFill.style.transition = `width ${s.drop.remaining_s}s linear`;
    dropFill.style.width = "0%";
  }

  const panic = document.getElementById("panic");
  panic.lastChild.textContent = s.panic ? " Panic on — tap to resume" : " Panic: lights on";
  panic.classList.toggle("active", s.panic);

  const crowd = document.getElementById("crowd");
  crowd.classList.toggle("live", s.crowd.strength > 0);
  crowd.style.background = s.crowd.strength > 0
    ? `hsl(${Math.round(s.crowd.hue * 360)} 100% 60% / ${0.35 + 0.65 * s.crowd.strength})`
    : "transparent";

  const statusEl = document.getElementById("status");
  const entries = Object.entries(s.status);
  if (!entries.length) {
    statusEl.textContent = "starting\u2026";
  } else {
    // Group the module health dots so the footer stays one short row.
    const GROUP_OF = { analyzer: "Audio", player: "Audio", speakers: "Audio",
                       streamer: "Lights", watchdog: "Lights", web: "Web" };
    const groups = new Map();  // name -> {members: [..], worst: 0 ok | 1 warn | 2 bad}
    const SEVERITY = (st) => (st === "running" ? 0 : st === "restarting" ? 1 : 2);
    entries.forEach(([name, st]) => {
      if (name === "stream") return;  // rendered separately: state, not health
      const group = GROUP_OF[name] || "Web";
      const entry = groups.get(group) || { members: [], worst: 0 };
      entry.members.push(`${name}: ${st}`);
      entry.worst = Math.max(entry.worst, SEVERITY(st));
      groups.set(group, entry);
    });
    const items = [...groups.entries()].map(([name, g]) => {
      const item = document.createElement("span");
      item.className = "st";
      item.title = g.members.join(" \u00b7 ");
      const dot = document.createElement("span");
      dot.className = "st-dot " + (g.worst === 0 ? "ok" : g.worst === 1 ? "warn" : "bad");
      const label = document.createElement("span");
      label.textContent = name;
      item.append(dot, label);
      return item;
    });
    if ("stream" in s.status) {
      const item = document.createElement("span");
      item.className = "st";
      item.title = `stream: ${s.status.stream}`;
      const dot = document.createElement("span");
      dot.className = "st-dot " + (s.status.stream === "live" ? "ok" : "off");
      const label = document.createElement("span");
      label.textContent = "Stream";
      item.append(dot, label);
      items.push(item);
    }
    statusEl.replaceChildren(...items);
  }
}

document.getElementById("cover").onerror = (e) => {
  e.target.classList.add("empty");
  if (e.target.src !== BLANK_COVER) e.target.src = BLANK_COVER;
};

document.getElementById("offset").oninput = (e) =>
  post("/api/offset", { offset_ms: Number(e.target.value) });
document.getElementById("brightness").oninput = (e) =>
  post("/api/brightness", { cap: Number(e.target.value) });
document.getElementById("panic").onclick = () =>
  post("/api/panic", { on: !(state && state.panic) });
document.getElementById("calibrate").onclick = () =>
  post("/api/calibration", { on: !(state && state.calibration) });
document.querySelectorAll("#player button[data-player]").forEach((b) => {
  b.onclick = () => post(`/api/player/${b.dataset.player}`);
});
const restartOverlay = document.getElementById("restart-confirm");
document.getElementById("restart-btn").onclick = () => { restartOverlay.hidden = false; };
document.getElementById("restart-cancel").onclick = () => { restartOverlay.hidden = true; };
restartOverlay.onclick = (e) => { if (e.target === restartOverlay) restartOverlay.hidden = true; };
document.getElementById("restart-confirm-btn").onclick = () => {
  restartOverlay.hidden = true;
  post("/api/system/restart");
  // The websocket drops during the restart; its reconnect loop recovers the page.
};

const stopOverlay = document.getElementById("stop-confirm");
document.getElementById("stop-party").onclick = () => { stopOverlay.hidden = false; };
document.getElementById("stop-cancel").onclick = () => { stopOverlay.hidden = true; };
stopOverlay.onclick = (e) => { if (e.target === stopOverlay) stopOverlay.hidden = true; };
document.getElementById("stop-confirm-btn").onclick = () => {
  stopOverlay.hidden = true;
  post("/api/party/stop");
};
document.getElementById("drop").onclick = () => post("/api/drop/start");

const TABS = ["music", "recent", "party"];
function showTab(name) {
  TABS.forEach((t) => {
    document.getElementById(`tab-${t}`).hidden = t !== name;
    const btn = document.getElementById(`tab-btn-${t}`);
    btn.classList.toggle("active", t === name);
    btn.setAttribute("aria-selected", String(t === name));
  });
  localStorage.setItem("hueparty.tab", name);
  if (name === "recent") refreshRecent();
}

const RECENT_VIEWS = ["tracks", "lists", "picks"];
function showRecentView(name) {
  RECENT_VIEWS.forEach((v) => {
    document.getElementById(`recent-${v}`).hidden = v !== name;
    const btn = document.getElementById(`recent-btn-${v}`);
    btn.classList.toggle("active", v === name);
    btn.setAttribute("aria-selected", String(v === name));
  });
  localStorage.setItem("hueparty.recentView", name);
}
RECENT_VIEWS.forEach((v) => {
  document.getElementById(`recent-btn-${v}`).onclick = () => showRecentView(v);
});
const storedRecentView = localStorage.getItem("hueparty.recentView");
if (RECENT_VIEWS.includes(storedRecentView)) showRecentView(storedRecentView);

function recentRow(entry, isList) {
  const row = document.createElement("button");
  row.className = "result";
  const img = document.createElement("img");
  img.alt = "";
  if (entry.thumb) img.src = entry.thumb;
  const meta = document.createElement("div");
  meta.className = "meta";
  const title = document.createElement("div");
  title.className = "title";
  title.textContent = entry.title || entry.url;
  const artist = document.createElement("div");
  artist.className = "artist";
  artist.textContent = isList ? "YouTube list" : entry.artist || "";
  meta.append(title, artist);
  row.append(img, meta);
  row.onclick = () => {
    showTab("music");
    const body = isList
      ? { url: entry.url, title: entry.title }
      : { video_id: entry.id, title: entry.title, artist: entry.artist, thumb: entry.thumb };
    playMusic(body, `“${entry.title || "your pick"}”`);
  };
  return row;
}

async function refreshRecent() {
  let recent;
  try {
    const resp = await fetch("/api/music/history");
    if (!resp.ok) return;
    recent = await resp.json();
  } catch {
    return; // server restarting; next tab open retries
  }
  const fill = (elId, items, isList, empty) => {
    const el = document.getElementById(elId);
    if (!items.length) {
      el.replaceChildren();
      const div = document.createElement("div");
      div.className = "hint";
      div.textContent = empty;
      el.appendChild(div);
      return;
    }
    el.replaceChildren(...items.map((e) => recentRow(e, isList)));
  };
  fill("recent-tracks", recent.tracks, false, "Nothing played yet.");
  fill("recent-lists", recent.lists, true, "No lists played yet.");

  try {
    const picksResp = await fetch("/api/music/recommended");
    if (!picksResp.ok) return;
    const picks = await picksResp.json();
    const el = document.getElementById("recent-picks");
    if (!picks.length) return;  // keep the loading hint; next open retries
    // Recommended picks come in search-result shape: adapt to recentRow's fields.
    el.replaceChildren(...picks.map((p) =>
      recentRow({ id: p.video_id, title: p.title, artist: p.artist, thumb: p.thumb }, false)));
  } catch {
    /* server restarting; next tab open retries */
  }
}
TABS.forEach((t) => {
  document.getElementById(`tab-btn-${t}`).onclick = () => showTab(t);
});
const hashTab = location.hash.slice(1);
const storedTab = localStorage.getItem("hueparty.tab");
showTab(TABS.includes(hashTab) ? hashTab : TABS.includes(storedTab) ? storedTab : "music");

const resultsEl = document.getElementById("music-results");
const queryEl = document.getElementById("music-query");

function resultsMessage(cls, text) {
  resultsEl.replaceChildren();
  const div = document.createElement("div");
  div.className = cls;
  div.textContent = text;
  resultsEl.appendChild(div);
}

async function playMusic(body, label) {
  resultsMessage("hint", `Starting ${label}\u2026`);
  const resp = await post("/api/music/play", body);
  if (resp.ok) {
    resultsMessage("hint", `Playing ${label} \u2014 give Chrome a few seconds.`);
  } else {
    const detail = (await resp.json().catch(() => ({}))).detail;
    resultsMessage("error", detail || `Could not play ${label}.`);
  }
}

function renderResults(tracks) {
  if (!tracks.length) {
    resultsMessage("hint", "No songs found.");
    return;
  }
  resultsEl.replaceChildren(...tracks.map((t) => {
    const row = document.createElement("button");
    row.className = "result";
    const img = document.createElement("img");
    img.alt = "";
    if (t.thumb) img.src = t.thumb;
    const meta = document.createElement("div");
    meta.className = "meta";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = t.title;
    const artist = document.createElement("div");
    artist.className = "artist";
    artist.textContent = t.artist;
    meta.append(title, artist);
    const duration = document.createElement("div");
    duration.className = "duration";
    duration.textContent = t.duration || "";
    row.append(img, meta, duration);
    row.onclick = () =>
      playMusic(
        { video_id: t.video_id, title: t.title, artist: t.artist, thumb: t.thumb },
        `\u201c${t.title}\u201d`,
      );
    return row;
  }));
}

document.getElementById("music-form").onsubmit = async (e) => {
  e.preventDefault();
  const q = queryEl.value.trim();
  if (!q) return;
  queryEl.blur();
  if (/^https?:\/\//i.test(q)) {
    await playMusic({ url: q }, "your link");
    queryEl.value = "";
    return;
  }
  resultsMessage("hint", "Searching\u2026");
  try {
    const resp = await fetch(`/api/music/search?q=${encodeURIComponent(q)}`);
    if (!resp.ok) {
      const detail = (await resp.json().catch(() => ({}))).detail;
      resultsMessage("error", detail || "Search failed.");
      return;
    }
    renderResults(await resp.json());
  } catch {
    resultsMessage("error", "Search failed \u2014 is the server up?");
  }
};

const guestUrl = `${location.origin}/guest`;
document.getElementById("guestUrl").textContent = `Guests: ${guestUrl}`;
if (window.QRCode) new QRCode(document.getElementById("qr"), { text: guestUrl, width: 140, height: 140 });

const speakersEl = document.getElementById("speakers");
let speakersBusy = false;

function renderSpeakers(speakers) {
  if (!speakers.length) {
    speakersEl.innerHTML = '<div class="speaker-empty">No Sonos speakers found on the network.</div>';
    return;
  }
  speakersEl.replaceChildren(...speakers.map((sp) => {
    const row = document.createElement("div");
    row.className = "speaker" + (sp.enabled ? "" : " off");

    const name = document.createElement("div");
    name.className = "speaker-name";
    name.textContent = sp.name;

    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = 0;
    slider.max = 100;
    slider.step = 5;
    slider.value = sp.volume_pct;
    slider.setAttribute("aria-label", `${sp.name} volume`);
    slider.oninput = () => post("/api/speakers/volume", { sink: sp.sink, pct: Number(slider.value) });

    const toggle = document.createElement("button");
    toggle.className = "speaker-toggle" + (sp.enabled ? " on" : "");
    toggle.setAttribute("aria-label", `${sp.name} ${sp.enabled ? "on" : "off"}`);
    toggle.onclick = async () => {
      speakersBusy = true;
      try {
        await post("/api/speakers/toggle", { sink: sp.sink, enabled: !sp.enabled });
      } finally {
        speakersBusy = false;
      }
      refreshSpeakers();
    };

    row.append(name, slider, toggle);
    return row;
  }));
}

async function refreshSpeakers() {
  if (speakersBusy || document.activeElement?.closest?.("#speakers-card")) return;
  try {
    const resp = await fetch("/api/speakers");
    if (!resp.ok) return;
    const speakers = await resp.json();
    renderSpeakers(speakers);
    if (speakers.length) {
      const avg = speakers.reduce((sum, sp) => sum + sp.volume_pct, 0) / speakers.length;
      document.getElementById("master-volume").value = Math.round(avg);
    }
  } catch {
    /* server restarting; next poll will recover */
  }
}

document.getElementById("master-volume").oninput = (e) =>
  post("/api/speakers/volume_all", { pct: Number(e.target.value) });
setInterval(refreshSpeakers, 5000);
refreshSpeakers();

const rescanBtn = document.getElementById("speakers-rescan");
rescanBtn.onclick = async () => {
  rescanBtn.disabled = true;
  rescanBtn.textContent = "Scanning…";
  try {
    await post("/api/speakers/rescan");  // takes a few seconds: fresh mDNS browse
    await refreshSpeakers();
  } finally {
    rescanBtn.disabled = false;
    rescanBtn.textContent = "Rescan";
  }
};

// PWA: registers only in secure contexts (HTTPS/localhost); harmless elsewhere.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (e) => render(JSON.parse(e.data));
  ws.onclose = () => setTimeout(connect, 1500);
}
connect();
