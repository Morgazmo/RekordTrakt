// The Controllers tab. Each card is built once from its device definition's layout; after that every view update
// only changes text, classes and knob positions in place. So nothing flashes, a held mouse button keeps its control
// pressed while the labels change around it, and the mapping editor can point at a control that stays put.
import { $, app, change, el, emit, get, icon, post, store, toast } from "./core.js";

const DECK_VAR = (d) => `var(--d${d || 1})`;
const cards = new Map();                                // position -> card
const locks = store.get("rt-device-locks", {});        // position -> true when its on-screen controls are locked
const editing = new Set(store.get("rt-editing", []));  // positions in edit mode: a click opens the editor
const held = new Map();                                 // "position|control" -> element, presses in progress
let renaming = false;

export function isEditing(position) { return editing.has(position); }
export function setEditing(position, on) {
  if (on) editing.add(position); else editing.delete(position);
  store.set("rt-editing", [...editing]);
  if (on) { releaseAll(); toast("Click a control to change what it does"); }
  renderControllers();
}

// ---- the window as a controller ------------------------------------------------------------------------------
function sendInput(position, control, action, value = 0) {
  return post("input", { position, control, action, value }).catch((e) => toast(e.message, true));
}
export function releaseAll() {
  for (const node of held.values()) node.classList.remove("pressed");
  held.clear();
  post("release-ui", {}, true).catch(() => {});
}
window.addEventListener("blur", () => { if (held.size) releaseAll(); });
document.addEventListener("visibilitychange", () => { if (document.hidden && held.size) releaseAll(); });
window.addEventListener("pagehide", () => { if (held.size) releaseAll(); });

const usable = (card) => !locks[card.position] && !editing.has(card.position);

function pressable(node, card, control) {
  node.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || !usable(card)) return;
    e.preventDefault();
    e.stopPropagation();
    node.setPointerCapture(e.pointerId);
    const key = `${card.position}|${control}`;
    held.set(key, node);
    node.classList.add("pressed");
    sendInput(card.position, control, "press");
    const up = () => {
      for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) node.removeEventListener(ev, up);
      if (!held.has(key)) return;
      held.delete(key);
      node.classList.remove("pressed");
      sendInput(card.position, control, "release");
    };
    for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) node.addEventListener(ev, up);
  });
}

function draggable(cell, card, control, shape, redraw) {
  cell.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || !usable(card) || !cell._c) return;
    e.preventDefault();
    cell.setPointerCapture(e.pointerId);
    const c = cell._c;
    const startY = e.clientY, startValue = c.sent != null ? c.sent : c.value != null ? c.value : 64;
    let value = startValue, dragging = false, pending = null, timer = null;
    const flush = () => { if (pending != null) { sendInput(card.position, control, "value", pending); pending = null; } };
    const move = (m) => {
      const dy = startY - m.clientY;
      if (!dragging && Math.abs(dy) < 4) return;                // a small threshold, so a click doesn't move it
      dragging = true;
      cell.dataset.dragging = "1";
      const v = Math.max(0, Math.min(127, Math.round(startValue + dy / (shape === "fader" ? 0.6 : 2))));
      if (v === value) return;
      value = v;
      redraw(v, null);
      pending = v;
      if (!timer) timer = setInterval(flush, 33);
    };
    const end = () => {
      cell.removeEventListener("pointermove", move);
      cell.removeEventListener("pointerup", end);
      cell.removeEventListener("pointercancel", end);
      clearInterval(timer);
      flush();
      delete cell.dataset.dragging;
    };
    cell.addEventListener("pointermove", move);
    cell.addEventListener("pointerup", end);
    cell.addEventListener("pointercancel", end);
  });
  cell.addEventListener("dblclick", () => {
    const c = cell._c;
    if (!usable(card) || !c) return;
    if (c.default == null) return toast("This control has no neutral position to go back to.");
    sendInput(card.position, control, "value", c.default);
    toast(`${c.label}: back to ${c.default === 64 ? "centre" : c.default}`);
  });
}

