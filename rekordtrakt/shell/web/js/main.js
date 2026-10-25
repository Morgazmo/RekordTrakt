// The RekordTrakt window: header, tabs, overlays and the live connection; each tab draws itself. The header is the
// only status area: the Rekordbox chip (which version is running), Bypass, and a chip for whatever needs attention.
import { $, TOKEN, app, change, el, icon, post, toast, on } from "./core.js";
import { loadDefinitions, renderControllers, setEditing } from "./controllers.js";
import { loadMidiDevices, renderSettings, showSettingsPage } from "./settings.js";
import { bridgeNeedsAttention, openRekordboxDialog, render as renderRekordbox, setupRekordboxDialog } from "./rekordbox.js";
import { setupEditor } from "./editor.js";
import { setupHeaderButton } from "./appearance.js";
import { popover } from "./popover.js";

$("logo").src = document.querySelector('link[rel="icon"]').href;
$("support").prepend(icon("heart"));
$("appearance-btn").prepend(icon("palette"));

// ---- tabs ------------------------------------------------------------------------------------------------------
function showTab(name) {
  if (!["controllers", "settings", "debug"].includes(name)) name = "controllers";
  app.tab = name;
  for (const a of document.querySelectorAll("nav a")) a.setAttribute("aria-selected", String(a.dataset.tab === name));
  for (const s of document.querySelectorAll(".tab")) s.classList.toggle("active", s.id === `tab-${name}`);
  if (name === "debug" && !$("tab-debug").firstChild) {
    const frame = document.createElement("iframe");
    frame.src = `/debug?token=${encodeURIComponent(TOKEN)}&embed=1`;
    frame.title = "Debug";
    $("tab-debug").appendChild(frame);
  }
  if (name === "settings") { loadMidiDevices(); renderSettings(); }
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  showOverlay();
}
for (const a of document.querySelectorAll("nav a")) a.onclick = () => showTab(a.dataset.tab);
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));

// ---- header ----------------------------------------------------------------------------------------------------
$("support").onclick = () => post("open-support").catch(() => toast("Couldn't open the browser", true));
$("bypass").onchange = (e) => change("bypass", { on: e.target.checked }, e.target.checked ? "Bypass on" : "Bypass off").then(refresh);
$("rb-chip").onclick = () => { showTab("settings"); showSettingsPage("rekordbox"); };
const noticePop = popover($("notice-chip"), $("notice-pop"), "left");
$("no-view-add").onclick = () => { showTab("settings"); showSettingsPage("midi"); };

async function refresh() {
  try {
    const r = await fetch(`/api/status?token=${encodeURIComponent(TOKEN)}`, { cache: "no-store" });
    if (r.status === 403) return gone();
    app.status = await r.json();
    showStatus();
  } catch { gone(); }
}
function gone() {
  app.status = null;
  $("bypass").disabled = true;
  showNotices();
  showRekordbox();
  showOverlay();
}

// Which Rekordbox is running.
const runningMajor = (s) => s && s.rekordbox_running && s.rekordbox_version ? Number(s.rekordbox_version.split(".")[0]) : null;
const silent = (s) => s && s.state === "running" && s.rekordbox_silent;

// What needs attention, worst first: { level: bad | warn | info, title, text, action: [label, fn] }.
const LEVELS = ["bad", "warn", "info"];
function notices(s) {
  if (!s) return [{ level: "bad", title: "RekordTrakt isn't reachable",
                    text: "If you quit or restarted it, open this window again from its tray icon." }];
  const out = [];
  if (s.state === "failed" && s.error)
    out.push({ level: "bad", title: "RekordTrakt stopped",
               text: `${s.error}${s.restart_in != null ? ` Trying again in ${Math.ceil(s.restart_in)} s.` : ""}` });
  if (s.bridge && s.bridge.muted) out.push({ level: "bad", title: "The MIDI bridge is muted", text: s.bridge.message });
  if (bridgeNeedsAttention(s)) out.push(mappingNotice(s));
  if (silent(s) && runningMajor(s) === 7)
    out.push({ level: "bad", title: "Rekordbox 7 can't hear your controllers",
               text: "Its MIDI mapping is locked without a paid plan. Use Rekordbox 6, or a paid plan." });
  else if (silent(s))
    out.push({ level: "bad", title: "Rekordbox isn't answering",
               text: "In Rekordbox's MIDI settings, check RekordTrakt Bridge is listed and the MIDI button isn't locked." });
  if (s.state === "running")
    for (const d of Object.values(s.devices || {}))
      if (!d.connected) out.push({ level: "warn", title: `${d.name} isn't connected`, text: "Plug it in: it's picked up automatically." });
  for (const name of s.other_dj_software || [])
    out.push({ level: "warn", title: `${name} is running too`, text: "If it also uses these controllers, presses may do two things." });
  return out.sort((a, b) => LEVELS.indexOf(a.level) - LEVELS.indexOf(b.level));
}
function mappingNotice(s) {
  const b = s.bridge_mapping, n = (b.missing || []).length;
  const direct = (b.direct || []).map((p) => ((s.devices || {})[p] || {}).name || p);
  const twice = direct.length ? ` Rekordbox also still has its own mapping for ${direct.join(", ")}, so presses fire twice: installing turns it off.` : "";
  const install = ["Install", openRekordboxDialog], update = ["Update", openRekordboxDialog];
  if (b.state === "missing")
    return { level: "bad", title: "Rekordbox's mapping file isn't installed", text: "Rekordbox can't hear your controllers until it is." + twice, action: install };
  if (b.state === "required")
    return { level: "warn", title: "Rekordbox's mapping file needs an update",
             text: `${n} function${n === 1 ? "" : "s"} this setup uses do nothing until it's updated.` + twice, action: update };
  if (b.state === "update")
    return { level: direct.length ? "warn" : "info", title: "An update for Rekordbox's mapping file is ready",
             text: "Everything you use works; the update adds more of Rekordbox." + twice, action: update };
  return { level: "warn", title: "Controls would fire twice in Rekordbox", text: twice.trim(), action: update };
}
function showNotices() {
  const list = notices(app.status), chip = $("notice-chip");
  chip.hidden = !list.length;
  if (!list.length) { noticePop.close(); return; }
  chip.className = `hchip notice ${list[0].level}`;
  chip.querySelector(".dot").className = `dot ${list[0].level}`;
  $("notice-text").textContent = list[0].title;
  $("notice-more").textContent = list.length > 1 ? `+${list.length - 1}` : "";
  chip.title = list.map((x) => x.title).join("\n");
  $("notice-pop").replaceChildren(...list.map((x) => {
    const row = el("div", "row"), t = el("div", "t");
    t.append(el("b", null, x.title), el("small", null, x.text));
    row.append(el("span", `dot ${x.level}`), t);
    if (x.action) {
      const b = el("button", null, x.action[0]);
      b.onclick = () => { noticePop.close(); x.action[1](); };
      row.appendChild(b);
    }
    return row;
  }));
}
function showRekordbox() {
  const s = app.status, chip = $("rb-chip");
  const running = s && s.rekordbox_running;
  $("rb-state").textContent = !s || s.rekordbox_running == null ? "Rekordbox"
    : running ? `Rekordbox ${s.rekordbox_version || "running"}` : "Rekordbox not running";
  chip.querySelector(".dot").className = "dot" + (running ? (silent(s) ? " bad" : " ok") : "");
}

