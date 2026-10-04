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
const libraryScript = fs.readFileSync(path.join(staticDir, 'library.js'), 'utf8');

class Element {
  constructor() {
    this.children = []; this.attrs = {}; this.value = ""; this.textContent = "";
    this.hidden = false; this.disabled = false; this.className = ""; this.listeners = {};
    this.style = {}; this.currentTime = 0;
    this.classList = {contains: (name) => this.className.split(" ").includes(name), toggle: () => {}};
  }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return this.attrs[name]; }
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
  element("analysis-provider").value = "deepseek_plan";
  element("layout").value = "cinema";
  element("caption-style").value = "accent";
  const data = {
    status: {configured: true, budget_usd: null, remaining_usd: "1.00", charged_ceiling_usd: "0.0000789", model: "deepseek-flash", ...options.status},
    statusError: false, ready: true, jobs: [], calls: [],
    connection: {available: true, vision_supported: true, model: "deepseek-flash", balance_infos: [{currency: "USD", total_balance: "1.00"}]},
    providerBalance:{balance_usd:'1.00',observed_decrease_usd:'0.03',measured_at:1770000000,stale:false,scope:'account'},
  };
  const context = vm.createContext({
    console, URL, location: {origin: "http://127.0.0.1:8765", hash:'#projects'}, setInterval: () => {}, addEventListener:()=>{},
    document: {getElementById: element, createElement: tag => {const e=new Element(); e.tagName=tag.toUpperCase(); return e;}, querySelectorAll: () => Array.from({length: 5}, () => new Element())},
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
    data, element, run,
    async installLibrary(data) { this.data.library=data; vm.runInContext(libraryScript,context); await new Promise(resolve=>setImmediate(resolve)); },
    choose(provider) { element("analysis-provider").value = provider; run("renderProvider()"); },
    submit() { return element("create-form").listeners.submit({preventDefault() {}}); },
    checks() { return data.calls.filter((call) => call.url === "/api/deepseek/check"); },
    posts() { return data.calls.filter((call) => call.url === "/api/jobs" && call.method === "POST").map((call) => JSON.parse(call.body)); },
  };
}

test("funded studio defaults to DeepSeek plan and cinema; local remains explicit and free", async () => {
  const u = await ui();
  assert.match(html, /<option value="deepseek_plan" selected>/);
  assert.match(html, /<option value="hybrid">Локально \+ DeepSeek при сомнениях/);
  assert.match(html, /<option value="deepseek_plan" selected>DeepSeek/);
  assert.equal(u.run("analysisProvider()"), "deepseek_plan");
  assert.equal(u.element("deepseek-budget").textContent, "Без общего лимита");
  assert.equal(u.element("deepseek-remaining").textContent, "$1.00");
  assert.equal(u.element("deepseek-charged").textContent, "$0.03");
  assert.equal(u.element("deepseek-notice").hidden, false);
  await u.submit();
  assert.equal(u.posts()[0].analysis_provider, "deepseek_plan");
  assert.equal(u.posts()[0].layout, "cinema");
  assert.equal(u.posts()[0].caption_style, "accent");
  u.choose("local"); await u.submit();
  assert.equal(u.posts()[1].analysis_provider, "local");
  assert.equal(u.checks().length, 0);
});

test('provider balance is primary; failed refresh retains dated observation, never a price estimate',async()=>{
  const u=await ui();
  assert.equal(u.element('deepseek-charged').textContent,'$0.03');
  u.data.balanceError=true;
  await u.run('refreshBalance(true)');
  assert.equal(u.element('deepseek-charged').textContent,'$0.03');
  assert.match(u.element('provider-balance-time').textContent,/обновление не удалось/);
  assert.match(html,/не отдельного API-ключа/);
  assert.equal(u.posts().length,0);
});