function turnable(cell, card, control) {
  cell.addEventListener("wheel", (e) => {
    if (!usable(card)) return;
    e.preventDefault();
    sendInput(card.position, control, "turn", e.deltaY < 0 ? 1 : -1);
  }, { passive: false });
  cell.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || !usable(card) || e.target.closest(".push")) return;
    e.preventDefault();
    cell.setPointerCapture(e.pointerId);
    let lastX = e.clientX;
    const move = (m) => {
      const steps = Math.trunc((m.clientX - lastX) / 12);
      if (!steps) return;
      lastX += steps * 12;
      sendInput(card.position, control, "turn", Math.max(-8, Math.min(8, steps)));
    };
    const end = () => {
      cell.removeEventListener("pointermove", move);
      cell.removeEventListener("pointerup", end);
      cell.removeEventListener("pointercancel", end);
    };
    cell.addEventListener("pointermove", move);
    cell.addEventListener("pointerup", end);
    cell.addEventListener("pointercancel", end);
  });
}

// ---- drawing helpers ---------------------------------------------------------------------------------------
function dial(svg, value, hw, size) {
  const NS = "http://www.w3.org/2000/svg", c = size / 2, r = size / 2 - 3, start = 135, sweep = 270;
  svg.replaceChildren();
  const pt = (f) => { const a = (start + f * sweep) * Math.PI / 180; return [c + r * Math.cos(a), c + r * Math.sin(a)]; };
  const arc = (from, to, cls) => {
    const [x0, y0] = pt(from), [x1, y1] = pt(to);
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", `M ${x0} ${y0} A ${r} ${r} 0 ${(to - from) * sweep > 180 ? 1 : 0} 1 ${x1} ${y1}`);
    p.setAttribute("class", cls); p.setAttribute("fill", "none"); p.setAttribute("stroke-width", 4); p.setAttribute("stroke-linecap", "round");
    svg.appendChild(p);
  };
  arc(0, 1, "track");
  if (value != null && value > 0) arc(0, Math.max(0.01, value / 127), "fill");
  if (hw != null) {                                 // where the physical knob is while pickup waits
    const [x, y] = pt(hw / 127);
    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.setAttribute("r", 2.5); dot.setAttribute("class", "hwpos");
    svg.appendChild(dot);
  }
}
function newDial(size) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "dial"); svg.setAttribute("width", size); svg.setAttribute("height", size);
  return svg;
}
function placed(node, item) {
  node.style.gridColumn = `${item.c} / span ${item.w || 1}`;
  node.style.gridRow = `${item.r} / span ${item.h || 1}`;
  return node;
}
function halfOf(dev, id) {
  if (!dev.halves.length || dev.halves[0].half == null) return { half: dev.halves[0], base: id };
  const [h, base] = id.split(".", 2);
  return { half: dev.halves.find((x) => x.half === h), base };
}
const shiftOn = (dev) => !!(dev.shift_latched || dev.shift_held);

export function labelFor(c, shifted) {
  if (!c) return ["unmapped", true];
  if (shifted) {
    if (c.shift) return [c.shift_short || c.shift, false];
    return c.kind === "value" && c.label ? [c.short || c.label, false] : ["—", true];
  }
  if (!c.label) return ["unmapped", true];
  if (c.disabled) return ["—", true];
  let text = c.short || c.label;
  if (c.alt && /^Cue /.test(text) && /^Cue /.test(c.alt)) text = `${text} (${c.alt.slice(4)})`;
  return [text, false];
}

// ---- building a card -------------------------------------------------------------------------------------
function buildCard(dev, def) {
  const card = { position: dev.position, type: dev.type, dev, def, updaters: [], node: el("div", "device") };
  card.node.appendChild(buildHead(card));
  const face = el("div", "face");
  const colWidth = (def.layout.columns || []).length > 4 ? "42px" : "60px";        // X1: half-columns; F1: columns
  face.style.gridTemplateColumns = (def.layout.columns || []).map((w) => w === "1fr" ? colWidth : w).join(" ");
  const framed = new Set();                         // grid rows inside a row frame: their cells leave room for its title
  for (const item of def.layout.items)
    if (item.role === "row") for (let r = item.r; r < item.r + (item.h || 1); r++) framed.add(r);
  for (const item of def.layout.items)
    face.appendChild(item.control ? buildCell(card, item, framed.has(item.r)) : buildRole(card, item));
  for (const h of dev.halves) if (h.half) face.appendChild(buildHalfFrame(card, h.half));
  card.node.appendChild(face);
  card.node.addEventListener("contextmenu", (e) => {
    const cell = e.target.closest(".cell[data-control]");
    if (!cell) return;
    e.preventDefault();
    emit("edit", { position: card.position, control: cell.dataset.editControl || cell.dataset.control });
  });
  return card;
}

