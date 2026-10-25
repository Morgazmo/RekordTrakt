// The Settings tab: a sidebar of controllers and this PC, one page at a time, cards of rows. Every row is built by
// row(): what it is on the left, its control in a fixed column on the right (app.css explains the style system).
import { $, app, ask, change, el, emit, get, icon, post, toast } from "./core.js";
import { bridgeNeedsAttention, openRekordboxDialog } from "./rekordbox.js";

let renderedKey = "", chosen = null, shown = null;      // chosen: your pick; shown: the page drawn

export function loadMidiDevices() {
  get("/api/midi-devices").then((d) => { app.midiDevices = d; renderedKey = ""; renderSettings(); }).catch(() => {});
}
export function showSettingsPage(id) {
  chosen = id;
  if (id === "midi") loadMidiDevices();
  renderedKey = "";
  renderSettings();
}

// ---- building blocks ----------------------------------------------------------------------------------------
function card(title, ...children) {
  const c = el("div", "card");
  c.appendChild(el("h3", null, title));
  c.append(...children.filter(Boolean));
  return c;
}
function row(title, help, ...controls) {
  const r = el("div", "item");
  const txt = el("div", "txt");
  txt.appendChild(el("b", null, title));
  if (help) txt.appendChild(el("small", null, help));
  r.appendChild(txt);
  const trail = el("div", "trail");
  trail.append(...controls.filter(Boolean));
  r.appendChild(trail);
  return r;
}
const tag = (text, cls = "") => el("span", `tag ${cls}`.trim(), text);
function switchInput(checked, disabled, onchange, name) {
  const label = el("label", "switch");
  const input = el("input");
  input.type = "checkbox"; input.checked = checked; input.disabled = disabled;
  input.setAttribute("role", "switch");
  if (name) input.setAttribute("aria-label", name);
  input.onchange = () => onchange(input.checked);
  label.append(input, el("span"));
  return label;
}
function select(values, current, disabled, onchange, name, cls) {
  const s = el("select", cls);
  if (name) s.setAttribute("aria-label", name);
  for (const [v, text] of values) {
    const o = new Option(text, JSON.stringify(v));
    if (JSON.stringify(v) === JSON.stringify(current)) o.selected = true;
    s.appendChild(o);
  }
  s.disabled = disabled;
  s.onchange = () => onchange(JSON.parse(s.value));
  return s;
}
function button(text, cls, onclick) {
  const b = el("button", cls || "", text);
  b.onclick = onclick;
  return b;
}
function iconButton(name, label, onclick) {
  const b = el("button", "iconbtn");
  b.appendChild(icon(name));
  b.title = label;
  b.setAttribute("aria-label", label);
  b.onclick = onclick;
  return b;
}
function sideButton(title, small, dotCls, id) {
  const b = el("button");
  b.setAttribute("aria-current", String(shown === id));
  const t = el("span", "t");
  t.append(el("b", null, title), el("small", null, small));
  b.append(el("span", "dot " + dotCls), t);
  b.onclick = () => showSettingsPage(id);
  return b;
}
function title(main, sub) {
  const t = el("div", "page-title");
  t.append(el("h2", null, main));
  if (sub) t.appendChild(el("div", null, sub));
  return t;
}
function columns(left, right) {
  const cols = el("div", "cols"), a = el("div"), b = el("div");
  a.append(...left);
  b.append(...right);
  cols.append(a, b);
  return cols;
}

