// The mapping editor: what one control does, per layer (Normal, Shift, Sync held...) and FX-section page.
// Right-click a control (or click it in edit mode) to open it. Saving applies at once: Rekordbox already has every
// function, so nothing needs restarting.
import { $, app, el, emit, get, icon, on, post, toast } from "./core.js";

let target = null;        // {position, control}
let info = null;          // from the server: kind, page, layers [{layer, label, preset, mine}]
let layer = "base";
let draft = null;         // {do, items: [...]}
let pickerFor = null;     // {index, field} while the function list is open
let pickerQuery = "";
let busy = false;

const KIND_NAMES = { button: "button", knob: "knob", fader: "fader", encoder: "encoder" };

async function functions() {
  if (!app.functions) app.functions = await get("/api/functions");
  return app.functions.functions;
}
function fnInfo(name) { return (app.functions ? app.functions.functions : []).find((f) => f.name === name); }

export function setupEditor() {
  $("ed-close").onclick = close;
  $("ed-cancel").onclick = close;
  $("ed-save").onclick = save;
  $("ed-reset").onclick = () => saveAction(null);
  on("edit", ({ position, control }) => open(position, control));
  on("edit-close", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && target && !document.querySelector("dialog[open]")) close(); });
}

export async function open(position, control, page) {
  target = { position, control };
  app.editTarget = target;
  emit("render");
  $("editor").hidden = false;
  try {
    await functions();
    info = await post("control-info", { position, control, page });
  } catch (e) { toast(e.message, true); return close(); }
  if (!info.layers.some((l) => l.layer === layer)) layer = info.layers[0].layer;
  startDraft();
  render();
}

function close() {
  target = null; info = null; pickerFor = null;
  app.editTarget = null;
  $("editor").hidden = true;
  emit("render");
}

function current() { return info.layers.find((l) => l.layer === layer); }

function startDraft() {
  const mine = current().mine;
  pickerFor = null;
  $("ed-err").textContent = "";
  if (!mine) { draft = { do: defaultDo(), items: [blankItem()] }; return; }
  const d = { do: mine.do, items: [] };
  if (mine.do === "function" || mine.do === "value") d.items = [{ ...mine }];
  else if (mine.do === "functions") d.items = (mine.items || []).map((x) => ({ ...x }));
  else if (mine.do === "sequence") d.items = (mine.steps || []).map((x) => ({ ...x }));
  if (!d.items.length) d.items = [blankItem()];
  draft = d;
}
function defaultDo() { return "function"; }
function blankItem() {
  return { function: null, deck: info && info.half !== undefined ? defaultDeck() : "deck" };
}
function defaultDeck() { return info.half ? "deck" : ((info.slots || [])[0] || ["d1"])[0]; }

// What a control of this kind can take, for each part of an action.
function allowed(kinds) {
  const k = info.kind;
  if (kinds === "main") {
    if (draft.do === "value") return ["value"];
    if (k === "button") return ["button"];
    if (k === "encoder") return draft.do === "functions" ? ["turn"] : ["turn", "button"];
    return ["value"];
  }
  return ["button"];                                   // an encoder's anticlockwise step
}

function deckOptions(scope) {
  if (scope !== "deck") return null;
  const out = info.half ? [["deck", `This deck (${info.deck})`]]
    : (info.slots || []).map(([key, label, deck]) => [key, `${label} (${deck})`]);    // follow the controller's decks
  for (const n of [1, 2, 3, 4]) out.push([`d${n}`, `Deck ${n}`]);
  return out;
}