function buildHead(card) {
  const { dev, def } = card;
  const head = el("div", "device-head");
  const dot = el("span", "dot");
  const name = el("span", "name", dev.name);
  name.contentEditable = "plaintext-only";
  name.spellcheck = false;
  name.title = "Click to rename";
  name.setAttribute("role", "textbox");
  name.setAttribute("aria-label", "Controller name");
  name.addEventListener("focus", () => { renaming = true; });
  name.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); name.blur(); }
    if (e.key === "Escape") { name.textContent = card.dev.name; name.blur(); }
  });
  name.addEventListener("blur", () => {
    renaming = false;
    const n = name.textContent.trim().slice(0, 40);
    if (n && n !== card.dev.name) change("rename", { position: card.position, name: n }, `Renamed to ${n}`);
    else name.textContent = card.dev.name;
  });
  const type = el("small");
  head.append(dot, name, type);
  let shiftBtn = null;
  if (def.has_shift) {
    shiftBtn = el("button", "shiftbtn", "SHIFT");
    shiftBtn.title = "Latch Shift: the controller and the screen work as if Shift were held";
    shiftBtn.onclick = () => change("shift-latch", { position: card.position, on: !card.dev.shift_latched }, null);
    head.appendChild(shiftBtn);
  }
  const edit = el("button", "iconbtn");
  edit.appendChild(icon("pencil"));
  edit.onclick = () => {
    if (editing.has(card.position)) editing.delete(card.position); else editing.add(card.position);
    store.set("rt-editing", [...editing]);
    if (editing.has(card.position)) { releaseAll(); toast("Click a control to change what it does"); }
    else emit("edit-close");
    update(card);
  };
  const lock = el("button", "iconbtn");
  lock.onclick = () => {
    locks[card.position] = !locks[card.position];
    if (locks[card.position]) releaseAll();
    store.set("rt-device-locks", locks);
    update(card);
  };
  head.append(edit, lock);
  card.updaters.push((dev, st) => {
    dot.className = "dot " + (st.connected ? "ok" : "bad");
    if (!renaming || document.activeElement !== name) name.textContent = dev.name;
    type.textContent = `${def.name}${st.connected ? "" : " · not connected"}`;
    if (shiftBtn) {
      shiftBtn.classList.toggle("latched", !!dev.shift_latched);
      shiftBtn.classList.toggle("held", !dev.shift_latched && !!dev.shift_held);
      shiftBtn.setAttribute("aria-pressed", String(!!dev.shift_latched));
    }
    const ed = editing.has(card.position);
    edit.classList.toggle("editon", ed);
    edit.title = ed ? "Editing: click a control to change it. Click here to finish." : "Change what this controller's controls do";
    edit.setAttribute("aria-pressed", String(ed));
    lock.replaceChildren(icon(locks[card.position] ? "lockShut" : "lockOpen"));
    lock.classList.toggle("on", !!locks[card.position]);
    lock.title = locks[card.position] ? "On-screen controls locked. Click to unlock." : "Lock this controller's on-screen controls";
    lock.setAttribute("aria-label", locks[card.position] ? `Unlock ${dev.name}` : `Lock ${dev.name}`);
  });
  return head;
}