// ---- the page ---------------------------------------------------------------------------------------------------
export function renderSettings() {
  const s = app.status;
  if (!s) return;
  const running = s.state === "running" && app.view && app.view.devices.length;
  const devices = running ? app.view.devices : [];
  const key = JSON.stringify([running, chosen, s.devices || null, app.midiDevices, s.bridge_mapping || null,
    s.rekordbox_running, s.rekordbox_version, s.app && s.app.start_at_login, devices.map((d) => [d.position, d.name,
      d.decks, d.fx_units, d.options, d.pages, d.all_pages, d.page_names, d.mine_count, d.page_bindings])]);
  const busy = dragging || document.activeElement?.closest("#settings select, #settings input[type=text]");
  if (key === renderedKey || busy) return;
  renderedKey = key;
  // The page you chose; until you choose, the first controller (once they're known: not a fallback that sticks).
  const pcPages = ["midi", "rekordbox", "app"];
  if (!devices.some((d) => d.position === chosen) && !pcPages.includes(chosen)) chosen = null;
  const empty = s.state === "running" && app.view && !app.view.devices.length;     // a first run: nothing added
  shown = chosen || (devices.length ? devices[0].position : empty ? "midi" : "rekordbox");
  const conn = s.devices || {};
  const side = el("div", "side");
  side.appendChild(el("h4", null, "Controllers"));
  for (const d of devices) {
    const ok = conn[d.position] ? conn[d.position].connected : true;
    side.appendChild(sideButton(d.name, d.type_name + (ok ? "" : " · not connected"), ok ? "ok" : "bad", d.position));
  }
  if (empty) side.appendChild(el("p", "none", "None yet: add one under MIDI devices."));
  side.appendChild(el("h4", null, "This PC"));
  side.appendChild(sideButton("MIDI devices", "What's connected", "ok", "midi"));
  const b = s.bridge_mapping;
  side.appendChild(sideButton("Rekordbox", s.rekordbox_running && s.rekordbox_version ? `${s.rekordbox_version} running` : "MIDI mapping file",
    !b ? "" : bridgeNeedsAttention(s) ? "warn" : "ok", "rekordbox"));
  side.appendChild(sideButton("RekordTrakt", "Start with Windows", "ok", "app"));
  const main = el("div");
  if (shown === "midi") main.append(...midiPage());
  else if (shown === "rekordbox") main.append(...rekordboxPage());
  else if (shown === "app") main.append(...appPage());
  else if (devices.length) main.append(...devicePage(devices.find((d) => d.position === shown)));
  else main.appendChild(card("Controllers", el("p", "note", "Controller settings appear once RekordTrakt is running.")));
  $("settings").replaceChildren(side, main);
  if (refocus) {
    const handle = document.querySelector(`#settings .item.page[data-page="${CSS.escape(refocus)}"] .handle`);
    if (handle) { handle.focus(); refocus = null; }
  }
}

// ---- a controller --------------------------------------------------------------------------------------------
function devicePage(dev) {
  const name = el("input");
  name.type = "text"; name.value = dev.name; name.maxLength = 40;
  name.setAttribute("aria-label", "Name");
  name.onchange = () => { if (name.value.trim()) change("rename", { position: dev.position, name: name.value.trim() }, "Renamed"); };
  const general = [row("Name", null, name)];
  if (dev.halves.length > 1) {
    dev.halves.forEach((h, i) => {
      const side = h.half === "L" ? "Left deck" : "Right deck";
      general.push(row(side, "Its deck and FX unit.",
        select([1, 2, 3, 4].map((d) => [d, `Deck ${d}`]), dev.decks[i], !dev.reassignable,
          (deck) => change("assign", { position: dev.position, half: h.half, deck }, `Deck ${deck}`), side, "pair"),
        select([1, 2].map((u) => [u, `FX unit ${u}`]), dev.fx_units[i], !dev.reassignable,
          (fx) => change("assign", { position: dev.position, half: h.half, fx }, `FX unit ${fx}`), `${side} FX unit`, "pair")));
    });
  } else {
    general.push(row("Decks", null, tag(`Decks ${dev.decks.join(" and ")}`)), row("FX unit", null, tag(`FX unit ${dev.fx_units[0]}`)));
  }
  const left = [card("General", ...general)];
  if (dev.all_pages.length) left.push(pagesCard(dev));
  const options = dev.options || {};
  const opts = Object.entries(dev.option_info || {})
    .filter(([k, info]) => k !== "pages" && (!info.when || (options[info.when[0]] ?? null) === info.when[1]))
    .map(([k, info]) => row(info.title, info.help, select(info.values, options[k], false,
      (value) => change("option", { position: dev.position, key: k, value }, `${info.title}: saved`), info.title)));
  const right = [card("Behaviour", ...(opts.length ? opts : [el("p", "note", "Nothing to set for this preset.")])), mappingCard(dev)];
  return [title(dev.name, dev.type_name), columns(left, right)];
}

