"use strict";

// Run with an existing Node runtime: node --test --test-isolation=none tests/test_ui.cjs.
// Every fetch is mocked; this suite never contacts the local server or DeepSeek.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const staticDir = path.join(__dirname, "..", "app", "static");
const script = fs.readFileSync(path.join(staticDir, "app.js"), "utf8");
const html = fs.readFileSync(path.join(staticDir, "index.html"), "utf8");
const css = fs.readFileSync(path.join(staticDir, "style.css"), "utf8");
const libraryScript = fs.readFileSync(path.join(staticDir, 'library.js'), 'utf8');

class Element {
  constructor() {
    this.children = []; this.attrs = {}; this.value = ""; this.textContent = "";
    this.hidden = false; this.disabled = false; this.className = ""; this.listeners = {};
    this.style = {}; this.currentTime = 0;
    this.classList = {
      contains: (name) => this.className.split(" ").includes(name),
      toggle: (name, force) => {const names=new Set(this.className.split(" ").filter(Boolean)); if(force ?? !names.has(name)) names.add(name); else names.delete(name); this.className=[...names].join(" ");},
      add: (...names) => {const values=new Set(this.className.split(" ").filter(Boolean)); names.forEach(name=>values.add(name)); this.className=[...values].join(" ");},
      remove: (...names) => {const values=new Set(this.className.split(" ").filter(Boolean)); names.forEach(name=>values.delete(name)); this.className=[...values].join(" ");},
    };
    this.dataset = {};
  }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return this.attrs[name]; }
  querySelector(selector) {
    if (!this.descendants) this.descendants = new Map();
    if (!this.descendants.has(selector)) this.descendants.set(selector, new Element());
    return this.descendants.get(selector);
  }
  removeAttribute(name) { delete this.attrs[name]; }
  querySelectorAll(selector) {
    const descendants=this.children.flatMap(child=>[child,...child.querySelectorAll()]);
    return selector==='button' ? descendants.filter(child=>child.tagName==='BUTTON') : descendants;
  }
  get lastElementChild() { return this.children.at(-1); }
  pause() { this.paused=true; } load() {} scrollIntoView() {}
  play() { this.paused=false; return Promise.resolve(); }
  set src(value) { this.attrs.src=value; }
  get src() { return this.attrs.src; }
}

