// Small Chromium/Edge integration test with no npm dependencies. Run: node --test tests/browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join, resolve, sep } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { test } from "node:test";

const root = resolve(import.meta.dirname, "..");
const web = join(root, "rekordtrakt", "shell", "web", "js");
const browser = process.env.CHROME_PATH || [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
].find(existsSync);
if (process.env.REQUIRE_BROWSER && !browser) throw new Error("Chromium or Edge is required for this test");

const fixture = `<!doctype html><meta charset="utf-8"><body>
<div id="no-view"><span id="no-view-title"></span><span id="no-view-text"></span><button id="no-view-add"></button></div>
<div id="rig"></div><div id="toast"></div>
<aside id="editor" hidden><b id="ed-title"></b><small id="ed-sub"></small><button id="ed-close"></button>
<div id="ed-body"></div><span id="ed-err"></span><button id="ed-reset"></button>
<button id="ed-cancel"></button><button id="ed-save"></button></aside>
<script type="module">
import { app } from "/js/core.js";
import { renderControllers } from "/js/controllers.js";
import { open, setupEditor } from "/js/editor.js";
HTMLElement.prototype.setPointerCapture = function () {};
app.functions = { functions: [{name:"PlayPause",label:"Play/Pause",category:"Transport",kind:"button",scope:"deck"}] };
app.defs = { demo: {name:"Demo",has_shift:false,controls:{
  play:{name:"Play",kind:"button"}, a:{name:"A",kind:"button"}, b:{name:"B",kind:"button"}},
  layout:{columns:["1fr"],items:[{control:"play",shape:"key",c:1,r:1}]}}};
app.view = {devices:[{position:"p",type:"demo",name:"Demo",pages:[],halves:[{half:null,controls:{
  play:{label:"Play",kind:"button"},a:{label:"A",kind:"button"},b:{label:"B",kind:"button"}}}]}]};
app.status = {devices:{p:{connected:true}}};
const pending = new Map(), calls = [];
let delayedBinding = false, bindingResolve = null;
window.fetch = async (url, options) => {
  const name = String(url).split("/").pop().split("?")[0], body = JSON.parse(options?.body || "{}");
  calls.push({name,body});
  if (name === "control-info") return new Promise(resolve => {
    const queue = pending.get(body.control) || [];
    queue.push(resolve); pending.set(body.control, queue);
  });
  if (name === "binding" && delayedBinding) return new Promise(resolve => { bindingResolve = resolve; });
  return {ok:true,json:async()=>({ok:true,result:{}})};
};
window.__test = {
  calls, open, renderControllers,
  pending: name => (pending.get(name) || []).length,
  resolve: name => {
    const resolver = (pending.get(name) || []).shift();
    if (!resolver) throw new Error("No pending " + name);
    resolver({ok:true,json:async()=>({ok:true,result:{kind:"button",page:null,page_bound:false,
      half:null,deck:null,slots:[["a","A",1]],layers:[
        {layer:"base",label:"Normal",mine:null,preset:null},
        {layer:"shift",label:"Shift",mine:null,preset:null}]}})});
  },
  delayBinding: () => { delayedBinding = true; },
  resolveBinding: () => { bindingResolve({ok:true,json:async()=>({ok:true,result:{}})}); bindingResolve=null; },
};
setupEditor(); renderControllers(); window.__ready = true;
</script>`;

async function devtools(port) {
  const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const page = pages.find(p => p.type === "page" && p.url === "about:blank") || pages.find(p => p.type === "page");
  assert.ok(page,"browser has no page target");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolveOpen, reject) => {
    ws.addEventListener("open", resolveOpen, {once:true});
    ws.addEventListener("error", reject, {once:true});
  });
  let id = 0;
  const pending = new Map();
  const errors = [];
  ws.addEventListener("message", e => {
    const m = JSON.parse(e.data);
    if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
    if (m.method === "Log.entryAdded" && m.params.entry.level === "error") errors.push(m.params.entry.text);
    if (!m.id || !pending.has(m.id)) return;
    const [done, fail] = pending.get(m.id); pending.delete(m.id);
    m.error ? fail(new Error(m.error.message)) : done(m.result);
  });
  const call = (method, params = {}) => new Promise((done, fail) => {
    const n = ++id;
    const timer = setTimeout(() => {pending.delete(n); fail(new Error(`CDP ${method} timed out`));},5000);
    pending.set(n, [v => {clearTimeout(timer); done(v);}, e => {clearTimeout(timer); fail(e);}]);
    ws.send(JSON.stringify({id:n,method,params}));
  });
  const evaluate = async expression => {
    const r = await call("Runtime.evaluate", {expression,awaitPromise:true,returnByValue:true});
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
    return r.result.value;
  };
  return {call,evaluate,errors,close:()=>ws.close()};
}

