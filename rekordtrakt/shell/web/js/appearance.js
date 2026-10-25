// Theme (System / Light / Dark) and skin (accent and palette), set from the header's Theme button only, and
// remembered in this window's storage. The Debug page reads the same keys, so both follow.
import { $, el, icon } from "./core.js";
import { popover } from "./popover.js";

export const THEMES = [["system", "System"], ["light", "Light"], ["dark", "Dark"]];
export const SKINS = [["teal", "Teal", "#5dcaa5"], ["blue", "Blue", "#4c9dff"], ["orange", "Orange", "#ff8a1f"],
                      ["contrast", "High contrast", "#ffd60a"]];

export function current() {
  const theme = rawGet("rt-theme"), skin = rawGet("rt-skin");
  return { theme: THEMES.some(([k]) => k === theme) ? theme : "system", skin: SKINS.some(([k]) => k === skin) ? skin : "teal" };
}
function rawGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function rawSet(k, v) { try { localStorage.setItem(k, v); } catch { /* not remembered */ } }

export function apply({ theme, skin }) {
  const root = document.documentElement;
  if (theme === "light" || theme === "dark") root.dataset.theme = theme; else delete root.dataset.theme;
  if (skin && skin !== "teal") root.dataset.skin = skin; else delete root.dataset.skin;
  const b = $("appearance-btn");
  if (b) b.title = `Theme: ${THEMES.find(([k]) => k === theme)[1]} · Skin: ${SKINS.find(([k]) => k === skin)[1]}`;
}

function set(change) {
  const next = { ...current(), ...change };
  rawSet("rt-theme", next.theme);
  rawSet("rt-skin", next.skin);
  apply(next);
  draw();
}

function draw() {
  const now = current(), pop = $("appearance-pop");
  const seg = el("div", "seg");
  for (const [key, label] of THEMES) {
    const b = el("button");
    b.append(icon(key), el("span", null, label));
    b.setAttribute("aria-pressed", String(now.theme === key));
    b.onclick = () => set({ theme: key });
    seg.appendChild(b);
  }
  const skins = el("div", "skins");
  for (const [key, label, colour] of SKINS) {
    const b = el("button");
    const dot = el("i");
    dot.style.background = colour;
    b.append(dot, el("span", null, label));
    b.setAttribute("aria-pressed", String(now.skin === key));
    b.onclick = () => set({ skin: key });
    skins.appendChild(b);
  }
  pop.replaceChildren(el("h4", null, "Theme"), seg, el("h4", null, "Skin"), skins);
}

export function setupHeaderButton() {
  draw();
  popover($("appearance-btn"), $("appearance-pop"));
  apply(current());
}
