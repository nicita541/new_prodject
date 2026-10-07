"use strict";

const $ = (id) => document.getElementById(id);
const state = {health: null, sources: [], jobs: [], selected: null, selectedJob: null, files: [], fileIndex: 0, busyAction: false, uploading: false, historyKey: "", filesKey: "", polling: false, planWarnings: new Map(), qualityJobId: null, qualityRenderedKey: "", deepseek: null, deepseekError: null, checkingDeepseek: false, deepseekCheck: null};
const statuses = {queued: "В очереди", running: "В работе", completed: "Готово", failed: "Ошибка", cancelled: "Отменено", interrupted: "Прервано"};
const timelineColors = ['#edb884', '#8ec3a8', '#91b4df', '#ca9cca', '#d8c978'];
state.timelineKey = ''; state.timeline = null; state.sourceSelection = null;
state.savingVideos=false;
const stages = {queued: "Ожидание", prepare: "Подготовка видео", preparing: "Подготовка видео", probe: "Проверка видео", audio: "Подготовка звука", transcribe: "Распознавание русской речи", transcribing: "Распознавание русской речи", transcript: "Распознавание русской речи", speech: "Распознавание русской речи", shots: "Поиск смены планов", analyze: "Анализ сюжета и изображения", analyzing: "Анализ сюжета и изображения", analysis: "Анализ сюжета и изображения", events: "Анализ сюжета и изображения", condense: "Сокращение сюжета с сохранением контекста", framing: "Кадрирование говорящих и действия", focus: "Кадрирование говорящих и действия", plan: "Составление монтажного плана", planning: "Составление монтажного плана", render: "Экспорт частей", rendering: "Экспорт частей", completed: "Монтаж завершён", done: "Монтаж завершён"};
const checkpointStages = ["prepare", "transcribe", "analyze", "condense", "framing", "plan", "render"];
const stageGroup = {prepare: 0, preparing: 0, probe: 0, audio: 0, transcribe: 1, transcribing: 1, transcript: 1, speech: 1, scenes: 0, shots: 0, analyze: 2, analyzing: 2, analysis: 2, events: 2, condense: 3, framing: 4, focus: 4, planning: 5, plan: 5, rendering: 6, render: 6, completed: 7, done: 7};