// ---- drawing ---------------------------------------------------------------------------------------------------
function render() {
  if (!info) return;
  const dev = app.view && app.view.devices.find((d) => d.position === target.position);
  const def = dev && app.defs[dev.type];
  const name = (def && def.controls[target.control] && def.controls[target.control].name) || target.control;
  $("ed-title").textContent = name;
  $("ed-sub").textContent = `${dev ? dev.name : target.position} · ${KIND_NAMES[info.kind] || info.kind}`;
  const body = $("ed-body");
  body.replaceChildren();

  const layers = el("div", "layers");
  for (const l of info.layers) {
    const b = el("button", l.mine ? "has" : "", l.label);
    b.setAttribute("aria-pressed", String(l.layer === layer));
    b.onclick = () => { layer = l.layer; startDraft(); render(); };
    layers.appendChild(b);
  }
  body.appendChild(layers);

  if (info.page_bound && dev) {
    const row = el("div", "line");
    row.style.display = "flex"; row.style.alignItems = "center"; row.style.gap = "8px";
    row.appendChild(el("span", "hint", "On the page"));
    const s = el("select");
    for (const p of dev.all_pages) s.appendChild(new Option(dev.page_names[p] || p, p, false, p === info.page));
    s.onchange = () => open(target.position, target.control, s.value);
    row.appendChild(s);
    body.appendChild(row);
  }

  const l = current();
  const now = el("div", "now");
  const t = el("div", "t");
  if (l.mine) { t.append(el("b", null, "Yours"), el("small", null, summary(l.mine))); }
  else if (l.preset) { t.append(el("b", null, l.preset.label === "—" ? "Nothing" : l.preset.label), el("small", null, l.preset.detail ? `Preset · ${l.preset.detail}` : "Preset")); }
  else { t.append(el("b", null, "Nothing"), el("small", null, "Not used on this layer")); }
  now.appendChild(t);
  body.appendChild(now);

  const kinds = el("div", "kinds");
  const choices = [["function", "One function"], ["functions", info.kind === "button" ? "Several at once" : "Several"]];
  if (info.kind === "button") choices.push(["sequence", "Sequence"], ["value", "Set a value"]);
  choices.push(["nothing", "Nothing"]);
  for (const [k, label] of choices) {
    const b = el("button", null, label);
    b.setAttribute("aria-pressed", String(draft.do === k));
    b.onclick = () => {
      if (draft.do === k) return;
      const keep = draft.items.filter((x) => x.function);
      draft = { do: k, items: k === "function" || k === "value" ? [keep[0] || blankItem()] : keep.length ? keep : [blankItem()] };
      if (k === "value") draft.items = [{ ...blankItem(), value: 0 }];
      pickerFor = null;
      render();
    };
    kinds.appendChild(b);
  }
  body.appendChild(kinds);

  if (draft.do === "nothing") body.appendChild(el("p", "hint", "This control will do nothing on this layer."));
  else {
    const rows = el("div", "rows");
    draft.items.forEach((x, i) => rows.appendChild(itemRow(x, i)));
    body.appendChild(rows);
    if (draft.do === "functions" || draft.do === "sequence") {
      const add = el("button", null, draft.do === "sequence" ? "Add a step" : "Add a function");
      add.onclick = () => { draft.items.push({ ...blankItem(), wait: draft.do === "sequence" ? 0.5 : undefined }); render(); };
      add.disabled = draft.items.length >= (draft.do === "sequence" ? 16 : 8);
      body.appendChild(add);
    }
    body.appendChild(el("p", "hint", hint()));
  }
  $("ed-reset").hidden = !l.mine;
  $("ed-save").disabled = busy;
}

function hint() {
  if (draft.do === "functions" && info.kind !== "button") return "One knob drives each function over its own range; a range from high to low turns that one the other way.";
  if (draft.do === "functions") return "They're pressed together and let go together.";
  if (draft.do === "sequence") return "One press runs the steps in order; each waits its seconds after the one before. " +
    "Letting go doesn't stop it, and pressing again starts it over. Steps still waiting are cancelled when this deck's " +
    "assignment or page changes, Bypass turns on, or this controller's mapping is edited.";
  if (draft.do === "value") return "Pressing sets the value; when let go it can go back (e.g. an EQ kill).";
  if (info.kind === "encoder") return "Choose a turn function, or a button function for each direction.";
  return "";
}