// FX-section pages: drag to reorder, switch on or off. A blank, switched-off "Custom" row waits at the end:
// switching it on makes it a page of your own (and another blank one appears).
function pagesCard(dev) {
  const custom = new Set(dev.custom_pages || []), enabled = new Set(dev.pages);
  const order = [...dev.all_pages];
  const save = (pages, ord) => change("pages", { position: dev.position, pages, order: ord }, null);
  const list = el("div", "rows pagelist");
  for (const pg of order) {
    const on = enabled.has(pg), label = dev.page_names[pg] || pg;
    const r = row(label, null);
    r.classList.add("page");
    if (!on) r.classList.add("off");
    r.dataset.page = pg;
    const handle = el("button", "handle");
    handle.appendChild(icon("grip"));
    handle.setAttribute("aria-label", `Move ${label}: drag, or use the arrow keys`);
    handle.title = "Drag to change the order";
    const sw = switchInput(on, on && enabled.size === 1, (checked) =>
      save(order.filter((p) => p === pg ? checked : enabled.has(p)), order), `${label} page`);
    r.prepend(handle, sw);
    if (custom.has(pg)) {
      const trail = r.querySelector(".trail");
      trail.append(
        iconButton("pencil", `Rename ${label}`, async () => {
          const n = await ask({ title: "Rename page", value: label, ok: "Rename" });
          if (n && n !== label) change("page-rename", { position: dev.position, page: pg, name: n }, "Renamed");
        }),
        iconButton("trash", `Delete ${label}`, async () => {
          const used = (dev.page_bindings || {})[pg] || 0;
          if (used && !(await ask({ title: `Delete “${label}”?`, ok: "Delete",
            text: `${used} control${used === 1 ? " is" : "s are"} set on it, and ${used === 1 ? "goes" : "go"} with it.` }))) return;
          change("page-remove", { position: dev.position, page: pg }, `${label} deleted`);
        }));
    }
    list.appendChild(r);
  }
  const names = new Set([...custom].map((p) => dev.page_names[p]));
  let next = "Custom", n = 2;
  while (names.has(next)) next = `Custom ${n++}`;
  const blank = row(next, null);
  blank.classList.add("page", "off", "placeholder");
  const none = el("span", "handle none");
  blank.prepend(none, switchInput(false, false, async (checked) => {
    if (checked && await change("page-add", { position: dev.position, name: next }, `${next} added: right-click its controls to fill it`)) renderedKey = "";
  }, `${next} page`));
  list.appendChild(blank);
  sortable(list, (ord) => save(ord.filter((p) => enabled.has(p)), ord));
  return card("FX-section pages",
    el("p", "note", "Shift + FX Assign 1 / 2 steps through the pages that are on, in this order."), list);
}

