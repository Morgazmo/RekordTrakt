// Updating Rekordbox's MIDI mapping file: close Rekordbox, install, start it again, each on a click.
import { $, app, post, toast } from "./core.js";

export function bridgeNeedsAttention(s) {
  const b = s && s.bridge_mapping;
  return !!b && (b.state !== "current" || (b.direct || []).length > 0);
}

function why(b) {
  const s = app.status || {};
  const direct = (b.direct || []).map((pos) => ((s.devices || {})[pos] || {}).name || pos);
  const parts = [];
  if (b.state === "missing") parts.push("Rekordbox needs RekordTrakt's MIDI mapping file to hear your controllers.");
  else if (b.state === "required") parts.push(`This setup uses ${b.missing.length} function(s) Rekordbox's mapping file doesn't have yet. They do nothing until it's updated.`);
  else if (b.state === "update") parts.push("A newer mapping file is ready, covering more of Rekordbox. Everything you use works until you update.");
  else parts.push("Rekordbox already has the current mapping file. Reinstalling it is only needed if your controllers stop working in Rekordbox.");
  if (direct.length) parts.push(`Rekordbox also still has its own mapping for ${direct.join(", ")}, so presses would fire twice. Installing turns that off (a backup is kept).`);
  return parts.join(" ");
}

let rb = {}, poll = null;
export async function openRekordboxDialog() {
  rb = { running: null, playing: null, closing: false, installed: null, conflict: null, starting: false };
  $("rb-dialog").showModal();
  render();
  await check();
  clearInterval(poll);
  poll = setInterval(check, 1500);
}
async function check() {
  try {
    const r = await post("rekordbox-check");
    if (rb.running && !r.running) rb.closing = false;
    if (!rb.running && r.running) rb.starting = false;
    rb.running = r.running;
    rb.responding = r.responding;
    rb.midiStuck = r.midi_stuck;
    rb.found = r.found;
  } catch { /* the header says RekordTrakt is unreachable */ }
  render();
}

export function setupRekordboxDialog() {
  $("rb-dialog").addEventListener("close", () => clearInterval(poll));
  $("rb-done").onclick = () => $("rb-dialog").close();
  $("rb-close").onclick = async () => {
    try {
      const r = await post("rekordbox-close", { anyway: !!rb.playing });
      rb.playing = r.playing || null;
      rb.closing = !!r.closing;
    } catch (e) { toast(e.message, true); }
    render();
  };
  $("rb-end").onclick = async () => {
    try { await post("rekordbox-close", { end: true }); rb.closing = true; } catch (e) { toast(e.message, true); }
    render();
  };
  $("rb-install").onclick = async () => {
    $("rb-install").disabled = true;
    $("rb-install-text").textContent = "Installing";
    try {
      const r = await post("rekordbox-install", { overwrite: !!rb.conflict });
      if (r.installed) { rb.installed = r; rb.conflict = null; }
      else if (r.conflict) rb.conflict = r.conflict;
      else if (r.needs) rb.running = true;
    } catch (e) { toast(e.message, true); }
    render();
  };
  $("rb-start").onclick = async () => {
    try { const r = await post("rekordbox-start"); rb.starting = !!r.starting; } catch (e) { toast(e.message, true); }
    render();
  };
}

export function render() {
  if (!$("rb-dialog").open) return;
  const b = (app.status && app.status.bridge_mapping) || {};
  const running = rb.running, closed = running === false;
  $("rb-why").textContent = rb.installed ? "Installed. RekordTrakt has restarted with the new mapping file: start Rekordbox to use it." : why(b);
  $("rb-step-close").classList.toggle("done", closed || !!rb.installed);
  $("rb-close-text").textContent = rb.installed ? "Rekordbox was closed for the install."
    : running === null ? "Checking"
    : closed ? "Rekordbox is closed."
    : rb.responding === false ? "Rekordbox is running but not responding (its window may be gone), so it can't be asked to close. End it? Anything unsaved in Rekordbox is lost."
    : rb.playing ? `Deck ${rb.playing.join(" and ")} ${rb.playing.length > 1 ? "are" : "is"} playing. Close Rekordbox anyway?`
    : rb.closing ? "Closing. Rekordbox may ask you to confirm."
    : "Rekordbox reads its MIDI mappings when it starts, so it has to close first.";
  const hung = running === true && rb.responding === false;
  $("rb-close").hidden = closed || !!rb.installed || hung;
  $("rb-end").hidden = !hung || !!rb.installed;
  $("rb-close").disabled = rb.closing;
  $("rb-close").textContent = rb.playing ? "Close anyway" : "Close";
  $("rb-step-install").classList.toggle("done", !!rb.installed);
  $("rb-install").hidden = !!rb.installed;
  $("rb-install").disabled = !closed;
  $("rb-install").textContent = rb.conflict ? "Replace it" : "Install";
  $("rb-install-text").textContent = rb.installed
    ? `Installed: ${rb.installed.entries} entries. What was there before is backed up.`
    : rb.conflict ? "The mapping file was edited by hand since RekordTrakt installed it. Replace it? A backup is kept."
    : "Backups are kept; uninstalling puts back what you had.";
  const started = !!rb.installed && running === true;
  $("rb-step-start").classList.toggle("done", started);
  $("rb-start").hidden = started;
  $("rb-start").disabled = !rb.installed || !closed || rb.starting || rb.found === false || rb.midiStuck;
  $("rb-start-text").textContent = started ? "Rekordbox is running with the new mapping file."
    : rb.starting ? "Starting"
    : rb.midiStuck ? "Windows' MIDI service isn't responding, so Rekordbox would freeze while starting. Restart the Windows MIDI Service (or Windows) first."
    : rb.found === false ? "Start Rekordbox from the Start menu."
    : "";
  $("rb-done").textContent = rb.installed || b.state === "current" ? "Done" : "Later";
}