async function ui(options = {}) {
  const elements = new Map();
  const element = (id) => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const stageElements = ["prepare", "transcribe", "analyze", "condense", "framing", "plan", "render"].map(stage => {
    const node = new Element(); node.dataset.stage = stage; return node;
  });
  element("analysis-provider").value = "deepseek_plan";
  element("layout").value = "cinema";
  element("caption-style").value = "accent";
  const data = {
    status: {configured: true, budget_usd: null, remaining_usd: "1.00", charged_ceiling_usd: "0.0000789", model: "deepseek-flash", ...options.status},
    statusError: false, ready: true, jobs: [], calls: [],
    copied: [],
    connection: {available: true, vision_supported: true, model: "deepseek-flash", balance_infos: [{currency: "USD", total_balance: "1.00"}]},
    providerBalance:{balance_usd:'1.00',observed_decrease_usd:'0.03',measured_at:1770000000,stale:false,scope:'account'},
  };
  const context = vm.createContext({
    console, URL, location: {origin: "http://127.0.0.1:8765", hash:'#projects'}, setInterval: () => {}, addEventListener:()=>{},
    navigator: {clipboard: {writeText: async text => {if(data.clipboardFailure) throw new Error('denied'); data.copied.push(text);}}},
    document: {getElementById: element, createElement: tag => {const e=new Element(); e.tagName=tag.toUpperCase(); return e;}, querySelectorAll: selector => selector === "[data-stage]" ? stageElements : Array.from({length: 5}, () => new Element())},
    fetch: async (url, request = {}) => {
      data.calls.push({url, method: request.method ?? "GET", body: request.body, headers: request.headers});
      let body;
      if (url === "/api/deepseek") {
        if (data.statusError) return {ok: false, status: 503, json: async () => ({detail: "Локальный статус недоступен"})};
        body = data.status;
      } else if (url === "/api/deepseek/check") body = data.connection;
      else if (url.startsWith('/api/deepseek/balance?')) {
        if(data.balanceError) return {ok:false,status:503,json:async()=>({detail:'Balance unavailable'})};
        body=data.providerBalance;
      }
      else if (url === "/api/deepseek/recovery") body = {halted:false, uncertain_requests:0, reserved_ceiling_usd:"0"};
      else if (url === "/api/health") body = {ready: data.ready, missing: [], busy: false};
      else if (url === "/api/sources") body = [{id: "source-1", name: "Русская серия.mp4", size: 1024}];
      else if (url === "/api/jobs" && request.method === "POST") {
        const submitted = JSON.parse(request.body);
        body = {id: `job-${data.jobs.length + 1}`, source_name: "Русская серия.mp4", status: "queued", stage: "queued", files: [], analysis_provider: submitted.analysis_provider};
        data.jobs.push(body);
      } else if (url === "/api/jobs") body = data.jobs;
      else if (url === '/api/library') body=data.library ?? {projects:[],episodes:[]};
      else if (/^\/api\/(projects|episodes)\/[^/]+(?:\/restore)?$/.test(url) && ['DELETE','POST'].includes(request.method)) {
        const item=data.library[url.split('/')[2]].find(i=>i.id===url.split('/')[3]);
        if(request.method==='DELETE') item.archived_at='2026-10-03'; else delete item.archived_at;
        body={id:item.id,archived:!!item.archived_at};
      }
      else if (/\/api\/episodes\/[^/]+\/settings$/.test(url)) {
        const episode=data.library.episodes.find(e=>e.id===url.split('/')[3]);
        const saved=JSON.parse(request.body); episode.source_id=saved.source_id; delete saved.source_id; episode.settings=saved; body=episode;
      }
      else if (/\/api\/episodes\/[^/]+\/jobs$/.test(url)) {
        const episode=data.library.episodes.find(e=>e.id===url.split('/')[3]);
        body={id:'episode-job',episode_id:episode.id,source_name:'Серия.mp4',status:'running',stage:'prepare',files:[],...episode.settings};
        data.jobs.unshift(body); episode.jobs.unshift({id:body.id,status:body.status});
      }
      else if (url.endsWith('/reset-budget')) { data.attemptReset = true; body = {attempt:2, charged_ceiling_usd:'0'}; }
      else if (url.endsWith('/spending')) body = {limit_usd:'0.10', charged_ceiling_usd:data.attemptReset ? '0' : '0.08', remaining_usd:'0.02', attempt:data.attemptReset ? 2 : 1, job_total_usd:'0.08'};
      else if (url.endsWith("/plan")) body = data.plan ?? {warnings: ["DeepSeek недоступен: кадр выбран локально."]};
      else if (url.endsWith('/save-videos') && request.method==='POST') {
        if(data.saveFailure)return {ok:false,status:507,json:async()=>data.saveFailure};
        if(data.saveError)return {ok:false,status:500,json:async()=>({detail:data.saveError})};
        body=typeof data.saveHandler==='function' ? await data.saveHandler(JSON.parse(request.body)) : data.saveResult ?? {cancelled:false,count:1,files:['part_001.mp4']};
      }
      else body = data.jobs.find((job) => url === `/api/jobs/${job.id}`);
      assert.notEqual(body, undefined, `Unexpected mocked route: ${url}`);
      return {ok: true, status: 200, json: async () => body};
    },
  });
  vm.runInContext(script, context);
  await new Promise((resolve) => setImmediate(resolve));
  const run = (code) => vm.runInContext(code, context);
  element("source").value = "source-1"; run("sourceChanged()");
  return {
    data, element, run, stageElements,
    async installLibrary(data) { this.data.library=data; vm.runInContext(libraryScript,context); await new Promise(resolve=>setImmediate(resolve)); },
    choose(provider) { element("analysis-provider").value = provider; run("renderProvider()"); },
    submit() { return element("create-form").listeners.submit({preventDefault() {}}); },
    checks() { return data.calls.filter((call) => call.url === "/api/deepseek/check"); },
    posts() { return data.calls.filter((call) => call.url === "/api/jobs" && call.method === "POST").map((call) => JSON.parse(call.body)); },
  };
}

