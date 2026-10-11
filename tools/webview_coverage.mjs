// V8 block coverage from only the task-owned WebView2 target; no external browser is inspected.
import { readFile, writeFile, access } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
const [port, pageUrl, scriptUrl, output, ready, stop] = process.argv.slice(2);
const deadline = Date.now() + 30000;
let target;
while (Date.now() < deadline) {
  try { target = (await (await fetch(`http://127.0.0.1:${Number(port)}/json/list`)).json()).find(t => t.url === pageUrl); } catch {}
  if (target) break;
  await delay(100);
}
if (!target) throw new Error('The task-owned WebView2 target was not found');
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, {once:true}); socket.addEventListener('error', reject, {once:true}); });
let nextId = 0;
const pending = new Map();
socket.addEventListener('message', event => {
  const result = JSON.parse(event.data), request = pending.get(result.id);
  if (!request) return;
  pending.delete(result.id); clearTimeout(request.timer);
  if (result.error) request.reject(new Error(result.error.message)); else request.resolve(result.result);
});
function call(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 10000);
    pending.set(id, {resolve, reject, timer}); socket.send(JSON.stringify({id,method,params}));
  });
}
// Start only after the owned fixture has initialized; startup is outside action coverage.
while (Date.now() < deadline) {
  const initialized = await call('Runtime.evaluate', {expression:"!!window.pywebview?.api && !!document.getElementById('resultsCard') && !document.getElementById('resultsCard').hidden",returnByValue:true});
  if (initialized.result.value) break;
  await delay(100);
}
await call('Profiler.enable');
await call('Profiler.startPreciseCoverage', {callCount:true,detailed:true});
await writeFile(ready, 'ready');
let stopped = false;
while (Date.now() < deadline + 120000) {
  try { await access(stop); stopped = true; break; } catch {}
  await delay(100);
}
if (!stopped) throw new Error('Coverage scenario did not finish');
const raw = await call('Profiler.takePreciseCoverage');
await call('Profiler.stopPreciseCoverage');
socket.close();
const scripts = raw.result.filter(script => script.url === scriptUrl);
if (scripts.length !== 1) throw new Error(`Expected one app.js script, found ${scripts.length}`);
const script = scripts[0], ranges = script.functions.flatMap(fn => fn.ranges);
const sourceLength = (await readFile(new URL(scriptUrl), 'utf8')).length;
const edges = [...new Set([0,sourceLength,...ranges.flatMap(r => [r.startOffset,r.endOffset])])].sort((a,b)=>a-b);
let covered = 0, total = 0;
for (let index=1; index<edges.length; index++) {
  const start=edges[index-1], end=edges[index];
  const containing=ranges.filter(r => r.startOffset <= start && r.endOffset >= end).sort((a,b)=>(a.endOffset-a.startOffset)-(b.endOffset-b.startOffset));
  total += end-start;
  if (containing.length && containing[0].count > 0) covered += end-start;
}
const report = {schema:'anonimato-v8-block-coverage-v1',url:script.url,covered,total,percent:100*covered/total,
  coveredFunctions:script.functions.filter(f=>f.ranges[0].count>0).length,totalFunctions:script.functions.length,
  limitations:'Task-owned real-window action coverage; UTF-16 source ranges, not line coverage or accessibility certification.',raw:script};
await writeFile(output, JSON.stringify(report,null,2));