function buildCell(card, item, framed) {
  const { def } = card;
  const id = item.control;
  const meta = def.controls[id] || {};
  const cell = placed(el("div", "cell" + (item.size === "tall" ? " tall" : "") + (framed ? " framed" : "")), item);
  cell.dataset.control = id;
  const shape = item.shape;
  let visual, svg = null, cap = null, push = null;
  const size = shape === "encoder" ? 32 : 30;
  if (shape === "knob") { svg = newDial(size); visual = svg; }
  else if (shape === "fader") { visual = el("div", "fader"); cap = el("i"); visual.appendChild(cap); }
  else if (shape === "encoder") { visual = el("div", "enc"); svg = newDial(size); push = el("div", "push"); visual.append(svg, push); }
  else visual = el("div", shape === "round" ? "round" + (item.size === "large" ? " large" : "") : shape === "pad" ? "pad" : "key", item.glyph || "");
  const lbl = el("div", "lbl");
  const pick = el("span", "pick");
  pick.hidden = true;
  cell.append(visual, lbl, pick);

  let drawn = null;
  const redraw = (value, hw) => {
    const key = `${value}|${hw}`;
    if (key === drawn) return;
    drawn = key;
    if (shape === "knob" || shape === "encoder") dial(svg, shape === "encoder" ? null : value, hw, size);
    if (cap) cap.style.top = `${Math.round((1 - (value != null ? value : 0) / 127) * 77)}px`;
  };

  // In edit mode a click opens the editor: capture it before the control's own handlers see it.
  cell.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || !editing.has(card.position)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const onPush = item.push && e.target.closest(".push");
    emit("edit", { position: card.position, control: onPush ? item.push : id });
  }, true);
  if (meta.kind === "button") { cell.classList.add("usable"); pressable(cell, card, id); }
  else if (meta.kind === "knob" || meta.kind === "fader") { cell.classList.add("usable", "value"); draggable(cell, card, id, shape, redraw); }
  else if (meta.kind === "encoder") {
    cell.classList.add("usable", "turn");
    turnable(cell, card, id);
    if (item.push) { push.style.cursor = "pointer"; pressable(push, card, item.push); }
  }

  card.updaters.push((dev, st) => {
    const { half, base } = halfOf(dev, id);
    const c = half ? half.controls[base] : null;
    const p = item.push ? halfOf(dev, item.push) : null;
    const pc = p && p.half ? p.half.controls[p.base] : null;
    cell._c = c;
    const shifted = shiftOn(dev);
    let [text, none] = labelFor(c, shifted);
    if (item.push) {
      const [ptext, pnone] = labelFor(pc, shifted);
      text = none && pnone ? text : `${none ? "—" : text} · ${pnone ? "—" : ptext}`;
      none = none && pnone;
    }
    if (lbl.textContent !== text) lbl.textContent = text;
    lbl.classList.toggle("none", none);
    cell.classList.toggle("unbound", !c || !c.label);
    if (half && (half.deck || half.decks)) cell.style.setProperty("--deck", DECK_VAR(half.deck || half.decks[0]));
    const ledSource = item.push ? pc : c;
    cell.classList.toggle("blink", !!ledSource && ledSource.led === "blink");
    cell.classList.toggle("on", !!ledSource && !!ledSource.led && ledSource.led !== "blink");
    cell.classList.toggle("down", !!(c && c.down));
    cell.classList.toggle("pushed", !!(pc && pc.down));
    cell.classList.toggle("mine", !!((c && c.mine) || (pc && pc.mine)));
    cell.classList.toggle("live", usable(card));
    cell.classList.toggle("selected", !!(app.editTarget && app.editTarget.position === card.position
      && (app.editTarget.control === id || app.editTarget.control === item.push)));
    if (c && c.pickup != null && c.value != null && c.value !== c.pickup) {
      pick.hidden = false;
      pick.textContent = c.pickup > c.value ? "▲▲" : "▼▼";
      pick.title = `Knob pickup: turn ${c.pickup > c.value ? "up" : "down"} to ${c.pickup} to take over`;
    } else pick.hidden = true;
    if (!cell.dataset.dragging && (svg || cap))
      redraw(c ? (c.sent != null ? c.sent : c.value) : null, c && c.pickup != null ? c.value : null);
    const tip = [meta.name, c && c.label && c.label !== text ? c.label : null, c && c.detail,
                 c && c.shift ? `Shift: ${c.shift}` : null, c && c.alt ? `Sync: ${c.alt}` : null,
                 item.push ? `Push: ${pc && pc.label ? pc.label : "unmapped"}` : null,
                 "Right-click to change"].filter(Boolean).join("\n");
    if (cell.title !== tip) cell.title = tip;
  });
  return cell;
}

