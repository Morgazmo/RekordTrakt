// Shared by every part of the window: the server, small DOM helpers, the app's state, and a tiny event bus.
export const TOKEN = new URLSearchParams(location.search).get("token") || "";
export const $ = (id) => document.getElementById(id);

export function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

export const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* blocked: not remembered */ } },
};

// What the window knows: status from /api/status, the live view, device definitions, the function list.
export const app = { status: null, view: null, defs: {}, functions: null, midiDevices: null, tab: "controllers" };

const handlers = {};
export function on(name, fn) { (handlers[name] = handlers[name] || []).push(fn); }
export function emit(name, data) { for (const fn of handlers[name] || []) fn(data); }

export async function post(name, body, keepalive = false) {
  const r = await fetch(`/api/${name}`, {
    method: "POST", keepalive,
    headers: { "X-RekordTrakt-Token": TOKEN, "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await r.json().catch(() => ({ ok: false, error: `HTTP ${r.status}` }));
  if (!data.ok) throw new Error(data.error || "failed");
  return data.result;
}

export async function get(path) {
  const r = await fetch(`${path}?token=${encodeURIComponent(TOKEN)}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

let toastTimer;
export function toast(text, err) {
  const t = $("toast");
  t.textContent = text;
  t.className = "toast show" + (err ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = "toast" + (err ? " err" : ""); }, err ? 4000 : 1400);
}

export async function change(name, body, done = "Saved") {
  try { const r = await post(name, body); if (done) toast(done); return r === undefined ? true : r; }
  catch (e) { toast(e.message, true); return false; }
}

// A small question box (name a page, confirm a removal), instead of the browser's prompt().
export function ask({ title, text, value, placeholder, ok = "OK" }) {
  return new Promise((resolve) => {
    const d = el("dialog", "ask");
    d.appendChild(el("h2", null, title));
    const body = el("div", "body");
    if (text) body.appendChild(el("p", "why", text)).style.padding = "0";
    let input = null;
    if (value !== undefined) {
      input = el("input");
      input.type = "text"; input.value = value || ""; input.placeholder = placeholder || ""; input.maxLength = 24;
      body.appendChild(input);
    }
    const foot = el("div", "foot");
    const cancel = el("button", null, "Cancel"), yes = el("button", null, ok);
    foot.append(cancel, yes);
    d.append(body, foot);
    document.body.appendChild(d);
    const done = (v) => { d.close(); d.remove(); resolve(v); };
    cancel.onclick = () => done(null);
    yes.onclick = () => done(input ? input.value.trim() || null : true);
    d.addEventListener("cancel", (e) => { e.preventDefault(); done(null); });
    if (input) input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); yes.click(); } });
    d.showModal();
    (input || yes).focus();
  });
}

export const SVG = {
  lockOpen: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/></svg>',
  lockShut: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
  grip: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
  pencil: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
  system: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>',
  light: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  dark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
  palette: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22a10 10 0 1 1 10-10c0 2.8-2.2 4-4 4h-2a2 2 0 0 0-1 3.7A2 2 0 0 1 12 22z"/><circle cx="7.5" cy="10.5" r="1.2"/><circle cx="11.5" cy="7" r="1.2"/><circle cx="16.5" cy="9" r="1.2"/></svg>',
  heart: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.6 2.9 5 6.4 5c2 0 3.6 1.1 4.4 2.6h2.4C14 6.1 15.6 5 17.6 5c3.5 0 5.5 3.6 4 6.8C19.5 16.4 12 21 12 21z"/></svg>',
};

// SVG strings above are fixed markup in this file, never data, so setting them as innerHTML is safe.
export function icon(name) {
  const span = el("span");
  span.innerHTML = SVG[name];
  return span.firstChild;
}