function showOverlay() {
  const s = app.status, wm = $("watermark"), arrow = $("wm-arrow"), rig = $("rig");
  let title = null, text = "", colour = "--warn";
  if (!s) { title = "OFFLINE"; text = "RekordTrakt isn't reachable."; colour = "--off"; }
  else if (s.state === "failed") {
    title = "STOPPED"; colour = "--bad";
    text = `${s.error || "Something went wrong."}${s.restart_in != null ? ` Trying again in ${Math.ceil(s.restart_in)} s.` : ""}`;
  } else if (s.bypass) { title = "BYPASS"; text = "Your controllers send nothing to Rekordbox."; }
  // A Rekordbox that isn't answering is shown in the header only (the notice and the Rekordbox chip turn red).
  const onControllers = app.tab === "controllers";
  wm.classList.toggle("show", !!title && onControllers);
  wm.style.setProperty("--wm", `var(${colour})`);
  $("wm-title").textContent = title || "";
  $("wm-text").textContent = text;
  rig.classList.toggle("greyed", !!title);
  const bypassed = !!(s && s.bypass) && onControllers;
  arrow.classList.toggle("show", bypassed);
  if (bypassed) placeArrow();
}
// The "Bypass is on ↑" arrow points up at the Bypass switch, wherever the header puts it.
function placeArrow() {
  const arrow = $("wm-arrow"), chip = $("bypass-chip").getBoundingClientRect();
  arrow.style.left = `${Math.max(8, chip.left + chip.width / 2 - arrow.offsetWidth + 7)}px`;
}
window.addEventListener("resize", () => { if ($("wm-arrow").classList.contains("show")) placeArrow(); });

function showStatus() {
  const s = app.status;
  showRekordbox();
  $("bypass").disabled = false;
  $("bypass").checked = !!s.bypass;
  $("bypass-chip").classList.toggle("bypassed", !!s.bypass);
  showNotices();
  showOverlay();
  renderControllers();
  if (app.tab === "settings") renderSettings();
  renderRekordbox();
}

// ---- live updates ----------------------------------------------------------------------------------------------
let pending = null;
function receive(e) {
  if (e.kind === "view") {
    if (!pending) requestAnimationFrame(applyView);
    pending = e.data || { devices: [] };
  } else if (["status", "supervisor", "bridge", "error", "notice"].includes(e.kind)) scheduleRefresh();
}
function applyView() {
  if (pending) { app.view = pending; pending = null; }
  renderControllers();
  if (app.tab === "settings") renderSettings();
}
let refreshTimer = null;
function scheduleRefresh() { if (!refreshTimer) refreshTimer = setTimeout(() => { refreshTimer = null; refresh(); }, 150); }

function connect() {
  const source = new EventSource(`/events?token=${encodeURIComponent(TOKEN)}&kinds=view,status,supervisor,bridge,error,notice`);
  source.addEventListener("backlog", (m) => { for (const e of JSON.parse(m.data)) receive(e); });
  source.onmessage = (m) => receive(JSON.parse(m.data));
  source.onerror = () => scheduleRefresh();
}

on("render", renderControllers);
on("definitions", () => { loadDefinitions(); refresh(); });
on("edit-mode", (position) => { showTab("controllers"); setEditing(position, true); });
on("refresh", refresh);

setupHeaderButton();
setupRekordboxDialog();
setupEditor();
showTab(location.hash.slice(1));
loadDefinitions();
refresh();
setInterval(refresh, 3000);
connect();