test('attempt reset cannot relabel previous balance decrease as new attempt spending',async()=>{
  const u=await ui();
  u.data.jobs.push({id:'done',status:'completed',stage:'completed',analysis_provider:'deepseek_plan',files:[]});
  await u.run('selectJob("done")');
  await u.run('state.providerBalanceJobId="done"; state.providerBalance={attempt:1,window:{decrease_usd:"0.03",coverage:"full_attempt",measured_at:1770000000}}; renderSpending(state.selectedJob,{attempt:2,charged_ceiling_usd:"0",limit_usd:"0.10",job_total_usd:"0.08"})');
  assert.match(u.element('job-spending').textContent,/нет измерения/);
  assert.doesNotMatch(u.element('job-spending').textContent,/\$0.03/);
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

test("hybrid can start without key, balance or cloud status; cloud mode remains gated", async () => {
  const u = await ui({status: {configured: false, remaining_usd: "0.00"}});
  u.choose("hybrid");
  assert.equal(u.element("create-button").disabled, false);
  assert.equal(u.element("deepseek-notice").hidden, false);
  assert.equal(u.element("hybrid-fallback").hidden, false);
  assert.match(u.element("provider-description").textContent, /ниже 75%/);
  assert.match(u.element("provider-description").textContent, /самооценка модели, не гарантия точности/);
  assert.match(u.element("deepseek-config").textContent, /продолжится локально с предупреждением/);
  await u.submit();
  assert.equal(u.posts()[0].analysis_provider, "hybrid");
  assert.match(u.element("job-provider").textContent, /локально \+ DeepSeek при сомнениях/);
  u.choose("deepseek"); assert.equal(u.element("create-button").disabled, true);
  u.choose("hybrid"); u.data.statusError = true; await u.run("loadDeepseekStatus()");
  assert.equal(u.element("create-button").disabled, false);
  assert.equal(u.checks().length, 0);
});

test("all four modes are sent explicitly; cloud check occurs only on explicit button click", async () => {
  const u = await ui();
  for (const provider of ["local", "hybrid", "deepseek", "deepseek_plan"]) {
    u.choose(provider); assert.equal(u.element("create-button").disabled, false); await u.submit();
  }
  assert.deepEqual(u.posts().map((post) => post.analysis_provider), ["local", "hybrid", "deepseek", "deepseek_plan"]);
  assert.equal(u.checks().length, 0);
  await u.element("deepseek-check").listeners.click();
  assert.equal(u.checks().length, 1);
  assert.match(u.element("deepseek-check-message").textContent, /не является расходом отдельного ключа/);
  assert(u.data.calls.every((call) => call.url.startsWith("/api/")));
});

test("hybrid survives failed cloud check, but full cloud does not; local runtime is still required", async () => {
  const u = await ui();
  u.choose("hybrid"); u.data.connection.available = false;
  await u.element("deepseek-check").listeners.click();
  assert.equal(u.element("create-button").disabled, false);
  u.choose("deepseek"); assert.equal(u.element("create-button").disabled, true);
  u.choose("deepseek_plan"); assert.equal(u.element("create-button").disabled, true);
  u.choose("hybrid"); u.data.ready = false; await u.run("refresh()");
  assert.equal(u.element("create-button").disabled, true);
  u.choose("local"); assert.equal(u.element("create-button").disabled, true);
});

test("retry uses the saved provider, and history distinguishes all four modes", async () => {
  const u = await ui({status: {remaining_usd: "0.00"}});
  u.data.jobs = [
    {id: "hybrid-job", source_name: "Серия.mp4", status: "failed", stage: "framing", analysis_provider: "hybrid", files: []},
    {id: "cloud-job", source_name: "Серия.mp4", status: "failed", stage: "framing", analysis_provider: "deepseek", files: []},
    {id: "plan-job", source_name: "Серия.mp4", status: "failed", stage: "framing", analysis_provider: "deepseek_plan", files: []},
    {id: "local-job", source_name: "Серия.mp4", status: "failed", stage: "framing", analysis_provider: "local", files: []},
  ];
  await u.run("refresh()");
  assert.match(u.element("history-list").children[0].children[1].children[0].textContent, /Локально \+ DeepSeek/);
  assert.match(u.element("history-list").children[1].children[1].children[0].textContent, / · DeepSeek$/);
  assert.match(u.element("history-list").children[2].children[1].children[0].textContent, /DeepSeek: сюжет · кадр локально/);
  assert.equal(u.element("history-list").children[3].children[1].children[0].textContent, "Ошибка");
  u.choose("deepseek"); await u.run('selectJob("hybrid-job")');
  assert.equal(u.element("retry-button").disabled, false);
  u.choose("hybrid"); await u.run('selectJob("cloud-job")');
  assert.equal(u.element("retry-button").disabled, true);
  await u.run('selectJob("plan-job")'); assert.equal(u.element("retry-button").disabled, true);
  assert.match(u.element("job-provider").textContent, /DeepSeek — сюжет и план, платно · кадрирование, монтаж и экспорт локально/);
  await u.run('selectJob("local-job")'); assert.equal(u.element("retry-button").disabled, false);
  u.data.status.remaining_usd = "1.00"; await u.run("loadDeepseekStatus()");
  await u.run('selectJob("plan-job")'); assert.equal(u.element("retry-button").disabled, false);
  await u.run('selectJob("cloud-job")'); assert.equal(u.element("retry-button").disabled, false);
});

test("DeepSeek plan mode explains local framing and requires confirmed cloud availability", async () => {
  const u = await ui();
  u.choose("deepseek_plan");
  assert.equal(u.element("deepseek-notice").hidden, false);
  assert.equal(u.element("hybrid-fallback").hidden, true);
  assert.match(u.element("provider-description").textContent, /события, заставки и титры/);
  assert.match(u.element("provider-description").textContent, /Распознавание речи, кадрирование, монтаж и экспорт выполняются на компьютере/);
  assert.match(u.element("deepseek-notice-description").textContent, /в платный сервис передаются исходные кадры серии и распознанные реплики/);
  assert.match(u.element("deepseek-notice-description").textContent, /DeepSeek не используется для обрезки кадра/);
  assert.match(u.element("storage-description").textContent, /Кадрирование и экспорт выполняются локально/);
  for (const status of [{configured: false}, {configured: true, remaining_usd: "0.00"}, {remaining_usd: undefined}]) {
    Object.assign(u.data.status, status); await u.run("loadDeepseekStatus()");
    assert.equal(u.element("create-button").disabled, true);
    await u.submit(); assert.equal(u.posts().length, 0);
  }
  Object.assign(u.data.status, {configured: true, remaining_usd: "1.00"}); await u.run("loadDeepseekStatus()");
  assert.equal(u.element("create-button").disabled, false);
  u.data.statusError = true; await u.run("loadDeepseekStatus()");
  assert.equal(u.element("create-button").disabled, true);
  assert.equal(u.checks().length, 0);
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

test("unknown provider cost after balance adjustment never renders as zero", async () => {
  const u=await ui();
  assert.equal(u.run('usd(null)'), 'Неизвестно');
  assert.equal(u.run('usd(undefined)'), 'Неизвестно');
  assert.equal(u.run('usd("")'), 'Неизвестно');
  assert.equal(u.run('usd("0.00")'), '$0.00');
  u.run('state.providerBalance={balance_usd:"2.00",observed_decrease_usd:null,adjusted:true,measured_at:1791040000}; renderBalance()');
  assert.equal(u.element('deepseek-charged').textContent,'Неизвестно');
  assert.match(u.element('provider-balance-time').textContent,/корректировался/);
});

test("uncapped attempt keeps spending history and has no budget reset control", async () => {
  const u = await ui();
  u.data.jobs.push({id: "done-cloud", source_name: "Серия.mp4", status: "completed", stage: "completed", analysis_provider: "deepseek_plan", files: []});
  await u.run("refresh()"); await new Promise((resolve) => setImmediate(resolve));
  assert.equal(u.element("reset-budget-button").hidden, true);
  assert.match(u.element("job-spending").textContent, /Попытка 1 · расход по балансу: нет измерения/);
  assert.match(u.element("job-budget-estimate").textContent, /Верхняя оценка по токенам: \$0.08/);
  assert.match(u.element("job-budget-estimate").textContent, /все попытки: \$0.08/);
  assert.doesNotMatch(u.element("processing-note").textContent, /0[.,]10|0[.,]1 /);
  assert.equal(u.data.calls.filter((call) => call.url.endsWith('/reset-budget')).length, 0);
  assert.equal(u.checks().length, 0);
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