test("screen lock and editor responses use the active control", {skip: !browser && "Chromium or Edge not found", timeout:30000}, async () => {
  const server = createServer(async (req,res) => {
    if (req.url === "/") {res.setHeader("Content-Type","text/html"); res.end(fixture); return;}
    if (/^\/js\/(core|controllers|editor)\.js$/.test(req.url)) {
      res.setHeader("Content-Type","text/javascript");
      res.end(await readFile(join(web, req.url.slice(4)), "utf8")); return;
    }
    res.writeHead(404).end();
  });
  await new Promise(done => server.listen(0,"127.0.0.1",done));
  const profile = await mkdtemp(join(root,".browser-test-"));
  const child = spawn(browser,["--headless=new","--no-first-run","--disable-gpu",
    `--user-data-dir=${profile}`,"--remote-debugging-port=0","about:blank"],{stdio:"ignore"});
  let cdp;
  try {
    let port;
    for (let i=0; i<100; i++) {
      try {port=Number((await readFile(join(profile,"DevToolsActivePort"),"utf8")).split("\n")[0]); break;}
      catch {await delay(50);}
    }
    assert.ok(port,"browser did not start");
    cdp = await devtools(port);
    await cdp.call("Runtime.enable");
    await cdp.call("Log.enable");
    await cdp.call("Page.navigate",{url:`http://127.0.0.1:${server.address().port}/`});
    for (let i=0; i<100 && !(await cdp.evaluate("window.__ready === true")); i++) await delay(50);
    assert.equal(await cdp.evaluate("window.__ready === true"),true,
      JSON.stringify({page:await cdp.evaluate("({url:location.href, hasTest:!!window.__test})"),errors:cdp.errors}));
    console.log("browser fixture ready");

    // A new controller cannot send input until its lock is explicitly opened.
    assert.equal(await cdp.evaluate(`(() => {
      const cell=document.querySelector('.cell[data-control="play"]');
      cell.dispatchEvent(new PointerEvent('pointerdown',{button:0,bubbles:true,pointerId:1}));
      return window.__test.calls.filter(x=>x.name==='input').length;
    })()`),0);
    await cdp.evaluate(`document.querySelector('button[aria-label="Unlock Demo"]').click()`);
    assert.equal(await cdp.evaluate(`(() => {
      const cell=document.querySelector('.cell[data-control="play"]');
      cell.dispatchEvent(new PointerEvent('pointerdown',{button:0,bubbles:true,pointerId:2}));
      cell.dispatchEvent(new PointerEvent('pointerup',{button:0,bubbles:true,pointerId:2}));
      return window.__test.calls.filter(x=>x.name==='input').length;
    })()`),2);
    console.log("lock checked");

    // Per-device Test is wired to an isolated translator mode, independently of the on-screen lock.
    assert.deepEqual(await cdp.evaluate(`(async()=>{
      [...document.querySelectorAll('.device-head button')].find(b=>b.textContent==='TEST').click();
      await new Promise(r=>setTimeout(r,0));
      const c=window.__test.calls.findLast(x=>x.name==='device-test'); return c && c.body;
    })()`),{position:"p",on:true});
    console.log("MIDI test isolation checked");

    // The first request finishes last; it must not replace B's editor.
    await cdp.evaluate(`window.__a=window.__test.open('p','a'); window.__b=window.__test.open('p','b'); true`);
    for (let i=0; i<40 && !(await cdp.evaluate("window.__test.pending('b')")); i++) await delay(25);
    await cdp.evaluate(`window.__test.resolve('b')`);
    await cdp.evaluate(`window.__b`);
    assert.equal(await cdp.evaluate(`document.querySelector('#ed-title').textContent`),"B");
    console.log("editor response order checked");
    // The first open may have been invalidated before it sent a request.
    if (await cdp.evaluate("window.__test.pending('a')")) await cdp.evaluate(`window.__test.resolve('a')`);
    await cdp.evaluate(`window.__a`);
    assert.equal(await cdp.evaluate(`document.querySelector('#ed-title').textContent`),"B");

    // A Save already sent for B must keep B's coordinates after opening A.
    await cdp.evaluate(`document.querySelector('.fn').click(); document.querySelector('.picker .list button').click()`);
    await cdp.evaluate(`document.querySelectorAll('.layers button')[1].click()`);
    await cdp.evaluate(`document.querySelectorAll('.layers button')[0].click()`);
    assert.equal(await cdp.evaluate(`document.querySelector('.fn').textContent`),"Play/Pause");
    await cdp.evaluate(`window.__test.delayBinding(); document.querySelector('#ed-save').click()`);
    await cdp.evaluate(`window.__next=window.__test.open('p','a'); true`);
    for (let i=0; i<40 && !(await cdp.evaluate("window.__test.pending('a')")); i++) await delay(25);
    await cdp.evaluate(`window.__test.resolve('a')`);
    await cdp.evaluate(`window.__next; window.__test.resolveBinding()`);
    assert.equal(await cdp.evaluate(`document.querySelector('#ed-title').textContent`),"A");
    assert.deepEqual(await cdp.evaluate(`window.__test.calls.filter(x=>x.name==='binding').map(x=>x.body.control)`),["b"]);
    assert.deepEqual(await cdp.evaluate(`window.__test.calls.filter(x=>x.name==='binding').map(x=>x.body.layer)`),["base"]);
    console.log("save coordinates checked");

    await cdp.evaluate(`document.querySelector('.fn').click(); document.querySelector('.picker .list button').click()`);
    await cdp.evaluate(`document.querySelector('#ed-close').click()`);
    assert.equal(await cdp.evaluate(`document.querySelector('.ask h2').textContent`),"Discard unsaved mappings?");
    await cdp.evaluate(`document.querySelector('.ask button').click()`);
    assert.equal(await cdp.evaluate(`document.querySelector('#editor').hidden`),false);
    await cdp.evaluate(`document.querySelector('#ed-close').click(); document.querySelector('.ask button:last-child').click()`);
    assert.equal(await cdp.evaluate(`document.querySelector('#editor').hidden`),true);
    console.log("unsaved draft guard checked");
  } finally {
    cdp?.close(); child.kill();
    server.closeAllConnections();
    await new Promise(done=>server.close(done));
    // The path was created under the checkout and is checked before recursive removal.
    if (resolve(profile).startsWith(root+sep)) await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:100});
  }
});