test("analysis picker exposes only local and DeepSeek story planning; launch makes no accounting calls", async () => {
  const u = await ui();
  const picker = html.match(/<select id="analysis-provider">([\s\S]*?)<\/select>/)?.[1] ?? "";
  assert.deepEqual([...picker.matchAll(/<option value="([^"]+)"/g)].map(match => match[1]), ["deepseek_plan", "local"]);
  assert.match(picker, /value="deepseek_plan" selected/);
  assert.equal(u.run("analysisProvider()"), "deepseek_plan");
  assert.equal(u.element("deepseek-notice").hidden, false);
  await u.submit();
  assert.equal(u.posts()[0].analysis_provider, "deepseek_plan");
  u.choose("local"); await u.submit();
  assert.equal(u.posts()[1].analysis_provider, "local");
  assert.equal(u.checks().length, 0);
  assert(!u.data.calls.some(call => /balance|spending|reset-budget/.test(call.url)));
});

test('automatic cover context follows the selected part and copies its current prompt', async () => {
  const u=await ui();
  u.run(`state.selected='job';state.files=[{url:'/one.mp4'},{url:'/two.mp4'}];state.timeline={jobId:'job',plan:{source:{duration:30},parts:[
    {cuts:[{start:0,end:10}],cover_context:{title:'Магазин',synopsis:'Герой приходит в магазин.',prompt:'Магазин, 9:16.',method:'model'}},
    {cuts:[{start:10,end:20}],cover_context:{title:'Встреча',synopsis:'Он встречает кассира.',prompt:'Встреча, 9:16.',method:'extractive'}}]}};selectFile(0,false);`);
  assert.equal(u.element('part-context').hidden,false);
  assert.equal(u.element('part-context-synopsis').textContent,'Герой приходит в магазин.');
  assert.equal(u.element('part-context-fallback').hidden,true);
  u.run('selectFile(1,false)');
  assert.equal(u.element('part-context-heading').textContent,'Заставка · часть 02');
  assert.equal(u.element('part-context-prompt').value,'Встреча, 9:16.');
  assert.equal(u.element('part-context-fallback').hidden,false);
  await u.run('copyPartContext()');
  assert.equal(u.data.copied.at(-1),'Контекст: Он встречает кассира.\n\nВстреча, 9:16.');
  u.data.clipboardFailure=true;await u.run('copyPartContext()');
  assert.match(u.element('context-copy-status').textContent,/Не удалось/);
  u.run(`state.selected='another-job';renderPartContext();`);
  assert.equal(u.element('part-context').hidden,true);
});

test("processing checkpoints identify the active stage and where work runs", async () => {
  const u = await ui();
  u.run('renderJob({id:"running",status:"running",stage:"condense",progress:0.62,message:"Проверяем темп",analysis_provider:"deepseek_plan",files:[]})');
  assert.deepEqual(u.stageElements.map(node => node.className), ["done", "done", "done", "current", "pending", "pending", "pending"]);
  assert.equal(u.stageElements[3].getAttribute("aria-current"), "step");
  assert.equal(u.stageElements[2].querySelector("[data-stage-owner]").textContent, "DeepSeek API");
  assert.equal(u.stageElements[3].querySelector("[data-stage-owner]").textContent, "DeepSeek API");
  assert.equal(u.stageElements[4].querySelector("[data-stage-owner]").textContent, "На компьютере · для этого режима");
  assert.equal(u.stageElements[5].querySelector("[data-stage-owner]").textContent, "На компьютере");
  assert.equal(u.stageElements[6].querySelector("[data-stage-owner]").textContent, "На компьютере");
  assert.equal(u.stageElements[3].querySelector("[data-stage-state]").textContent, "Выполняется");
  assert.match(html, /<ol class="stages"[^>]*aria-label="Этапы обработки"/);
  assert.match(html, /<li data-stage="condense"/);
  assert.match(html, /<li data-stage="framing"/);
  assert.match(css, /@media\(max-width:480px\)\{\.stages\{grid-template-columns:1fr/);
  assert.match(html, /href="\/static\/style\.css\?v=[a-z0-9-]+"/);
  assert.match(html, /src="\/static\/app\.js\?v=[a-z0-9-]+"/);
});

test("completed, failed, cancelled and queued jobs retain truthful checkpoint states", async () => {
  const u = await ui();
  u.run('renderJob({status:"completed",stage:"completed",progress:1,analysis_provider:"local",files:[]})');
  assert(u.stageElements.every(node => node.classList.contains("done")));
  u.run('renderJob({status:"failed",stage:"rendering",progress:0.74,error:"encoder failed",analysis_provider:"local",files:[]})');
  assert.deepEqual(u.stageElements.map(node => node.className), ["done", "done", "done", "done", "done", "done", "failed"]);
  assert.equal(u.element("job-error").hidden, false);
  assert.equal(u.stageElements[6].querySelector("[data-stage-state]").textContent, "Остановлено с ошибкой");
  u.run('renderJob({status:"cancelled",stage:"transcribe",progress:0.08,analysis_provider:"deepseek_plan",files:[]})');
  assert.deepEqual(u.stageElements.map(node => node.className), ["done", "cancelled", "pending", "pending", "pending", "pending", "pending"]);
  u.run('renderJob({status:"queued",stage:"queued",progress:0,analysis_provider:"local",files:[]})');
  assert(u.stageElements.every(node => node.classList.contains("pending")));
  assert(u.stageElements.every(node => node.getAttribute("aria-current") === undefined));
  u.run('renderJob({status:"running",stage:"framing",progress:0.65,analysis_provider:"deepseek_plan",files:[]})');
  assert.deepEqual(u.stageElements.map(node => node.className), ["done", "done", "done", "done", "current", "pending", "pending"]);
  assert.equal(u.stageElements[4].querySelector("[data-stage-owner]").textContent, "На компьютере · для этого режима");
  u.run('renderJob({status:"running",stage:"scenes",progress:0.19,analysis_provider:"deepseek_plan",files:[]})');
  assert.deepEqual(u.stageElements.map(node => node.className), ["current", "pending", "pending", "pending", "pending", "pending", "pending"]);
  assert.match(u.stageElements[0].querySelector("[data-stage-owner]").textContent, /поиск смены планов/);
  u.run('renderJob({status:"running",stage:"unexpected",progress:0.4,analysis_provider:"local",files:[]})');
  assert(u.stageElements.every(node => node.classList.contains("unknown")));
  u.run('renderJob({status:"running",stage:"analyze",progress:0.51,analysis_provider:"deepseek_plan",files:[]})');
  assert.deepEqual(u.stageElements.map(node => node.className), ["done", "done", "current", "pending", "pending", "pending", "pending"]);
});

test("preset changes update the preview and explicit request without paid checks", async () => {
  const u = await ui();
  u.element("layout").value = "portrait";
  u.element("caption-style").value = "classic";
  u.run("renderEditing()");
  assert.equal(u.element("style-preview").className, "style-preview portrait classic");
  assert.match(u.element("layout-description").textContent, /Обработка дольше/);
  await u.submit();
  assert.equal(u.posts()[0].layout, "portrait");
  assert.equal(u.posts()[0].caption_style, "classic");
  assert.equal(u.checks().length, 0);
});

test("drop rejects multiple or unsupported files before import", async () => {
  const u = await ui();
  await u.element("upload-button").listeners.drop({preventDefault() {}, dataTransfer: {files: [{name: "a.mp4"}, {name: "b.mp4"}]}});
  assert.match(u.element("form-message").textContent, /по одной серии/);
  await u.element("upload-button").listeners.drop({preventDefault() {}, dataTransfer: {files: [{name: "script.exe"}]}});
  assert.match(u.element("form-message").textContent, /MP4 или MKV/);
  assert(!u.data.calls.some((call) => call.url === "/api/import"));
});

test("legacy modes normalize to DeepSeek planning while old jobs keep their provider labels", async () => {
  const u = await ui({status: {remaining_usd: "0.00"}});
  u.choose("hybrid"); assert.equal(u.run("analysisProvider()"), "deepseek_plan");
  await u.submit(); assert.equal(u.posts()[0].analysis_provider, "deepseek_plan");
  u.choose("deepseek"); assert.equal(u.run("analysisProvider()"), "deepseek_plan");
  const savedLocal = {analysis_provider:"local",layout:"cinema",caption_style:"accent"};
  await u.installLibrary({projects:[{id:"p",title:"Аниме"}],episodes:[{id:"e",project_id:"p",number:1,title:"Серия 1",source_id:"source-1",settings:{...savedLocal,analysis_provider:"hybrid"},jobs:[]}]});
  await u.run("location.hash='#episode/e/edit'; libraryUI.route()");
  assert.equal(u.element("analysis-provider").value, "deepseek_plan");
  u.run('state.navigation=null; state.jobs=[{id:"old-hybrid",source_name:"Серия.mp4",status:"failed",stage:"analyze",analysis_provider:"hybrid",files:[]},{id:"old-deepseek",source_name:"Серия.mp4",status:"failed",stage:"analyze",analysis_provider:"deepseek",files:[]},{id:"old-local",source_name:"Серия.mp4",status:"failed",stage:"analyze",analysis_provider:"local",files:[]}]; state.selected=null; state.historyKey=""; renderHistory()');
  assert.match(u.element("history-list").children[0].children[1].children[0].textContent,/Локально \+ DeepSeek/);
  assert.match(u.element("history-list").children[1].children[1].children[0].textContent,/ · DeepSeek$/);
  assert.equal(u.element("history-list").children[2].children[1].children[0].textContent,"Ошибка");
});

test("DeepSeek launch requires configured API and local readiness, without balance-based gating", async () => {
  const u = await ui();
  u.choose("deepseek_plan");
  assert.equal(u.element("deepseek-notice").hidden, false);
  assert.equal(u.element("hybrid-fallback").hidden, true);
  assert.match(u.element("provider-description").textContent, /события, заставки и титры/);
  assert.match(u.element("provider-description").textContent, /Распознавание речи, кадрирование, монтаж и экспорт выполняются на компьютере/);
  assert.match(u.element("deepseek-notice-description").textContent, /исходные кадры серии и распознанные реплики/);
  assert.match(u.element("deepseek-notice-description").textContent, /DeepSeek не используется для обрезки кадра/);
  assert.match(u.element("storage-description").textContent, /Кадрирование и экспорт выполняются локально/);
  u.data.status.configured=false; await u.run("loadDeepseekStatus()");
  assert.equal(u.element("create-button").disabled,true);
  await u.submit(); assert.equal(u.posts().length,0);
  Object.assign(u.data.status,{configured:true,remaining_usd:"0.00"}); await u.run("loadDeepseekStatus()");
  assert.equal(u.element("create-button").disabled, false);
  await u.submit(); assert.equal(u.posts()[0].analysis_provider,"deepseek_plan");
  u.data.ready=false; await u.run("refresh()");
  assert.equal(u.element("create-button").disabled, true);
  assert.equal(u.checks().length, 0);
  assert(!u.data.calls.some(call=>/balance|spending/.test(call.url)));
});

test("fallback warning is surfaced safely from the completed job plan", async () => {
  const u = await ui();
  u.data.jobs.push({id: "done-hybrid", source_name: "Серия.mp4", status: "completed", stage: "completed", analysis_provider: "hybrid", files: []});
  await u.run("refresh()"); await new Promise((resolve) => setImmediate(resolve));
  assert.equal(u.element("quality-warnings").hidden, false);
  assert.match(u.element("quality-warning-list").children[0].textContent, /DeepSeek недоступен/);
  assert.equal(u.checks().length, 0);
  assert(!script.includes("innerHTML"));
});

test("retry and checkpoint display make no balance or spending requests", async () => {
  const u = await ui();
  u.data.jobs.push({id: "failed-cloud", source_name: "Серия.mp4", status: "failed", stage: "rendering", analysis_provider: "deepseek_plan", files: []});
  await u.run('selectJob("failed-cloud")');
  assert.equal(u.element("retry-button").hidden,false);
  await u.element("retry-button").listeners.click();
  assert(u.data.calls.some(call=>call.url==="/api/jobs/failed-cloud/retry"&&call.method==="POST"));
  assert(!u.data.calls.some(call=>/balance|spending|reset-budget/.test(call.url)));
  assert.equal(u.checks().length, 0);
  u.run('renderJob({id:"complete",status:"completed",stage:"completed",progress:1,analysis_provider:"local",files:[]})');
  assert(u.stageElements.every(node=>node.classList.contains("done")));
  assert(!/\.job-completed \.stages\s*,/.test(css));
  assert.match(css,/\.job-completed #job-message,\.job-completed \.progress-heading\{display:none\}/);
});

test('timeline covers kept and omitted footage and reviews the exact original interval', async () => {
  const u=await ui();
  assert.doesNotMatch(html.match(/<input id="source-limit"[^>]*>/)?.[0] ?? '',/checked/);
  u.data.plan={source:{duration:100}, parts:[{index:1,cuts:[{start:10,end:20},{start:25,end:30}]},{index:2,cuts:[{start:60,end:90}]}]};
  u.data.jobs.push({id:'timeline-job',source_name:'Серия.mp4',status:'completed',stage:'completed',analysis_provider:'local',files:[]});
  await u.run('refresh()'); await new Promise(resolve=>setImmediate(resolve));
  assert.equal(u.element('timeline-panel').hidden,false);
  assert.equal(u.element('timeline-overview').children.length,7);
  assert.equal(u.element('timeline-groups').children.length,2);
  u.element('timeline-zoom').value='4'; u.element('timeline-zoom').listeners.change();
  assert.equal(u.element('timeline-map').style.width,'400%');
  assert.equal(u.run('sourceTime(59.999)'), '01:00.00');
  assert(!html.includes('timeline-detail'));
  assert.equal(u.element('timeline-groups').children[0].getAttribute('aria-pressed'),'true');
  u.element('timeline-overview').children[2].listeners.click();
  u.element('source-player').listeners.loadedmetadata();
  assert.match(u.element('source-selection').textContent,/Убрано · исходник 00:20.00–00:25.00/);
  assert.equal(u.element('source-player').src,'http://127.0.0.1:8765/api/jobs/timeline-job/source');
  assert.equal(u.element('source-player').currentTime,20);
  assert.equal(u.element('source-player').paused,false);
  u.element('source-player').currentTime=25.1; u.element('source-player').listeners.timeupdate();
  assert.equal(u.element('source-player').paused,false);
  u.element('source-player').currentTime=60; u.element('source-player').listeners.timeupdate();
  assert.equal(u.element('source-player').paused,false);
  u.element('source-limit').checked=true;
  u.element('source-player').listeners.timeupdate();
  assert.equal(u.element('source-player').paused,true);
  u.element('source-full-button').listeners.click();
  assert.equal(u.element('source-player').paused,false);
  u.element('source-player').currentTime=60; u.element('source-player').listeners.timeupdate();
  assert.equal(u.element('source-player').paused,false);
  u.element('timeline-groups').children[1].listeners.click();
  assert.equal(u.element('timeline-groups').children[0].getAttribute('aria-pressed'),'false');
  assert.equal(u.element('timeline-groups').children[1].getAttribute('aria-pressed'),'true');
  assert.equal(u.checks().length,0);
});

test('analysis debug is optional, clips evidence to kept footage and uses the existing source player', async()=>{
  const u=await ui();
  assert.doesNotMatch(html.match(/<input id="analysis-debug"[^>]*>/)?.[0] ?? '',/checked/);
  u.data.plan={source:{duration:100},parts:[{index:1,cuts:[{start:10,end:20},{start:25,end:30}]}],
    debug_timeline:{available:true,reasons:[
      {start:4,end:28,kind:'reaction',title:'Ответ героя',detail:'Эмоциональная реакция.'},
      {start:15,end:18,kind:'story',title:'Причина действия',detail:'Продолжает разговор.'}]}};
  u.data.jobs.push({id:'debug-job',status:'completed',stage:'completed',files:[]});
  await u.run('refresh()');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(u.element('analysis-debug-lane').hidden,true);
  const timelineCount=u.element('timeline-overview').children.length;
  u.element('analysis-debug').checked=true;u.element('analysis-debug').listeners.change();
  const reasons=u.element('analysis-debug-lane').children;
  assert.equal(reasons.length,3);
  assert.equal(reasons[0].style.left,'10%');assert.equal(reasons[0].style.width,'10%');
  assert.equal(reasons[1].style.top,'25px');assert.equal(reasons[2].style.left,'25%');
  reasons[1].listeners.mouseenter();
  assert.match(u.element('analysis-debug-title').textContent,/00:15.00–00:18.00/);
  reasons[2].listeners.click();u.element('source-player').listeners.loadedmetadata();
  assert.equal(u.element('source-player').currentTime,25);
  assert.equal(u.element('source-player').paused,false);
  u.element('analysis-debug').checked=false;u.element('analysis-debug').listeners.change();
  assert.equal(u.element('analysis-debug-lane').hidden,true);
  assert.equal(u.element('source-player').currentTime,25);assert.equal(u.element('source-player').paused,false);
  assert.equal(u.element('timeline-overview').children.length,timelineCount);
});

test('debug text is literal and malformed or missing evidence is unavailable', async()=>{
  const u=await ui();
  const injected='<img src=x onerror=alert(1)>';
  u.data.plan={source:{duration:50},parts:[{index:1,cuts:[{start:10,end:20}]}],
    debug_timeline:{available:true,reasons:[
      {start:10,end:15,kind:'manual',title:injected,detail:injected},
      {start:10,end:15,kind:'<script>',title:'x',detail:'x'},
      {start:-1,end:15,kind:'story',title:'x',detail:'x'},
      {start:10,end:51,kind:'story',title:'x',detail:'x'},
      {start:'10',end:15,kind:'story',title:'x',detail:'x'}]}};
  u.data.jobs.push({id:'safe-debug',status:'completed',stage:'completed',files:[]});
  await u.run('refresh()');await new Promise(resolve=>setImmediate(resolve));
  u.element('analysis-debug').checked=true;u.element('analysis-debug').listeners.change();
  assert.equal(u.element('analysis-debug-lane').children.length,1);
  u.element('analysis-debug-lane').children[0].listeners.focus();
  assert.equal(u.element('analysis-debug-detail').textContent,injected);
  assert.equal(u.element('analysis-debug-detail').children.length,0);
  u.data.plan.debug_timeline={available:false,reasons:[]};u.element('analysis-debug').listeners.change();
  assert.equal(u.element('analysis-debug-lane').children.length,0);
  assert.match(u.element('analysis-debug-title').textContent,/недоступны/);
});

test('debug combines adjacent identical proof but preserves source gaps and part boundaries',async()=>{
  const u=await ui();
  u.data.plan={source:{duration:100},parts:[{cuts:[{start:10,end:30},{start:35,end:40}]},{cuts:[{start:40,end:45}]}],
    debug_timeline:{available:true,reasons:[
      {event_id:'one',kind:'atmosphere',title:'Пауза',detail:'Та же причина',start:10,end:15},
      {event_id:'one',kind:'atmosphere',title:'Пауза',detail:'Та же причина',start:15,end:20},
      {event_id:'one',kind:'atmosphere',title:'Пауза',detail:'Та же причина',start:25,end:45},
      {event_id:'one',kind:'reaction',title:'Реакция',detail:'Другая причина',start:20,end:25}]}};
  u.data.jobs.push({id:'merged-debug',status:'completed',stage:'completed',files:[]});
  await u.run('refresh()');await new Promise(resolve=>setImmediate(resolve));
  const pieces=JSON.parse(JSON.stringify(u.run('debugPieces(state.timeline.plan)')));
  assert.deepEqual(pieces.map(p=>[p.start,p.end,p.kind]),[
    [10,20,'atmosphere'],[20,25,'reaction'],[25,30,'atmosphere'],[35,40,'atmosphere'],[40,45,'atmosphere']]);
});

test('current quality summary separates review warnings from profile information',async()=>{
  const u=await ui();
  u.data.plan={warnings:['STALE_REMOVED_ED'],quality_summary:{available:true,
    warnings:[{text:'Проверьте переход',category:'review',event_id:'one'}],
    notes:[{text:'Атмосфера сохранена выбранным профилем',category:'profile',event_id:'one'}]}};
  u.data.jobs.push({id:'quality-filtered',status:'completed',stage:'completed',files:[]});
  await u.run('refresh()');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(u.element('quality-warning-list').children.length,1);
  assert.equal(u.element('quality-warning-list').children[0].textContent,'Проверьте переход');
  assert.equal(u.element('quality-notes').hidden,false);
  assert.equal(u.element('quality-note-list').children[0].textContent,'Атмосфера сохранена выбранным профилем');
  assert.match(u.element('quality-summary').textContent,/замечаний: 1/);
  assert.equal(u.checks().length,0);
});

test('MP4 save uses the selected registered file and disables both actions while choosing a folder',async()=>{
  const u=await ui();
  const files=[1,2].map(n=>({name:`part_00${n}.mp4`,url:`/api/jobs/save-job/files/part_00${n}.mp4`,subtitle_url:`/api/jobs/save-job/files/part_00${n}.srt`}));
  u.data.jobs.push({id:'save-job',status:'completed',stage:'completed',files});
  await u.run('refresh()');await new Promise(resolve=>setImmediate(resolve));u.run('selectFile(1,false)');
  assert.equal(u.element('download-video').disabled,false);
  let finish;u.data.saveHandler=()=>new Promise(resolve=>{finish=resolve;});
  const saving=u.element('download-video').listeners.click();
  assert.equal(u.element('download-video').disabled,true);assert.equal(u.element('download-all').disabled,true);
  assert.match(u.element('download-status').textContent,/Выберите папку/);
  const calls=u.data.calls.filter(c=>c.url.endsWith('/save-videos'));
  assert.equal(calls.length,1);assert.deepEqual(JSON.parse(calls[0].body),{filename:'part_002.mp4'});
  finish({cancelled:false,count:1,files:['part_002.mp4']});await saving;
  assert.match(u.element('download-status').textContent,/MP4 сохранён/);
  assert.equal(u.element('download-video').disabled,false);assert.equal(u.element('download-all').disabled,false);
  assert.equal(u.element('download-subtitle').href,'http://127.0.0.1:8765/api/jobs/save-job/files/part_002.srt');
  assert.equal(u.checks().length,0);
});

test('save all copies separate videos to a chosen folder and reports cancellation or errors',async()=>{
  const u=await ui();
  u.data.jobs.push({id:'save-all-job',status:'completed',stage:'completed',files:Array.from({length:14},(_,i)=>({name:`part_${i+1}.mp4`,url:`/api/jobs/save-all-job/files/part_${i+1}.mp4`}))});
  await u.run('refresh()');await new Promise(resolve=>setImmediate(resolve));
  u.data.saveResult={cancelled:false,count:14,files:Array.from({length:14},(_,i)=>`part_${i+1}.mp4`)};
  await u.element('download-all').listeners.click();
  assert.deepEqual(JSON.parse(u.data.calls.find(c=>c.url.endsWith('/save-videos')).body),{all:true});
  assert.match(u.element('download-status').textContent,/сохранено видео: 14/);
  assert(!u.data.calls.some(c=>/zip|download-all|download-folder/.test(c.url)));
  u.data.saveResult={cancelled:true,count:0,files:[]};await u.element('download-all').listeners.click();
  assert.equal(u.element('download-status').textContent,'Сохранение отменено.');
  u.data.saveError='Выбранная папка недоступна.';await u.element('download-video').listeners.click();
  assert.match(u.element('download-status').textContent,/Не удалось сохранить видео: Выбранная папка недоступна/);
  assert.equal(u.element('download-video').disabled,false);assert.equal(u.element('download-all').disabled,false);
});

test('partial save failure reports the retained receipt and an incomplete success is not claimed as all files',async()=>{
  const u=await ui();
  u.data.jobs.push({id:'save-partial',status:'completed',stage:'completed',files:[1,2].map(n=>({name:`part_00${n}.mp4`,url:`/api/jobs/save-partial/files/part_00${n}.mp4`}))});
  await u.run('refresh()');await new Promise(resolve=>setImmediate(resolve));
  u.data.saveFailure={cancelled:false,count:1,files:['part_001.mp4'],error:'Недостаточно места в выбранной папке.'};
  await u.element('download-all').listeners.click();
  assert.match(u.element('download-status').textContent,/Успели сохранить видео: 1/);
  assert.match(u.element('download-status').textContent,/Недостаточно места/);
  delete u.data.saveFailure;u.data.saveResult={cancelled:false,count:1,files:['part_001.mp4']};
  await u.element('download-all').listeners.click();
  assert.match(u.element('download-status').textContent,/не подтвердил сохранение/);
  assert.equal(u.element('download-all').disabled,false);
});

test('library opens projects then scoped episodes and separate editing/review screens', async()=>{
  const u=await ui();
  const settings={analysis_provider:'local',layout:'cinema',caption_style:'accent'};
  u.data.jobs=[{id:'ready-1',source_name:'one.mp4',status:'completed',stage:'completed',files:[],episode_id:'e1'},
    {id:'ready-2',source_name:'two.mp4',status:'completed',stage:'completed',files:[],episode_id:'e2'}];
  await u.run('refresh()');
  await u.installLibrary({projects:[{id:'p1',title:'Первое аниме'},{id:'p2',title:'Другое аниме'}],episodes:[
    {id:'e1',project_id:'p1',number:1,title:'Серия 1',source_id:'source-1',settings,jobs:[{id:'ready-1'}]},
    {id:'e2',project_id:'p2',number:1,title:'Серия 1',source_id:'source-2',settings,jobs:[{id:'ready-2'}]}]});
  assert.equal(u.element('projects-screen').hidden,false);
  assert.equal(u.element('edit-screen').hidden,true);
  assert.equal(u.element('review-screen').hidden,true);
  assert.equal(u.element('project-cards').children.length,2);
  await u.run("location.hash='#project/p1'; libraryUI.route()");
  assert.equal(u.element('episode-cards').children.length,1);
  assert.equal(u.element('episode-number').value,'2');
  await u.run("location.hash='#episode/e1/edit'; libraryUI.route()");
  assert.equal(u.element('edit-screen').hidden,false);
  assert.equal(u.element('review-screen').hidden,true);
  assert.equal(u.element('source').disabled,true);
  await u.run("location.hash='#episode/e1/review/ready-2'; libraryUI.route()");
  assert.equal(u.run('state.selected'),'ready-1'); // Foreign-episode requested job is ignored.
  assert.equal(u.element('review-screen').hidden,false);
  assert.equal(u.element('edit-screen').hidden,true);
  assert.equal(u.element('episode-attempt').children.length,1);
  await u.run("location.hash='#projects'; libraryUI.route()");
  assert.equal(u.run('state.selected'),null);
  assert.equal(u.element('source-player').paused,true);
  assert.equal(u.checks().length,0);
});

test('episode save is free and launch uses the episode endpoint with saved settings', async()=>{
  const u=await ui();
  await u.installLibrary({projects:[{id:'p',title:'Аниме'}],episodes:[{id:'e',project_id:'p',number:1,title:'Серия 1',source_id:null,settings:{analysis_provider:'local',layout:'cinema',caption_style:'accent'},jobs:[]}]});
  await u.run("location.hash='#episode/e/edit'; libraryUI.route()");
  assert.equal(u.element('source').value,'');
  u.element('source').value='source-1';
  await u.run('libraryUI.save()');
  assert.equal(u.data.jobs.length,0);
  assert.equal(u.element('source').disabled,true);
  await u.run('libraryUI.launch()');
  assert.equal(u.data.jobs[0].episode_id,'e');
  assert.equal(u.data.jobs[0].layout,'cinema');
  assert.equal(u.posts().length,0);
  u.data.jobs[0].status='completed'; u.data.jobs[0].stage='completed';
  await u.run('refresh()');
  assert.equal(u.run('location.hash'),'episode/e/review/episode-job');
  assert.equal(u.checks().length,0);
});

test('delete controls hide episodes/projects and trash restores scoped results without processing', async()=>{
  const u=await ui();
  const settings={analysis_provider:'local',layout:'cinema',caption_style:'accent'};
  u.data.jobs=[{id:'done',episode_id:'e',status:'completed',stage:'completed',source_name:'one.mp4',files:[]}];
  await u.run('refresh()');
  await u.installLibrary({projects:[{id:'p',title:'Аниме'}],episodes:[{id:'e',project_id:'p',number:1,title:'Серия 1',source_id:'source-1',settings,jobs:[{id:'done'}]}]});
  await u.run("location.hash='#episode/e/edit'; libraryUI.route()");
  await u.element('delete-current-episode').listeners.click();
  assert.equal(u.run('libraryUI.view'),'episodes');
  assert.equal(u.element('episode-cards').children.length,0);
  await u.run("location.hash='#episode/e/review'; libraryUI.route()");
  assert.equal(u.run('libraryUI.view'),'projects');
  await u.run("location.hash='#trash'; libraryUI.route()");
  assert.equal(u.element('trash-screen').hidden,false);
  assert.equal(u.element('trash-cards').children.length,1);
  await u.element('trash-cards').children[0].children[2].listeners.click();
  assert.equal(u.element('trash-cards').children.length,0);
  await u.run("location.hash='#episode/e/review'; libraryUI.route()");
  assert.equal(u.run('state.selected'),'done');
  await u.run("location.hash='#project/p'; libraryUI.route()");
  await u.element('delete-current-project').listeners.click();
  assert.equal(u.element('project-cards').children.length,0);
  await u.run("location.hash='#episode/e/edit'; libraryUI.route()");
  assert.equal(u.run('libraryUI.view'),'projects');
  await u.run("location.hash='#trash'; libraryUI.route()");
  assert.equal(u.element('trash-cards').children.length,1);
  await u.element('trash-cards').children[0].children[2].listeners.click();
  await u.run("location.hash='#project/p'; libraryUI.route()");
  assert.equal(u.element('episode-cards').children.length,1);
  u.data.jobs[0].status='running'; await u.run('refresh()');
  assert.equal(u.element('delete-current-project').disabled,true);
  await u.run("location.hash='#episode/e/edit'; libraryUI.route()");
  assert.equal(u.element('delete-current-episode').disabled,true);
  assert.equal(u.data.calls.filter(c=>c.method==='POST' && (c.url.endsWith('/jobs') || (c.url.includes('deepseek') && !c.url.startsWith('/api/deepseek/balance?')))).length,0);
  assert.equal(u.element('source-player').paused,true);
});
