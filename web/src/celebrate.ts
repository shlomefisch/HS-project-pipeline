// The one moment of fanfare: finishing a step. A handful of sand and navy tiles
// burst from where you tapped and settle. Off for anyone who asked for less motion.

export function celebrate(x = window.innerWidth / 2, y = window.innerHeight / 2): void {
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  const layer = document.createElement("div");
  layer.className = "burst";
  layer.setAttribute("aria-hidden", "true");
  const colors = ["#B79F7E", "#1A334A", "#D9C7A8", "#2F855A", "#B79F7E"];
  for (let i = 0; i < 18; i++) {
    const t = document.createElement("span");
    const angle = (Math.PI * 2 * i) / 18 + Math.random() * 0.4;
    const dist = 70 + Math.random() * 90;
    t.style.left = `${x}px`;
    t.style.top = `${y}px`;
    t.style.background = colors[i % colors.length];
    t.style.setProperty("--dx", `${Math.cos(angle) * dist}px`);
    t.style.setProperty("--dy", `${Math.sin(angle) * dist - 30}px`);
    t.style.setProperty("--r", `${Math.random() * 180 - 90}deg`);
    t.style.animationDelay = `${Math.random() * 60}ms`;
    layer.appendChild(t);
  }
  document.body.appendChild(layer);
  window.setTimeout(() => layer.remove(), 1100);
}

let lastTap = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
if (typeof window !== "undefined") {
  window.addEventListener("pointerdown", (e) => (lastTap = { x: e.clientX, y: e.clientY }), { capture: true, passive: true });
}
/** Bursts from wherever the person last tapped or clicked. */
export function celebrateHere(): void {
  celebrate(lastTap.x, lastTap.y);
}