function setText(id, text) { $(id).textContent = text ?? ""; }
stages.scenes = "Поиск смены планов";
function humanSize(bytes) { return Number.isFinite(Number(bytes)) ? `${(Number(bytes) / 1024 / 1024).toFixed(1)} МБ` : ""; }
function humanDuration(seconds) { const n = Math.round(Number(seconds)); return Number.isFinite(n) && n > 0 ? `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}` : ""; }
function dateLabel(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("ru-RU", {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"}); }
function safeUrl(value) { try { const url = new URL(value, location.origin); return url.origin === location.origin && url.pathname.startsWith("/api/jobs/") ? url.href : null; } catch { return null; } }
function analysisProvider() { const select = $("analysis-provider"); if (["deepseek", "hybrid"].includes(select.value) || !["deepseek_plan", "local"].includes(select.value)) select.value = "deepseek_plan"; return select.value; }
function editingOptions() { return {layout: $("layout").value === "portrait" ? "portrait" : "cinema", caption_style: $("caption-style").value === "classic" ? "classic" : "accent"}; }
function renderEditing() {
  const options = editingOptions();
  $("style-preview").className = `style-preview ${options.layout} ${options.caption_style}`;
  setText("preview-subtitle", options.caption_style === "accent" ? "ИСТОРИЯ\nНАЧИНАЕТСЯ ЗДЕСЬ" : "История\nначинается здесь");
  setText("layout-description", options.layout === "cinema" ? "Все персонажи в кадре. Размытый фон заполняет 9:16." : "Фокус на говорящем или действии. Обработка дольше; проверьте положение лиц.");
}
function providerLabel(provider) { return provider === "deepseek_plan" ? "DeepSeek: сюжет · кадр локально" : provider === "hybrid" ? "Локально + DeepSeek" : provider === "deepseek" ? "DeepSeek" : "На компьютере"; }
function usd(value) { if (value === null || value === undefined || value === "") return "Неизвестно"; const amount = Number(value); return Number.isFinite(amount) && amount >= 0 ? `$${amount.toFixed(8).replace(/0+$/, "").replace(/\.$/, ".00")}` : "Неизвестно"; }
state.providerBalance=null; state.balanceBusy=false; state.balanceNextRefresh=0;
function balanceTime(value) { return value ? new Date(value*1000).toLocaleString('ru-RU') : 'нет проверки'; }
function renderBalance() {}
function renderSpending() {}
async function refreshBalance() {}
function providerReady(provider) {
  if (!state.health?.ready) return false;
  if (!["deepseek", "deepseek_plan"].includes(provider)) return true;
  return state.deepseek?.configured === true && !state.checkingDeepseek;
}
async function api(path, options = {}) {
  const response = await fetch(path, {cache: "no-store", ...options});
  let body;
  try { body = await response.json(); } catch { throw new Error("Сервер вернул неожиданный ответ."); }
  if (!response.ok) { const message = body.detail ?? body.message; throw new Error(typeof message === "string" ? message : `Ошибка сервера (${response.status}).`); }
  return body;
}
function updateControls() {
  $("create-button").disabled = !providerReady(analysisProvider()) || !!state.health?.busy || !$("source").value || state.busyAction || state.uploading;
  $("upload-button").disabled = state.uploading || state.busyAction;
  $("source").disabled = state.uploading || state.busyAction || !!state.navigation?.episode?.source_id;
  if(state.navigation?.episode?.source_id) $('upload-button').disabled=true;
  if(state.navigation) { $('upload-button').hidden=!!state.navigation.episode?.source_id; $('refresh-sources').hidden=!!state.navigation.episode?.source_id; }
  $("analysis-provider").disabled = state.uploading || state.busyAction;
  $("layout").disabled = state.uploading || state.busyAction;
  $("caption-style").disabled = state.uploading || state.busyAction;
  $("refresh-sources").disabled = state.uploading;
  if (state.health?.busy) $("create-button").textContent = "Сначала завершится текущий монтаж";
  else $("create-button").textContent = state.busyAction ? "Запускаем…" : state.navigation ? (state.navigation.attempts().length ? 'Запустить новый монтаж' : 'Запустить монтаж') : "Создать шортсы ↗";
  const active = state.selectedJob && ["queued", "running"].includes(state.selectedJob.status);
  $("cancel-button").disabled = state.busyAction || !!state.selectedJob?.cancel_requested;
  $("retry-button").disabled = state.busyAction || !providerReady(state.selectedJob?.analysis_provider ?? "local") || !!state.health?.busy;
  $("reset-budget-button").disabled = state.busyAction || !!state.health?.busy;
  $("cancel-button").textContent = active && state.selectedJob.cancel_requested ? "Отмена запрошена…" : "Отменить";
  $("deepseek-check").disabled = state.deepseek?.configured !== true || state.checkingDeepseek || state.busyAction;
  $("deepseek-check").textContent = state.checkingDeepseek ? "Проверяем подключение…" : "Проверить подключение";
}
function renderProvider() {
  const provider = analysisProvider(), cloud = ["deepseek", "deepseek_plan"].includes(provider), cloudPlan = provider === "deepseek_plan", hybrid = provider === "hybrid";
  setText('processing-note', cloud || hybrid ? `${hybrid ? 'При сомнениях ' : ''}DeepSeek: кадры и реплики через интернет. При сбое — до двух повторов. Экспорт — на компьютере.` : 'Речь, анализ и экспорт на компьютере. Без платных запросов.');
  $("deepseek-notice").hidden = !cloud && !hybrid;
  $("deepseek-details").hidden = !cloud && !hybrid;
  $("hybrid-fallback").hidden = !hybrid;
  setText("provider-description", cloudPlan ? "DeepSeek анализирует события, заставки и титры, сокращает сюжет и составляет план. Распознавание речи, кадрирование, монтаж и экспорт выполняются на компьютере. Требуется интернет. При сбое запрос повторяется ещё до двух раз." : hybrid ? "Локальный анализ первым. DeepSeek вызывается при уверенности в кадрировании ниже 75%, явном сомнении или некорректном ответе. Уверенность — самооценка модели, не гарантия точности." : cloud ? "Кадры и текст отправляются в DeepSeek. Требуется интернет. При сбое запрос повторяется ещё до двух раз." : "Кадры и текст обрабатываются на компьютере, без платных запросов.");
  setText("deepseek-notice-title", hybrid ? "DeepSeek может уточнить сомнительные ответы" : "Кадры и текст отправятся в DeepSeek");
  setText("deepseek-notice-description", cloudPlan ? "Для анализа сюжета и плана в платный сервис передаются исходные кадры серии и распознанные реплики. DeepSeek не используется для обрезки кадра. Оригинальное видео и результаты сохраняются в папке проекта." : hybrid ? "При уточнении в сервис отправляются кадры серии и распознанные реплики. Оригинальное видео и результаты сохраняются в папке проекта." : "Для анализа передаются кадры серии и распознанные реплики. Требуется интернет. Оригинальное видео и результаты сохраняются в папке проекта.");
  setText("storage-title", cloudPlan ? "DeepSeek: сюжет и план · кадрирование локально" : hybrid ? "Локально + DeepSeek при сомнениях" : cloud ? "DeepSeek · анализ через интернет" : "Локальный анализ");
  setText("storage-description", cloudPlan ? "Для нового задания DeepSeek получает кадры и реплики для сюжета и плана через интернет, платно. Кадрирование и экспорт выполняются локально. Все рабочие файлы — в F:\\new_prodject." : hybrid ? "Для нового задания сначала работает локальная модель. При сомнении кадры и текст могут передаваться в DeepSeek через интернет, платно. Без API обработка продолжается локально. Все рабочие файлы — в F:\\new_prodject." : cloud ? "Для нового задания выбран DeepSeek: кадры и текст передаются сервису. Нужен интернет. Оригиналы и результаты хранятся в F:\\new_prodject." : "Для нового задания выбран анализ на компьютере. Видео, модели и результаты хранятся в F:\\new_prodject. После настройки он работает без интернета.");
  setText("deepseek-budget", state.deepseek?.budget_usd === null ? "Без общего лимита" : usd(state.deepseek?.budget_usd));
  renderBalance();
  let config = "Читаем локальную настройку DeepSeek…";
  if (state.deepseekError) config = `Статус DeepSeek недоступен: ${state.deepseekError}`;
  else if (state.deepseek?.configured === false) config = "DeepSeek не настроен. Выберите локальный анализ.";
  else if (state.deepseek?.configured) {
    config = `Подключение настроено · ${state.deepseek.model ?? "DeepSeek"}. При сбое — до двух повторов.`;
  }
  if (state.deepseekCheck?.available === false) config = "Последняя проверка: подключение недоступно. Повторите проверку или выберите локальный анализ.";
  else if (state.deepseekCheck?.vision_supported === false) config = "Проверка не подтвердила поддержку кадров. Доступен локальный анализ.";
  if (hybrid && !providerReady("deepseek")) config = "Уточнение через DeepSeek сейчас не подтверждено. Гибридный режим доступен: обработка продолжится локально с предупреждением, если API не удастся использовать.";
  setText("deepseek-config", config);
  if (state.health) setText("connection-label", state.health.busy ? "Монтаж выполняется" : state.health.ready ? cloud ? "Локальная часть готова" : "Система готова · локально" : "Требуется настройка");
  updateControls();
}
async function loadDeepseekStatus() {
  try { state.deepseek = await api("/api/deepseek"); state.deepseekError = null; }
  catch (error) { state.deepseek = null; state.deepseekError = error.message; }
  renderProvider();
  $("deepseek-recovery").hidden = true;
}
async function checkDeepseek() {
  if ($("deepseek-check").disabled) return;
  state.checkingDeepseek = true; updateControls(); setText("deepseek-check-message", "Проверяем подключение без платного анализа…");
  try {
    const result = await api("/api/deepseek/check", {method: "POST"});
    state.deepseekCheck = result;
    const balances = Array.isArray(result.balance_infos) ? result.balance_infos.map((item) => `${item.currency}: ${item.total_balance}`).join("; ") : "";
    const connection = result.available === true ? "Подключение доступно" : "Подключение недоступно";
    const vision = result.vision_supported === true ? "анализ кадров поддерживается" : result.vision_supported === false ? "модель не поддерживает кадры" : "поддержка кадров не подтверждена";
    setText("deepseek-check-message", `Последняя проверка: ${connection}, ${vision}. Модель: ${result.model ?? "DeepSeek"}.${balances ? ` Баланс аккаунта: ${balances}.` : ""}`);
  } catch (error) { setText("deepseek-check-message", `Не удалось проверить подключение: ${error.message}`); }
  finally { state.checkingDeepseek = false; await loadDeepseekStatus(); updateControls(); }
}
function renderHealth(health) {
  state.health = health;
  $("connection").className = `status-pill${health.ready ? " ready" : ""}`;
  setText("connection-label", health.busy ? "Монтаж выполняется" : health.ready ? "Система готова · локально" : "Требуется настройка");
  const missing = Array.isArray(health.missing) ? health.missing : [];
  $("readiness").hidden = health.ready;
  $("missing-list").replaceChildren(...missing.map((item) => { const li = document.createElement("li"); li.textContent = String(item); return li; }));
  renderProvider();
}
async function loadSources(preferred) {
  const episodeId=state.navigation?.episode?.id;
  let sources = await api("/api/sources");
  if(state.navigation && episodeId!==state.navigation.episode?.id) return;
  if(state.navigation?.episode) {
    const episode=state.navigation.episode;
    sources=sources.filter(source=>episode.source_id ? source.id===episode.source_id : !state.navigation.data.episodes.some(other=>other.id!==episode.id && state.navigation.alive(other) && other.source_id===source.id));
  }
  state.sources = sources;
  const selected = preferred ?? $("source").value;
  $("source").replaceChildren();
  if(state.navigation && !state.navigation.episode?.source_id) { const placeholder=document.createElement('option'); placeholder.value=''; placeholder.textContent='Выберите видео этой серии'; $('source').append(placeholder); }
  if (!sources.length) { const option = document.createElement("option"); option.value = ""; option.textContent = "Нет видео. Добавьте MP4 или MKV."; $("source").append(option); }
  for (const source of sources) { const option = document.createElement("option"); option.value = source.id; option.textContent = source.name; $("source").append(option); }
  if (sources.some((source) => source.id === selected)) $("source").value = selected;
  sourceChanged();
}
function sourceChanged() { const selected = state.sources.find((source) => source.id === $("source").value); setText("source-size", selected ? humanSize(selected.size) : ""); updateControls(); }
function renderHistory() {
  if(state.navigation) return;
  const key = JSON.stringify(state.jobs.map((job) => [job.id, job.status, job.source_name, job.created_at, job.analysis_provider])) + state.selected;
  if (key === state.historyKey) return;
  state.historyKey = key;
  setText("history-count", state.jobs.length);
  $("history-empty").hidden = state.jobs.length > 0;
  $("history-list").replaceChildren(...state.jobs.map((job) => {
    const button = document.createElement("button"); button.type = "button"; button.className = `history-item${job.id === state.selected ? " selected" : ""}`; button.setAttribute("aria-pressed", String(job.id === state.selected));
    const name = document.createElement("span"); name.className = "history-name"; name.textContent = job.source_name;
    const meta = document.createElement("span"); meta.className = "history-meta";
    const status = document.createElement("span"); status.className = `history-state ${Object.hasOwn(statuses, job.status) ? job.status : ""}`; status.textContent = `${statuses[job.status] ?? job.status}${["deepseek", "deepseek_plan", "hybrid"].includes(job.analysis_provider) ? ` · ${providerLabel(job.analysis_provider)}` : ""}`;
    const date = document.createElement("span"); date.textContent = dateLabel(job.created_at);
    meta.append(status, date); button.append(name, meta); button.addEventListener("click", () => selectJob(job.id)); return button;
  }));
}
function checkpointOwner(step, provider, stage) {
  if (step === "prepare" && ["scenes", "shots"].includes(stage)) return "На компьютере · поиск смены планов";
  if (["prepare", "transcribe", "plan", "render"].includes(step)) return "На компьютере";
  if (step === "framing") return provider === "deepseek_plan" ? "На компьютере · для этого режима" : provider === "local" ? "На компьютере" : "DeepSeek API";
  if (provider === "local") return "На компьютере";
  if (provider === "hybrid") return "Локально · DeepSeek API может уточнять сомнения";
  return "DeepSeek API";
}
function renderCheckpoints(job) {
  const group = stageGroup[job.stage];
  const recognized = Number.isInteger(group);
  const active = job.status === "running" && recognized && group < checkpointStages.length;
  document.querySelectorAll("[data-stage]").forEach((element) => {
    const step = element.dataset.stage;
    const index = checkpointStages.indexOf(step);
    let stateName = "pending", label = "Ожидает";
    if (job.status === "completed") { stateName = "done"; label = "Завершено"; }
    else if (active && index === group) { stateName = "current"; label = "Выполняется"; }
    else if (job.status !== "queued" && recognized && group < checkpointStages.length && index < group) { stateName = "done"; label = "Готово"; }
    else if (["failed", "cancelled", "interrupted"].includes(job.status) && recognized && index === group && group < checkpointStages.length) {
      stateName = job.status === "failed" ? "failed" : job.status === "cancelled" ? "cancelled" : "interrupted";
      label = job.status === "failed" ? "Остановлено с ошибкой" : job.status === "cancelled" ? "Отменено" : "Прервано";
    } else if (!recognized && ["running", "failed", "cancelled", "interrupted"].includes(job.status)) { stateName = "unknown"; label = "Стадия сервера не распознана"; }
    element.classList.remove("done", "current", "pending", "failed", "cancelled", "interrupted", "unknown");
    element.classList.add(stateName);
    if (active && index === group) element.setAttribute("aria-current", "step"); else element.removeAttribute("aria-current");
    const owner = element.querySelector("[data-stage-owner]");
    const status = element.querySelector("[data-stage-state]");
    if (owner) owner.textContent = checkpointOwner(step, job.analysis_provider ?? "local", job.stage);
    if (status) status.textContent = label;
  });
}
function renderJob(job) {
  state.selectedJob = job;
  setText('workspace-title', job.source_name?.match(/[«「]([^»」]+)[»」]/)?.[1] ?? job.source_name?.replace(/\.(mp4|mkv)$/i,'') ?? 'Монтаж серии');
  $('job-panel').classList.toggle('job-completed',job.status === 'completed');
  $("job-panel").hidden = false;
  setText("job-heading", job.status === "completed" ? "Монтаж завершён" : "Обработка серии");
  setText("job-source", job.source_name);
  $("job-spending").hidden = true;
  $('job-budget-estimate').hidden=true;

  setText("job-editing", `Оформление: ${job.layout === "cinema" ? "весь кадр + мягкий фон" : "крупный план"} · ${job.caption_style === "accent" ? "яркие короткие субтитры" : "белые субтитры"}`);
  setText("job-provider", job.analysis_provider === "deepseek_plan" ? "Анализ: DeepSeek — сюжет и план, платно · кадрирование, монтаж и экспорт локально" : job.analysis_provider === "hybrid" ? "Анализ: локально + DeepSeek при сомнениях · возможны платные запросы; без API продолжаем локально" : job.analysis_provider === "deepseek" ? "Анализ: DeepSeek · кадры и текст отправляются через интернет, платно" : "Анализ: на компьютере · без платных запросов");
  setText("job-status", statuses[job.status] ?? job.status);
  const progress = Math.max(0, Math.min(1, Number(job.progress) || 0));
  $("job-progress").max = 1; $("job-progress").value = progress; setText("progress-label", `${Math.round(progress * 100)}%`);
  setText("stage-label", stages[job.stage] ?? job.stage ?? "Ожидание"); setText("job-message", job.message);
  $("job-message").hidden = !job.message;
  renderCheckpoints(job);
  $("job-error").hidden = !job.error; setText("job-error", job.error);
  $("cancel-button").hidden = !["queued", "running"].includes(job.status);
  $("retry-button").hidden = !["failed", "cancelled", "interrupted"].includes(job.status);
  $("reset-budget-button").hidden = true;
  $("plan-link").href = `/api/jobs/${encodeURIComponent(job.id)}/plan`;
  $("plan-link").hidden = !["render", "rendering", "completed", "done"].includes(job.stage) && job.status !== "completed";
  renderFiles(job);
  loadQualityWarnings(job);
  loadTimeline(job);
  updateControls();
  state.navigation?.onJob(job);
}
function renderQualityWarnings(jobId, record) {
  if (state.selected !== jobId || state.selectedJob?.id !== jobId || state.selectedJob.status !== "completed") return;
  const warnings = record.warnings ?? [];
  const notes = record.notes ?? [];
  const key = jobId + JSON.stringify([warnings, notes, record.error]);
  if (state.qualityRenderedKey === key) return;
  state.qualityRenderedKey = key;
  $("quality-warnings").hidden = !record.error && !warnings.length;
  setText("quality-summary", record.error ? "Замечания к монтажу недоступны" : `Требует проверки · замечаний: ${warnings.length}`);
  setText("quality-message", record.error ? `Не удалось прочитать монтажный план: ${record.error} Откройте его по ссылке выше и проверьте результат перед публикацией.` : "Модель отметила места, которые стоит проверить при просмотре. Сопоставьте их с монтажным планом и исходной серией.");
  $("quality-warning-list").replaceChildren(...warnings.map((warning) => { const item = document.createElement("li"); item.textContent = warning; return item; }));
  $('quality-notes').hidden=!notes.length;
  $('quality-note-list').replaceChildren(...notes.map(note=>{const item=document.createElement('li');item.textContent=note;return item;}));
}
function loadQualityWarnings(job) {
  if (state.qualityJobId !== job.id) { state.qualityJobId = job.id; state.qualityRenderedKey = ""; $("quality-warnings").open = false; $("quality-warnings").hidden = true; $("quality-warning-list").replaceChildren(); $('quality-notes').hidden=true; $('quality-notes').open=false; $('quality-note-list').replaceChildren(); }
  if (job.status !== "completed") { $("quality-warnings").hidden = true; $('quality-notes').hidden=true; return; }
  const previous = state.planWarnings.get(job.id);
  if (previous) { renderQualityWarnings(job.id, previous); return; }
  const record = {warnings: [], notes: [], error: null};
  state.planWarnings.set(job.id, record);
  api(`/api/jobs/${encodeURIComponent(job.id)}/plan`).then((plan) => {
    const texts=items=>Array.isArray(items) ? [...new Set(items.map(item=>item?.text).filter(text=>typeof text==='string' && text.trim()).map(text=>text.slice(0,500)))] : [];
    if (plan.quality_summary && typeof plan.quality_summary==='object') {
      record.warnings=texts(plan.quality_summary.warnings); record.notes=texts(plan.quality_summary.notes);
    } else record.warnings = Array.isArray(plan.warnings) ? [...new Set(plan.warnings.filter((warning) => typeof warning === "string" && warning.trim()))] : [];
    renderQualityWarnings(job.id, record);
  }).catch((error) => { record.error = error.message; renderQualityWarnings(job.id, record); });
}
function renderFiles(job) {
  const files = Array.isArray(job.files) ? job.files.filter((file) => safeUrl(file.url)) : [];
  const key = job.id + JSON.stringify(files);
  if (key === state.filesKey) return;
  state.filesKey = key; state.files = files;
  if(!state.savingVideos)setText('download-status','');
  $("results-panel").hidden = !files.length;
  const player = $("player"); player.pause(); player.removeAttribute("src"); player.load();
  setText("parts-count", `${files.length} шт.`);
  $("playlist").replaceChildren(...files.map((file, index) => {
    const li = document.createElement("li"); const button = document.createElement("button"); button.type = "button";
    const name = document.createElement("span"); name.textContent = `Часть ${String(index + 1).padStart(2, "0")}`;
    const duration = document.createElement("span"); duration.textContent = humanDuration(file.duration);
    button.append(name, duration); button.addEventListener("click", () => selectFile(index, true)); li.append(button); return li;
  }));
  if (files.length) selectFile(0, false);
  renderDownloadButtons();
}
function renderDownloadButtons() {
  const ready = state.selectedJob?.status === 'completed' && state.selectedJob.id === state.selected;
  const hasFiles = Boolean(ready && state.files.length);
  const currentFile = hasFiles ? state.files[state.fileIndex] : null;

  const downloadVideo = $('download-video');
  if (downloadVideo) {
    if (currentFile && ready) {
      downloadVideo.href = `${safeUrl(currentFile.url)}?download=1`;
      downloadVideo.download = currentFile.name || 'video.mp4';
      downloadVideo.classList.remove('disabled');
      downloadVideo.removeAttribute('aria-disabled');
    } else {
      downloadVideo.href = '#';
      downloadVideo.removeAttribute('download');
      downloadVideo.classList.add('disabled');
      downloadVideo.setAttribute('aria-disabled', 'true');
    }
  }

  const downloadSub = $('download-subtitle');
  if (downloadSub) {
    const subtitleUrl = currentFile?.subtitle_url ? safeUrl(currentFile.subtitle_url) : null;
    if (subtitleUrl && ready) {
      downloadSub.href = `${subtitleUrl}?download=1`;
      downloadSub.download = `${(currentFile.name || 'subtitles').replace(/\.[^.]+$/, '')}.srt`;
      downloadSub.hidden = false;
      downloadSub.classList.remove('disabled');
      downloadSub.removeAttribute('aria-disabled');
    } else {
      downloadSub.href = '#';
      downloadSub.removeAttribute('download');
      downloadSub.hidden = !subtitleUrl;
      downloadSub.classList.add('disabled');
      downloadSub.setAttribute('aria-disabled', 'true');
    }
  }

  const downloadAll = $('download-all');
  if (downloadAll) {
    downloadAll.disabled = state.savingVideos || !ready || !hasFiles;
  }

  const openFolder = $('open-output-folder');
  if (openFolder) {
    openFolder.disabled = !ready || !hasFiles;
  }
}
async function saveVideos(all) {
  const job=state.selectedJob,file=state.files[state.fileIndex];
  if(state.savingVideos || !job || job.id!==state.selected || job.status!=='completed' || !state.files.length || (!all && !file)) return;
  const expected=all ? state.files.length : 1;
  state.savingVideos=true;renderDownloadButtons();
  setText('download-status','Выберите папку для сохранения видео в открывшемся окне Windows.');
  try {
    const response=await fetch(`/api/jobs/${encodeURIComponent(job.id)}/save-videos`,{
      cache:'no-store',method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(all ? {all:true} : {filename:file.name})});
    let result;try{result=await response.json();}catch{throw new Error('Сервер не подтвердил сохранение видео.');}
    const receipt=Number.isInteger(result.count) && result.count>=0 && Array.isArray(result.files) && result.files.length===result.count;
    if(!response.ok) {
      const message=typeof result.error==='string' ? result.error : typeof result.detail==='string' ? result.detail : `Ошибка сервера (${response.status}).`;
      throw new Error(receipt && result.count>0 ? `Успели сохранить видео: ${result.count}. ${message}` : message);
    }
    if(state.selected===job.id) {
      if(result.cancelled===true)setText('download-status','Сохранение отменено.');
      else if(result.cancelled===false && receipt && result.count===expected)setText('download-status',all ? `В выбранную папку сохранено видео: ${result.count}.` : 'MP4 сохранён в выбранную папку.');
      else throw new Error('Сервер не подтвердил сохранение видео. Повторите выбор папки.');
    }
  } catch(error) {
    if(state.selected===job.id)setText('download-status',`Не удалось сохранить видео: ${error.message}`);
  } finally {state.savingVideos=false;renderDownloadButtons();}
}
$('download-video')?.addEventListener('click',(event)=>{if($('download-video').classList.contains('disabled'))event.preventDefault();});
$('download-subtitle')?.addEventListener('click',(event)=>{if($('download-subtitle').classList.contains('disabled'))event.preventDefault();});
$('download-all')?.addEventListener('click',()=>saveVideos(true));
$('open-output-folder')?.addEventListener('click',async ()=>{
  const job=state.selectedJob;
  if(!job || job.id!==state.selected || job.status!=='completed') return;
  setText('download-status','Открываем папку с видео в проводнике...');
  try {
    const res=await api(`/api/jobs/${encodeURIComponent(job.id)}/open-folder`,{method:'POST'});
    if(res?.opened && state.selected===job.id) {
      setText('download-status',`Папка с видео открыта в проводнике: ${res.path}`);
    }
  } catch(error) {
    if(state.selected===job.id)setText('download-status',`Не удалось открыть папку: ${error.message}`);
  }
});
function selectFile(index, play) {
  const file = state.files[index]; if (!file) return;
  state.fileIndex = index; setText("player-message", "");
  $("player").src = safeUrl(file.url); renderDownloadButtons();
  $("playlist").querySelectorAll("button").forEach((button, current) => { button.classList.toggle("selected", current === index); button.setAttribute("aria-current", String(current === index)); });
  if (play) $("player").play().catch(() => setText("player-message", "Нажмите воспроизведение в плеере."));
  if (state.timeline?.jobId === state.selected) renderTimelineSelection(index);
  const part = state.timeline?.plan?.parts?.[index];
  const badge = $('part-music-badge');
  if (badge) {
    if (part?.music_track) {
      badge.textContent = `🎵 Фоновая музыка: ${part.music_track}`;
      badge.hidden = false;
    } else {
      badge.hidden = true;
    }
  }
  renderPartContext();
}

function currentPartContext() {
  if (state.timeline?.jobId !== state.selected) return null;
  const context=state.timeline.plan.parts[state.fileIndex]?.cover_context;
  return context && ['title','synopsis','prompt'].every(key=>typeof context[key]==='string' && context[key].trim()) ? context : null;
}
function renderPartContext() {
  const context=currentPartContext();
  $('part-context').hidden=!context;
  setText('context-copy-status','');
  if(!context) return;
  setText('part-context-heading',`Заставка · часть ${String(state.fileIndex+1).padStart(2,'0')}`);
  setText('part-context-title',context.title);
  setText('part-context-synopsis',context.synopsis);
  $('part-context-prompt').value=context.prompt;
  $('part-context-fallback').hidden=context.method!=='extractive';
}
async function copyPartContext() {
  const context=currentPartContext(); if(!context) return;
  const jobId=state.selected,index=state.fileIndex;
  try {
    await navigator.clipboard.writeText(`Контекст: ${context.synopsis}\n\n${context.prompt}`);
    if(state.selected===jobId && state.fileIndex===index) setText('context-copy-status','Контекст и промпт скопированы.');
  } catch {
    if(state.selected===jobId && state.fileIndex===index) setText('context-copy-status','Не удалось скопировать. Выделите текст промпта ниже и скопируйте вручную.');
  }
}
$('copy-part-context').addEventListener('click',copyPartContext);

function sourceTime(seconds, precise = true) {
  const n = Math.max(0, Number(seconds));
  const scale=precise ? 100 : 1, rounded=Math.round(n*scale);
  return `${String(Math.floor(rounded / (60*scale))).padStart(2, '0')}:${((rounded % (60*scale))/scale).toFixed(precise ? 2 : 0).padStart(precise ? 5 : 2, '0')}`;
}
function timelinePieces(plan) {
  const retained = plan.parts.flatMap((part, index) => part.cuts.map((cut, cutIndex) => ({...cut, partIndex:index, cutIndex}))).sort((a,b) => a.start-b.start);
  const pieces = []; let end = 0;
  for (const cut of retained) {
    if (cut.start > end + .002) pieces.push({start:end, end:cut.start, removed:true});
    pieces.push(cut); end = Math.max(end, cut.end);
  }
  if (end < plan.source.duration - .002) pieces.push({start:end, end:plan.source.duration, removed:true});
  return pieces;
}
function pieceLabel(piece) {
  return `${piece.removed ? 'Убрано' : `Часть ${String(piece.partIndex+1).padStart(2,'0')}, фрагмент ${piece.cutIndex+1}`} · исходник ${sourceTime(piece.start)}–${sourceTime(piece.end)}`;
}
function timelineButton(piece, duration) {
  const button = document.createElement('button'); button.type = 'button';
  button.className = `timeline-piece${piece.removed ? ' removed' : ''}`;
  button.style.left = `${100*piece.start/duration}%`; button.style.width = `${100*(piece.end-piece.start)/duration}%`;
  if (!piece.removed) button.style.backgroundColor = timelineColors[piece.partIndex % timelineColors.length];
  const label = pieceLabel(piece); button.title = label; button.setAttribute('aria-label', label);
  button.addEventListener('click', () => reviewSource(piece)); return button;
}
const debugKinds={atmosphere:'Атмосфера',story:'Развитие сюжета',reaction:'Реакция',uncertainty:'Неуверенность',manual:'Ручная проверка'};
function debugPieces(plan) {
  if (plan.debug_timeline?.available!==true || !Array.isArray(plan.debug_timeline.reasons)) return [];
  const pieces=[];
  for(const reason of plan.debug_timeline.reasons.slice(0,500)) {
    if(!reason || !Object.hasOwn(debugKinds,reason.kind) || !Number.isFinite(reason.start) || !Number.isFinite(reason.end) || reason.start<0 || reason.end<=reason.start || reason.end>plan.source.duration || typeof reason.title!=='string' || typeof reason.detail!=='string') continue;
    plan.parts.forEach((part,partIndex)=>part.cuts.forEach((cut,cutIndex)=>{
      const start=Math.max(cut.start,reason.start),end=Math.min(cut.end,reason.end);
      if(start<end) pieces.push({...reason,start,end,partIndex,cutIndex,title:reason.title.slice(0,160),detail:reason.detail.slice(0,500)});
    }));
  }
  const groups=new Map();
  pieces.forEach((piece,index)=>{
    const key=typeof piece.event_id==='string' && piece.event_id ? JSON.stringify([piece.event_id,piece.kind,piece.title,piece.detail,piece.partIndex,piece.cutIndex]) : `unmapped-${index}`;
    if(!groups.has(key))groups.set(key,[]);groups.get(key).push(piece);
  });
  const merged=[];
  for(const group of groups.values()) {
    const continuous=[];
    for(const piece of group.sort((a,b)=>a.start-b.start || a.end-b.end)) {
      const last=continuous.at(-1);
      if(last && piece.start<=last.end) last.end=Math.max(last.end,piece.end);
      else continuous.push({...piece});
    }
    merged.push(...continuous);
  }
  return merged.sort((a,b)=>a.start-b.start || a.end-b.end);
}
function showDebugReason(piece) {
  setText('analysis-debug-title',`${debugKinds[piece.kind]} · исходник ${sourceTime(piece.start)}–${sourceTime(piece.end)} · ${piece.title}`);
  setText('analysis-debug-detail',piece.detail);
}
function renderDebugTimeline() {
  const enabled=$('analysis-debug').checked===true;
  $('analysis-debug-info').hidden=!enabled; $('analysis-debug-lane').hidden=!enabled;
  const record=state.timeline;
  if(!enabled || !record || record.jobId!==state.selected) return;
  const pieces=debugPieces(record.plan),ends=[];
  $('analysis-debug-lane').replaceChildren(...pieces.map(piece=>{
    let row=ends.findIndex(end=>end<=piece.start); if(row<0)row=ends.length; ends[row]=piece.end;
    const button=document.createElement('button');button.type='button';button.className=`analysis-debug-piece reason-${piece.kind}`;
    button.style.left=`${100*piece.start/record.plan.source.duration}%`;button.style.width=`${100*(piece.end-piece.start)/record.plan.source.duration}%`;button.style.top=`${row*25}px`;
    button.textContent=debugKinds[piece.kind];button.title=`${piece.title} · ${piece.detail}`;button.setAttribute('aria-label',`${debugKinds[piece.kind]} · ${sourceTime(piece.start)}–${sourceTime(piece.end)} · ${piece.title}`);
    button.addEventListener('mouseenter',()=>showDebugReason(piece));button.addEventListener('focus',()=>showDebugReason(piece));
    button.addEventListener('click',()=>{reviewSource(piece);showDebugReason(piece);});return button;
  }));
  $('analysis-debug-lane').style.height=`${Math.max(1,ends.length)*25}px`;
  setText('analysis-debug-title',pieces.length ? 'Выберите причину на таймлайне для сравнения с исходником.' : 'Причины анализа недоступны для оставленных фрагментов.');
  setText('analysis-debug-detail','');
}
$('analysis-debug').addEventListener('change',renderDebugTimeline);
function loadTimeline(job) {
  const available = job.status === 'completed' || job.stage === 'rendering';
  const key = `${job.id}:${available ? job.status : 'pending'}`;
  if (key === state.timelineKey) return;
  state.timelineKey = key; state.timeline = null; state.sourceSelection = null;
  renderPartContext();
  $('analysis-debug').checked=false; $('analysis-debug-info').hidden=true; $('analysis-debug-lane').hidden=true; $('analysis-debug-lane').replaceChildren();
  $('timeline-playhead').hidden = true; setText('source-clock','');
  $('timeline-zoom').value='1'; $('timeline-map').style.width='100%';
  $('timeline-map').classList.toggle('zoomed',false);
  const player = $('source-player'); player.pause(); player.removeAttribute('src'); player.load();
  $('timeline-panel').hidden = true;
  $('source-panel-review').hidden = true;
  if (!available) return;
  api(`/api/jobs/${encodeURIComponent(job.id)}/plan`).then((plan) => {
    if (state.timelineKey !== key || state.selected !== job.id || !plan.source || !Array.isArray(plan.parts)) return;
    if (!(Number.isFinite(plan.source.duration) && plan.source.duration > 0)) return;
    state.timeline = {jobId:job.id, plan};
    player.src=safeUrl(`/api/jobs/${encodeURIComponent(job.id)}/source`); player.load();
    $('timeline-panel').hidden = false; $('source-panel-review').hidden = false; setText('timeline-duration', sourceTime(plan.source.duration, false));
    setText('source-selection', 'Выбери сохранённый или удалённый отрезок.'); setText('source-error', '');
    $('timeline-ruler').replaceChildren(...[0,.25,.5,.75,1].map(f => { const span=document.createElement('span'); span.textContent=sourceTime(plan.source.duration*f,false); return span; }));
    $('timeline-overview').replaceChildren(...timelinePieces(plan).map(piece => timelineButton(piece,plan.source.duration)));
    $('timeline-groups').replaceChildren(...plan.parts.map((part,index) => {
      const label=document.createElement('button'); label.type='button'; label.className='timeline-group';
      const title=`Часть ${String(index+1).padStart(2,'0')} · ${part.cuts.length} фрагментов`;
      label.title=title; label.setAttribute('aria-label',title);
      const short=document.createElement('span'); short.className='group-short'; short.textContent=String(index+1).padStart(2,'0');
      const full=document.createElement('span'); full.className='group-full'; full.textContent=`Часть ${String(index+1).padStart(2,'0')}`;
      label.append(short,full);
      const begin=part.cuts[0].start, end=part.cuts.at(-1).end;
      label.style.left=`${100*begin/plan.source.duration}%`; label.style.width=`${100*(end-begin)/plan.source.duration}%`;
      label.style.borderColor=timelineColors[index % timelineColors.length]; label.style.color=timelineColors[index % timelineColors.length];
      label.addEventListener('click', () => { if(state.files[index]) selectFile(index,false); else renderTimelineSelection(index); });
      return label;
    }));
    renderTimelineSelection(state.fileIndex < plan.parts.length ? state.fileIndex : 0);
    renderPartContext();
    renderDebugTimeline();
  }).catch(() => { if (state.timelineKey === key) state.timelineKey = ''; });
}
function renderTimelineSelection(index) {
  const record=state.timeline; if(!record || record.jobId !== state.selected) return;
  const part=record.plan.parts[index]; if(!part) return;
  $('timeline-groups').querySelectorAll('button').forEach((button,current)=>{
    button.classList.toggle('selected',current===index); button.setAttribute('aria-pressed',String(current===index));
  });
}
function reviewSource(piece) {
  if(!state.timeline || state.timeline.jobId !== state.selected) return;
  state.sourceSelection={...piece,jobId:state.selected};
  setText('source-selection',pieceLabel(piece)); setText('source-error','');
  if(!piece.removed) { if(state.files[piece.partIndex]) selectFile(piece.partIndex,false); else renderTimelineSelection(piece.partIndex); }
  const player=$('source-player'); const url=safeUrl(`/api/jobs/${encodeURIComponent(state.selected)}/source`);
  if(player.getAttribute('src') !== url) { player.src=url; player.load(); }
  else if(player.readyState >= 1) playSourceSelection();
}
function playSourceSelection() {
  const selected=state.sourceSelection; if(!selected || selected.jobId !== state.selected) return;
  const player=$('source-player'); player.currentTime=selected.start;
  player.play().catch(()=>setText('source-error','Нажми воспроизведение в плеере исходника.'));
}
$('timeline-zoom').addEventListener('change',()=>{
  const scale=Number($('timeline-zoom').value);
  $('timeline-map').style.width=`${100*([1,2,4,8].includes(scale) ? scale : 1)}%`;
  $('timeline-map').classList.toggle('zoomed',scale>1);
});
$('source-player').addEventListener('loadedmetadata',playSourceSelection);
$('source-player').addEventListener('timeupdate',()=>{
  const selected=state.sourceSelection; const player=$('source-player');
  if(state.timeline?.jobId === state.selected) {
    const duration=state.timeline.plan.source.duration;
    $('timeline-playhead').hidden=false; $('timeline-playhead').style.left=`${Math.max(0,Math.min(100,100*player.currentTime/duration))}%`;
    setText('source-clock',`${sourceTime(player.currentTime)} / ${sourceTime(duration)}`);
  }
  if($('source-limit').checked && selected?.jobId === state.selected && player.currentTime >= selected.end) player.pause();
});
$('source-player').addEventListener('error',()=>setText('source-error','Браузер не смог открыть исходник. Для MKV может потребоваться локальный видеоплеер.'));
$('source-full-button').addEventListener('click',()=>{
  if(!state.timeline || state.timeline.jobId !== state.selected) return;
  state.sourceSelection=null; setText('source-selection','Вся исходная серия · перематывай плеер для сравнения.');
  const player=$('source-player'); const url=safeUrl(`/api/jobs/${encodeURIComponent(state.selected)}/source`);
  if(player.getAttribute('src') !== url) { player.src=url; player.load(); }
  player.play().catch(()=>setText('source-error','Нажми воспроизведение в плеере исходника.'));
});
async function selectJob(id) {
  if (state.selected !== id) { $("quality-warnings").hidden = true; state.qualityJobId = null; }
  state.selected = id; renderHistory();
  try { const job = await api(`/api/jobs/${encodeURIComponent(id)}`); if (state.selected === id) renderJob(job); }
  catch (error) { setText(state.navigation && state.navigation.view!=='edit' ? 'library-message' : 'form-message', error.message); }
}
async function refresh() {
  if (state.polling) return;
  state.polling = true;
  try {
    const [health, jobs] = await Promise.all([api("/api/health"), api("/api/jobs"), loadDeepseekStatus()]);
    const recovered = !state.health && $("connection").classList.contains("offline");
    renderHealth(health); state.jobs = jobs; renderHistory();
    state.navigation?.onJobs(jobs);
    if (recovered) setText("form-message", "Связь с локальным сервером восстановлена.");
    if (!state.selected && jobs.length && !state.navigation) state.selected = jobs.find((job) => ["running", "queued"].includes(job.status))?.id ?? jobs[0].id;
    if (state.selected) { const selected = state.selected; const job = await api(`/api/jobs/${encodeURIComponent(selected)}`); if (state.selected === selected) renderJob(job); renderHistory(); }
    refreshBalance();
  } catch (error) { state.health = null; $("connection").className = "status-pill offline"; setText("connection-label", "Нет связи с сервером"); setText("form-message", `${error.message} Проверьте окно start.bat.`); updateControls(); }
  finally { state.polling = false; }
}
async function jobAction(action) {
  if (!state.selected || state.busyAction) return;
  const actionJobId = state.selected;
  state.busyAction = true; updateControls(); setText("form-message", "");
  try { const job = await api(`/api/jobs/${encodeURIComponent(actionJobId)}/${action}`, {method: "POST"}); if (job?.id === actionJobId && state.selected === actionJobId) renderJob(job); await refresh(); }
  catch (error) { setText("form-message", error.message); }
  finally { state.busyAction = false; updateControls(); }
}
$("source").addEventListener("change", sourceChanged);
$("analysis-provider").addEventListener("change", renderProvider);
$("layout").addEventListener("change", renderEditing);
$("caption-style").addEventListener("change", renderEditing);
$("deepseek-check").addEventListener("click", checkDeepseek);
$('balance-refresh-button').addEventListener('click',()=>refreshBalance(true));
$("recovery-button").addEventListener("click", async () => {
  if (state.busyAction) return;
  state.busyAction = true; $("recovery-button").disabled = true; updateControls();
  try {
    await api('/api/deepseek/recovery', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({accept_reserved_costs:true})});
    state.deepseekCheck = null;
    setText("recovery-message", "Резерв сохранён. Спорные запросы не повторятся. Новые запросы доступны.");
    await loadDeepseekStatus();
  } catch (error) { setText("recovery-message", error.message); }
  finally { state.busyAction = false; $("recovery-button").disabled = false; updateControls(); }
});
$("refresh-sources").addEventListener("click", () => loadSources().catch((error) => setText("form-message", error.message)));
$("upload-button").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", () => uploadFile($("file-input").files[0]));
function uploadFile(file) {
  if (!file || state.uploading || state.busyAction) return;
  if (!/\.(mp4|mkv)$/i.test(file.name)) { setText("form-message", "Выберите файл MP4 или MKV."); $("file-input").value = ""; return; }
  state.uploading = true; updateControls(); $("upload-progress").hidden = false; $("upload-meter").value = 0; setText("upload-label", "Копируем видео в проект…"); setText("form-message", "");
  const body = new FormData(); body.append("file", file);
  const request = new XMLHttpRequest(); request.open("POST", "/api/import"); request.responseType = "json";
  request.upload.addEventListener("progress", (event) => { if (event.lengthComputable) { const percentage = Math.round(event.loaded / event.total * 100); $("upload-meter").value = percentage; setText("upload-label", percentage === 100 ? "Проверяем видео…" : `Копируем видео: ${percentage}%`); } });
  request.addEventListener("load", async () => {
    try { if (request.status < 200 || request.status >= 300) throw new Error(typeof request.response?.detail === "string" ? request.response.detail : "Не удалось добавить видео."); await loadSources(request.response.id); setText("form-message", "Видео добавлено в папку проекта."); }
    catch (error) { setText("form-message", error.message); }
    finally { finishUpload(); }
  });
  request.addEventListener("error", () => { setText("form-message", "Соединение прервалось. Видео не добавлено."); finishUpload(); });
  request.addEventListener("abort", () => { setText("form-message", "Загрузка прервана."); finishUpload(); });
  request.send(body);
}
$("upload-button").addEventListener("dragover", (event) => { event.preventDefault(); $("upload-button").classList.toggle("dragging", true); });
$("upload-button").addEventListener("dragleave", () => $("upload-button").classList.toggle("dragging", false));
$("upload-button").addEventListener("drop", (event) => {
  event.preventDefault(); $("upload-button").classList.toggle("dragging", false);
  const files = event.dataTransfer?.files;
  if (files?.length !== 1) { setText("form-message", "Добавляйте по одной серии за раз."); return; }
  uploadFile(files[0]);
});
function finishUpload() { state.uploading = false; $("file-input").value = ""; $("upload-progress").hidden = true; updateControls(); }
$("create-form").addEventListener("submit", async (event) => {
  event.preventDefault(); if ($("create-button").disabled) return;
  if(state.navigation) { await state.navigation.launch(); return; }
  state.busyAction = true; updateControls(); setText("form-message", "");
  try { const job = await api("/api/jobs", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({source_id: $("source").value, analysis_provider: analysisProvider(), ...editingOptions()})}); state.selected = job.id; renderJob(job); await refresh(); $("job-panel").scrollIntoView({behavior: "smooth", block: "nearest"}); }
  catch (error) { setText("form-message", error.message); }
  finally { state.busyAction = false; updateControls(); }
});
$("cancel-button").addEventListener("click", () => jobAction("cancel"));
$("retry-button").addEventListener("click", () => jobAction("retry"));
$("reset-budget-button").addEventListener("click", async () => {
  if (state.busyAction || !state.selectedJob) return;
  const jobId = state.selectedJob.id;
  state.busyAction = true; updateControls();
  try {
    await api(`/api/jobs/${encodeURIComponent(jobId)}/reset-budget`, {method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({})});
    if (state.selected === jobId) {
      await selectJob(jobId);
      setText("form-message", "Начато новое наблюдение. История расходов сохранена.");
    }
  } catch (error) { setText("form-message", error.message); }
  finally { state.busyAction = false; updateControls(); }
});
$("player").addEventListener("ended", () => { if (state.fileIndex + 1 < state.files.length) selectFile(state.fileIndex + 1, true); else setText("player-message", "Все части просмотрены."); });
$("player").addEventListener("loadedmetadata", () => { const button = $("playlist").querySelectorAll("button")[state.fileIndex]; if (button) button.lastElementChild.textContent = humanDuration($("player").duration); });
$("player").addEventListener("error", () => { if ($("player").getAttribute("src")) setText("player-message", "Не удалось воспроизвести файл. Попробуйте скачать MP4."); });
loadSources().catch((error) => setText("form-message", error.message));
renderProvider();
renderEditing();
refresh();
setInterval(refresh, 2500);