function itemRow(x, i) {
  const row = el("div", "row");
  const line = el("div", "line");
  if (draft.do === "sequence") {
    const w = el("input");
    w.type = "number"; w.min = 0; w.max = 30; w.step = 0.1; w.value = x.wait ?? (i ? 0.5 : 0);
    w.title = "Seconds after the step before";
    w.onchange = () => { x.wait = Math.max(0, Math.min(30, Number(w.value) || 0)); };
    const lab = el("label");
    lab.append(el("span", null, i ? "then after" : "after"), w, el("span", null, "s"));
    line.appendChild(lab);
  }
  line.appendChild(fnButton(x, i, "function", allowed("main")));
  const f = fnInfo(x.function);
  const decks = f && deckOptions(f.scope);
  if (decks) {
    const s = el("select");
    for (const [v, label] of decks) s.appendChild(new Option(label, v, false, v === x.deck));
    if (!decks.some(([v]) => v === x.deck)) x.deck = decks[0][0];
    s.onchange = () => { x.deck = s.value; };
    line.appendChild(s);
  }
  if (draft.items.length > 1) {
    const rm = el("button", "iconbtn");
    rm.appendChild(icon("trash"));
    rm.title = "Remove";
    rm.setAttribute("aria-label", "Remove");
    rm.onclick = () => { draft.items.splice(i, 1); pickerFor = null; render(); };
    line.appendChild(rm);
  }
  row.appendChild(line);
  if (info.kind === "encoder" && f && f.kind === "button" && draft.do === "function") {
    const l2 = el("div", "line");
    l2.appendChild(el("span", "hint", "Other way"));
    l2.appendChild(fnButton(x, i, "minus", allowed("minus")));
    row.appendChild(l2);
  }
  if (draft.do === "functions" && info.kind !== "button" && info.kind !== "encoder") {
    const l2 = el("div", "line");
    l2.append(numberField("From", x, "from", 0), numberField("to", x, "to", 127));
    row.appendChild(l2);
  }
  if (draft.do === "value") {
    const l2 = el("div", "line");
    l2.appendChild(numberField("Set to", x, "value", 0));
    const cb = el("input");
    cb.type = "checkbox"; cb.checked = x.release != null;
    const lab = el("label");
    lab.append(cb, el("span", null, "when let go:"));
    const back = numberField("", x, "release", 64);
    back.hidden = x.release == null;
    cb.onchange = () => { x.release = cb.checked ? 64 : null; render(); };
    l2.append(lab, back);
    row.appendChild(l2);
  }
  if (pickerFor && pickerFor.index === i) row.appendChild(picker(x, pickerFor.field, pickerFor.kinds));
  return row;
}

function numberField(label, x, key, dflt) {
  const lab = el("label");
  if (label) lab.appendChild(el("span", null, label));
  const n = el("input");
  n.type = "number"; n.min = 0; n.max = 127; n.value = x[key] ?? dflt;
  if (x[key] == null && key !== "release") x[key] = dflt;
  n.onchange = () => { x[key] = Math.max(0, Math.min(127, Math.round(Number(n.value) || 0))); };
  lab.appendChild(n);
  return lab;
}

function fnButton(x, i, field, kinds) {
  const f = fnInfo(x[field]);
  const b = el("button", "fn" + (f ? "" : " empty"), f ? f.label : "Choose a function");
  if (f) b.title = `${f.category} · ${f.name}`;
  b.onclick = () => {
    pickerFor = pickerFor && pickerFor.index === i && pickerFor.field === field ? null : { index: i, field, kinds };
    pickerQuery = "";
    render();
    const s = document.querySelector(".editor .picker input");
    if (s) s.focus();
  };
  return b;
}