// Reordering rows by their handle: with the pointer, or the arrow keys on a focused handle. The pointer is followed
// on the window, not captured by the handle: moving the row in the page would drop a capture mid-drag.
let dragging = false, refocus = null;
function sortable(list, onDone) {
  const rows = () => [...list.querySelectorAll(".item.page[data-page]")];
  const end = list.querySelector(".placeholder");
  const result = (before) => { const after = rows().map((r) => r.dataset.page); if (after.join() !== before.join()) onDone(after); };
  list.addEventListener("pointerdown", (e) => {
    const handle = e.target.closest("button.handle");
    if (!handle || e.button !== 0 || dragging) return;
    e.preventDefault();
    const dragged = handle.closest(".item"), before = rows().map((r) => r.dataset.page);
    dragging = true;
    dragged.classList.add("dragging");
    const move = (m) => {
      const target = rows().find((r) => r !== dragged && m.clientY < r.getBoundingClientRect().top + r.offsetHeight / 2);
      if ((target || end) !== dragged.nextSibling) list.insertBefore(dragged, target || end);
    };
    const finish = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
      window.removeEventListener("blur", finish);
      dragged.classList.remove("dragging");
      dragging = false;
      result(before);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
    window.addEventListener("blur", finish);
  });
  list.addEventListener("keydown", (e) => {
    const handle = e.target.closest("button.handle");
    if (!handle || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    e.preventDefault();
    const r = handle.closest(".item"), all = rows(), i = all.indexOf(r), before = all.map((x) => x.dataset.page);
    const j = e.key === "ArrowUp" ? i - 1 : i + 1;
    if (j < 0 || j >= all.length) return;
    list.insertBefore(r, e.key === "ArrowUp" ? all[j] : all[j].nextSibling);
    handle.focus();
    refocus = r.dataset.page;                    // the list is drawn again once saved: keep the keyboard on this row
    result(before);
  });
}

function mappingCard(dev) {
  const count = dev.mine_count || 0;
  const exportBtn = button("Export", "", async () => {
    try {
      const data = await post("mapping-export", { position: dev.position });
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = el("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${dev.name.replace(/[^\w -]+/g, "").trim() || dev.position}.rekordtrakt.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (e) { toast(e.message, true); }
  });
  const file = el("input");
  file.type = "file"; file.accept = ".json,application/json"; file.hidden = true;
  file.onchange = async () => {
    const f = file.files[0];
    file.value = "";
    if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      if (await ask({ title: `Import onto ${dev.name}?`, text: "It replaces this controller's own changes and pages (the preset stays underneath).", ok: "Import" }))
        change("mapping-import", { position: dev.position, data }, "Imported");
    } catch { toast("That file isn't a RekordTrakt mapping", true); }
  };
  const resetBtn = button("Reset", "", async () => {
    if (await ask({ title: `Reset ${dev.name} to its preset?`, text: "Your changed controls and your own pages are removed.", ok: "Reset" }))
      change("mapping-import", { position: dev.position, data: { rekordtrakt_mapping: 1, device_type: dev.type, mapping: {} } }, "Back to the preset");
  });
  resetBtn.disabled = !count && !(dev.custom_pages || []).length;
  return card("Your mapping",
    row(count ? `${count} control${count > 1 ? "s" : ""} changed` : "No changes yet",
      "Right-click a control on the Controllers tab, or choose Edit and click it, to change what it does.",
      button("Edit", "", () => emit("edit-mode", dev.position))),
    row("Share", "A file with your changes and pages, to keep or use on another PC.", exportBtn, button("Import", "", () => file.click()), file),
    row("Start over", "Back to the preset: your changes and your own pages go.", resetBtn));
}

// ---- this PC ----------------------------------------------------------------------------------------------------
function rekordboxPage() {
  const s = app.status, b = s.bridge_mapping;
  const version = s.rekordbox_running ? (s.rekordbox_version ? `Rekordbox ${s.rekordbox_version}` : "Running") : "Not running";
  const runningCard = card("Rekordbox",
    row("Running now", "Detected when it starts.", tag(version, s.rekordbox_running ? "ok" : "")),
    row("Mapping built for", b ? `RekordTrakt follows the Rekordbox you run, so there's nothing to choose. ${b.target === 7
      ? "Rekordbox 7 adds its own functions (Bass stem, Drum Swap and more) but locks MIDI mapping without a paid plan."
      : "Rekordbox 7 locks MIDI mapping without a paid plan."}` : null, b ? tag(`Rekordbox ${b.target}`) : null));
  if (!b) return [title("Rekordbox"), columns([runningCard], [card("MIDI mapping file", el("p", "note", "Shown once RekordTrakt is running."))])];
  const names = { current: ["Up to date", "ok"], update: ["Update ready", "info"], required: ["Update needed", "warn"], missing: ["Not installed", "bad"] };
  const text = {
    current: `Rekordbox has RekordTrakt's mapping file: ${b.entries} entries, every function for all four decks.`,
    update: "Everything you use works. The update adds more of Rekordbox, so later changes won't need another.",
    required: `Some functions this setup uses do nothing yet: ${b.missing.slice(0, 5).join(", ")}${b.missing.length > 5 ? ` and ${b.missing.length - 5} more` : ""}.`,
    missing: "Rekordbox doesn't have it yet, so it can't hear your controllers.",
  }[b.state];
  const [stateName, stateCls] = names[b.state] || [b.state, ""];
  const rows = [row("MIDI mapping file", text, tag(stateName, stateCls))];
  if ((b.direct || []).length)
    rows.push(row("Controllers' own mappings",
      `${b.direct.map((p) => ((s.devices || {})[p] || {}).name || p).join(", ")}: presses would fire twice. Installing turns these off.`,
      tag("On", "warn")));
  if (bridgeNeedsAttention(s))
    rows.push(row(b.state === "missing" ? "Install the mapping file" : "Update the mapping file", "Rekordbox closes for a moment; backups are kept.",
      button(b.state === "missing" ? "Install" : "Update", "", openRekordboxDialog)));
  else
    rows.push(row("Reinstall the mapping file", "Only if your controllers stop working in Rekordbox. It closes for a moment; backups are kept.",
      button("Reinstall", "", openRekordboxDialog)));
  return [title("Rekordbox"), columns([runningCard], [card("MIDI mapping file", ...rows)])];
}

function midiPage() {
  const names = { added: ["In use", "ok"], supported: ["Supported", "info"], rekordbox: ["Rekordbox", ""],
                  unknown: ["Not set up", ""], bridge: ["Bridge", ""] };
  const order = ["added", "supported", "rekordbox", "unknown", "bridge"];   // what you use first, the plumbing last
  const list = [...(app.midiDevices || [])].sort((x, y) => order.indexOf(x.status) - order.indexOf(y.status))
    .map((d) => {
      const [text, cls] = names[d.status] || [d.status, ""];
      return row(d.port, d.text, tag(text, cls), ...(midiAction(d) || [el("span", "btn-slot")]));
    });
  const how = card("Importing a mapping file",
    el("p", "note", "Import reads a controller mapping in the .midi.xml format (one file per controller) and makes it a controller here, with each of its buttons, knobs and LEDs. Controls the file links straight to a function (play, cue, hot cues, loops, EQ and more) do the same in Rekordbox. Controls it drives with its own scripts aren't imported: they're listed so you can set them in the mapping editor. Nothing in the file is run."));
  return [title("MIDI devices", "Every MIDI input on this PC"),
          columns([card("Connected now", ...(list.length ? list : [el("p", "note", "Looking")]))], [how])];
}

// The row's button (and the file picker it opens), or null for none.
function midiAction(d) {
  const after = (text) => { toast(text); loadMidiDevices(); setTimeout(() => emit("definitions"), 1500); };
  if (d.status === "supported")
    return [button("Add", "", async () => {
      try { await post("device-add", { port: d.port, type: d.type }); after(`${d.port} added`); } catch (e) { toast(e.message, true); }
    })];
  if (d.status === "added")
    return [button("Remove", "", async () => {
      if (!(await ask({ title: `Remove ${d.text}?`, text: "RekordTrakt stops using it. Its mapping goes with it.", ok: "Remove" }))) return;
      try { await post("device-remove", { position: d.position }); after(`${d.text} removed`); } catch (e) { toast(e.message, true); }
    })];
  if (d.status === "unknown") {
    const file = el("input");
    file.type = "file"; file.accept = ".xml,.midi.xml"; file.hidden = true;
    file.onchange = async () => {
      const f = file.files[0];
      file.value = "";
      if (!f) return;
      try {
        const r = await post("device-import", { xml: await f.text(), port: d.port });
        after(`${r.name}: ${r.controls} controls, ${r.mapped} set up${r.scripted.length ? `, ${r.scripted.length} to set in the editor` : ""}`);
      } catch (e) { toast(e.message, true); }
    };
    return [button("Import", "", () => file.click()), file];
  }
  return null;
}

function appPage() {
  const s = app.status, a = s.app || {};
  const login = switchInput(!!a.start_at_login, false, (on) => change("start-at-login", { on },
    on ? "RekordTrakt starts with Windows" : "RekordTrakt won't start with Windows").then(() => emit("refresh")), "Start with Windows");
  return [title("RekordTrakt", a.version ? `Version ${a.version}` : null), columns([card("RekordTrakt",
    row("Start with Windows", "Starts in the notification area when you sign in.", login),
    row("Log folder", "What RekordTrakt did, for troubleshooting.", button("Open", "", () => post("open-log-folder").catch((e) => toast(e.message, true)))),
    row("Source and issues", "RekordTrakt is free and open source (GPL-3.0).", button("GitHub", "", () => post("open-project").catch(() => toast("Couldn't open the browser", true)))))], [])];
}