function buildRole(card, item) {
  switch (item.role) {
    case "deck": return buildDeckHead(card, item);
    case "row": {
      const f = placed(el("div", "rowframe"), item);
      const span = el("span");
      f.appendChild(span);
      card.updaters.push((dev) => {
        const half = dev.halves.find((h) => h.half === item.half);
        const title = half && half.rows ? half.rows[item.index - 1] || "" : "";
        if (span.textContent !== title) span.textContent = title;
        span.hidden = !title;
      });
      return f;
    }
    case "shift": {
      const cell = placed(el("div", "cell inert"), item);
      cell.append(el("div", "key", "SHIFT"), el("div", "lbl none", ""));
      cell.title = item.note || "Shift sends nothing in MIDI mode";
      return cell;
    }
    case "display": {
      const cell = placed(el("div", "cell inert"), item);
      cell.append(el("div", "display7", "--"), el("div", "lbl none", ""));
      cell.title = item.note || "Display";
      return cell;
    }
  }
  return el("div");
}

function buildDeckHead(card, item) {
  const { dev } = card;
  const half0 = item.half ? dev.halves.find((h) => h.half === item.half) : dev.halves[0];
  const pages = dev.pages.length && half0 && half0.half;
  const box = placed(el("div", "deckhead" + (pages ? "" : " compact")), item);
  const line = el("div", "line1");
  let select = null, slotSelects = [];
  const fixed = el("span", "deck-fixed");
  if (dev.reassignable && half0 && half0.half) {
    select = el("select", "deck-select");
    select.setAttribute("aria-label", `${dev.name} deck`);
    for (const d of [1, 2, 3, 4]) select.appendChild(new Option(`Deck ${d}`, d));
    select.onchange = () => change("assign", { position: card.position, half: item.half, deck: Number(select.value) }, `Deck ${select.value}`);
    line.appendChild(select);
  } else if (dev.reassignable && half0 && (half0.slots || []).length) {
    // A controller without halves: one dropdown per deck it drives ("Decks 1 · 3"), each moved on its own.
    const many = half0.slots.length > 1;
    line.appendChild(el("span", "deck-fixed", many ? "Decks" : ""));
    slotSelects = half0.slots.map((s, i) => {
      const sel = el("select", "deck-select");
      sel.setAttribute("aria-label", `${dev.name} ${s.label}`);
      sel.title = s.label;
      for (const d of [1, 2, 3, 4]) sel.appendChild(new Option(many ? String(d) : `Deck ${d}`, d));
      sel.onchange = () => change("assign", { position: card.position, slot: i, deck: Number(sel.value) }, `${s.label}: deck ${sel.value}`);
      if (i) line.appendChild(el("span", "deck-sep", "·"));
      line.appendChild(sel);
      return sel;
    });
  } else line.appendChild(fixed);
  const fx = el("span", "fxchip"), badge = el("span", "badge");
  line.append(fx, badge);
  box.appendChild(line);
  const tabs = el("div", "ptabs");
  tabs.setAttribute("role", "tablist");
  tabs.addEventListener("wheel", (e) => {         // the wheel scrolls the page tabs sideways
    if (tabs.scrollWidth <= tabs.clientWidth) return;
    e.preventDefault();
    tabs.scrollLeft += e.deltaY || e.deltaX;
  }, { passive: false });
  if (pages) box.appendChild(tabs);
  let tabsKey = "";
  card.updaters.push((d) => {
    const half = item.half ? d.halves.find((h) => h.half === item.half) : d.halves[0];
    if (!half) return;
    box.style.setProperty("--deck", DECK_VAR(half.deck || (half.decks && half.decks[0])));
    if (select) { if (document.activeElement !== select) select.value = String(half.deck); }
    else if (slotSelects.length) slotSelects.forEach((sel, i) => {
      if (document.activeElement !== sel && half.slots[i]) {
        sel.value = String(half.slots[i].deck);
        sel.style.setProperty("--deck", DECK_VAR(half.slots[i].deck));
      }
    });
    else fixed.textContent = half.decks ? `Decks ${half.decks.join(" · ")}` : `Deck ${half.deck}`;
    fx.textContent = `FX ${half.fx}`;
    const b = [half.modes.browser ? "Browser" : null, half.modes.bank ? "Cues E–H" : null].filter(Boolean).join(" · ");
    if (badge.textContent !== b) badge.textContent = b;
    if (!pages) return;
    const key = JSON.stringify([d.pages, d.page_short, d.page_names]);
    if (key !== tabsKey) {
      tabsKey = key;
      tabs.replaceChildren(...d.pages.map((p) => {
        const t = el("button", "", (d.page_short || {})[p] || d.page_names[p] || p);
        t.dataset.page = p;
        t.setAttribute("role", "tab");
        t.title = `${d.page_names[p] || p} page (Shift + FX Assign on the hardware)`;
        t.onclick = () => change("page", { position: card.position, half: item.half, page: p }, null);
        return t;
      }));
    }
    for (const t of tabs.children) {
      const cur = t.dataset.page === half.modes.page;
      t.classList.toggle("current", cur);
      t.setAttribute("aria-selected", String(cur));
      if (cur) {                                  // many pages: keep the current one in view
        const left = t.offsetLeft, right = left + t.offsetWidth;
        if (left < tabs.scrollLeft) tabs.scrollLeft = left - 6;
        else if (right > tabs.scrollLeft + tabs.clientWidth) tabs.scrollLeft = right - tabs.clientWidth + 6;
      }
    }
  });
  return box;
}