function picker(x, field, kinds) {
  const box = el("div", "picker");
  const search = el("input");
  search.type = "search"; search.placeholder = "Search functions"; search.value = pickerQuery;
  const list = el("div", "list");
  const fill = () => {
    const q = pickerQuery.toLowerCase();
    list.replaceChildren();
    let category = null, shown = 0;
    const target = (app.status && app.status.bridge_mapping && app.status.bridge_mapping.target) || 6;
    for (const f of app.functions.functions) {
      if (!kinds.includes(f.kind) || (f.rekordbox || 6) > target) continue;     // Rekordbox 7's only when built for 7
      if (q && !`${f.label} ${f.name} ${f.category}`.toLowerCase().includes(q)) continue;
      if (f.category !== category) { category = f.category; list.appendChild(el("h5", null, category)); }
      const b = el("button");
      b.append(el("span", null, f.label));
      if (f.lights) b.appendChild(el("small", null, "lights"));
      b.onclick = () => {
        x[field] = f.name;
        if (field === "function" && f.scope === "deck" && !x.deck) x.deck = defaultDeck();
        if (field === "function" && f.scope !== "deck") x.deck = null;
        if (field === "function" && info.kind === "encoder" && f.kind === "button" && !x.minus) x.minus = guessMinus(f.name);
        pickerFor = null;
        render();
      };
      list.appendChild(b);
      if (++shown > 400) break;
    }
    if (!shown) list.appendChild(el("p", "hint", "Nothing matches."));
  };
  search.oninput = () => { pickerQuery = search.value; fill(); };
  box.append(search, list);
  fill();
  return box;
}

// Pairs for an encoder: "...Fwd" turns back with "...Prev", "...Up" with "...Down", and so on.
function guessMinus(name) {
  const pairs = [["Fwd", "Prev"], ["Up", "Down"], ["Inc", "Dec"], ["Right", "Left"], ["Next", "Prev"], ["Double", "Half"]];
  for (const [a, b] of pairs) {
    if (name.includes(a)) { const m = name.replace(a, b); if (fnInfo(m)) return m; }
  }
  return null;
}

function summary(a) {
  const label = (n) => (fnInfo(n) || { label: n }).label;
  const slot = (d) => ((info && info.slots) || []).find(([key]) => key === d);
  const deck = (d) => !d || d === "deck" ? "" : slot(d) ? ` (${slot(d)[1].toLowerCase()})`
    : /^d[1-4]$/.test(d) ? ` (deck ${d.slice(1)})` : "";
  if (a.do === "nothing") return "Nothing";
  if (a.do === "function") return `${label(a.function)}${deck(a.deck)}${a.minus ? ` / ${label(a.minus)}` : ""}`;
  if (a.do === "value") return `${label(a.function)}${deck(a.deck)} = ${a.value}${a.release != null ? `, then ${a.release}` : ""}`;
  if (a.do === "functions") return (a.items || []).map((x) => `${label(x.function)}${deck(x.deck)}`).join(" + ");
  if (a.do === "sequence") return (a.steps || []).map((x) => `${x.wait ? `${x.wait}s → ` : ""}${label(x.function)}`).join(", ");
  return a.do;
}

// ---- saving ---------------------------------------------------------------------------------------------------
function toAction() {
  const clean = (x, extra = []) => {
    const out = { function: x.function };
    if (x.deck) out.deck = x.deck;
    for (const k of extra) if (x[k] != null) out[k] = x[k];
    return out;
  };
  const items = draft.items.filter((x) => x.function);
  if (draft.do === "nothing") return { do: "nothing" };
  if (!items.length) throw new Error("Choose a function first");
  if (draft.do === "function") {
    const a = { do: "function", ...clean(items[0]) };
    if (items[0].minus) a.minus = items[0].minus;
    return a;
  }
  if (draft.do === "value") return { do: "value", ...clean(items[0], ["value", "release"]) };
  if (draft.do === "functions") return { do: "functions", items: items.map((x) => clean(x, info.kind === "button" || info.kind === "encoder" ? [] : ["from", "to"])) };
  if (draft.do === "sequence") return { do: "sequence", steps: items.map((x, i) => ({ ...clean(x), wait: i === 0 ? (x.wait || 0) : (x.wait ?? 0.5) })) };
  throw new Error("Choose what it does");
}

function save() {
  let action;
  try { action = toAction(); } catch (e) { $("ed-err").textContent = e.message; return; }
  saveAction(action);
}

async function saveAction(action) {
  busy = true;
  render();
  $("ed-err").textContent = "";
  try {
    await post("binding", { position: target.position, layer, page: info.page, control: target.control, action });
    toast(action ? "Saved" : "Back to the preset");
    info = await post("control-info", { position: target.position, control: target.control, page: info.page });
    startDraft();
  } catch (e) { $("ed-err").textContent = e.message; }
  busy = false;
  render();
}
