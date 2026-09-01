"use strict";
const pad = document.getElementById("pad");
for (let i = 0; i < 12; i++) {
  const hue = i / 12;
  const b = document.createElement("button");
  b.style.background = `hsl(${Math.round(hue * 360)} 100% 50%)`;
  b.textContent = ".";
  b.onclick = () => {
    fetch("/api/guest/vote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hue }),
    });
    b.style.outline = "3px solid #fff";
    setTimeout(() => (b.style.outline = ""), 300);
  };
  pad.appendChild(b);
}

async function refreshCrowd() {
  const s = await (await fetch("/api/state")).json();
  const el = document.getElementById("crowd");
  el.style.background = s.crowd.strength > 0
    ? `hsl(${Math.round(s.crowd.hue * 360)} 100% 50% / ${0.3 + 0.7 * s.crowd.strength})`
    : "transparent";
}
setInterval(refreshCrowd, 2000);
refreshCrowd();