// While a modifier is held on a half (Sync, FX Assign...), frame that half in orange and name the layer.
function buildHalfFrame(card, halfName) {
  const { def } = card;
  let c0 = 99, c1 = 0, r0 = 99, r1 = 0;
  for (const item of def.layout.items) {
    const id = item.control || "";
    if (!(id.startsWith(`${halfName}.`) || item.half === halfName)) continue;
    c0 = Math.min(c0, item.c); c1 = Math.max(c1, item.c + (item.w || 1));
    r0 = Math.min(r0, item.r); r1 = Math.max(r1, item.r + (item.h || 1));
  }
  const f = el("div", "halfframe");
  f.style.gridColumn = `${c0} / ${c1}`;
  f.style.gridRow = `${r0} / ${r1}`;
  const span = el("span");
  f.appendChild(span);
  f.hidden = true;
  card.updaters.push((dev) => {
    const h = dev.halves.find((x) => x.half === halfName);
    const layer = h && h.layer;
    f.hidden = !layer;
    if (layer) span.textContent = `${layer}${shiftOn(dev) ? " + Shift" : ""} held`;
  });
  return f;
}

// ---- updating ------------------------------------------------------------------------------------------------
function update(card) {
  const conn = (app.status && app.status.devices) || {};
  const st = { connected: conn[card.position] ? conn[card.position].connected : true };
  const dev = card.dev;
  card.node.classList.toggle("offline", !st.connected);
  card.node.classList.toggle("shifted", shiftOn(dev));
  card.node.classList.toggle("editing", editing.has(card.position));
  for (const fn of card.updaters) fn(dev, st);
}

export function renderControllers() {
  const devices = app.view ? app.view.devices : [];
  $("no-view").style.display = devices.length ? "none" : "";
  if (!devices.length) {                      // starting, or a first run with nothing added yet
    const ready = !!(app.view && app.status && app.status.state === "running");
    $("no-view-title").textContent = ready ? "No controllers yet" : "Starting";
    $("no-view-text").textContent = ready ? "Plug in a controller, then add it under Settings › MIDI devices."
      : "RekordTrakt is connecting to your controllers.";
    $("no-view-add").hidden = !ready;
  }
  const order = [];
  const seen = new Set();
  for (const dev of devices) {
    const def = app.defs[dev.type];
    if (!def) { loadDefinitions(); continue; }
    let card = cards.get(dev.position);
    const layoutKey = JSON.stringify([dev.type, dev.halves.map((h) => h.half), dev.pages.length > 0]);
    if (!card || card.layoutKey !== layoutKey) {
      card = buildCard(dev, def);
      card.layoutKey = layoutKey;
      cards.set(dev.position, card);
    }
    card.dev = dev;
    update(card);
    order.push(card.node);
    seen.add(dev.position);
  }
  for (const p of [...cards.keys()]) if (!seen.has(p)) cards.delete(p);
  const host = $("rig");
  const current = [...host.children];
  if (current.length !== order.length || current.some((n, i) => n !== order[i])) host.replaceChildren(...order);
}

let loading = null;
export function loadDefinitions() {
  if (loading) return loading;
  loading = get("/api/definitions").then((d) => { app.defs = d; cards.clear(); renderControllers(); })
    .catch(() => {}).finally(() => { loading = null; });
  return loading;
}
