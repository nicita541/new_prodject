(() => {
  "use strict";
  const $ = (id) => document.getElementById(id),
    esc = (s) =>
      String(s ?? "").replace(
        /[&<>"']/g,
        (c) =>
          ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
          })[c],
      ),
    stamp = (x) =>
      new Date(x || Date.now()).toLocaleString("ru-RU", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      }),
    kb = (s) =>
      Number.isFinite(Number(s)) && Number(s) >= 0
        ? (Number(s) / 1024 / 1024 / 1024).toFixed(2) + " ГБ"
        : "Размер неизвестен",
    copyText = (t) =>
      navigator.clipboard?.writeText(t).catch(() => fallbackCopy(t)) ||
      fallbackCopy(t);
  function fallbackCopy(t) {
    let x = document.createElement("textarea");
    x.value = t;
    document.body.append(x);
    x.select();
    document.execCommand("copy");
    x.remove();
  }
  const stages = [
    ["prepare", "Подготовка видео"],
    ["transcribe", "Распознавание речи"],
    ["scenes", "Поиск сцен"],
    ["analyze", "Анализ сюжета и кадров"],
    ["condense", "Отбор смысловых сцен"],
    ["framing", "Кадрирование"],
    ["plan", "Составление плана"],
    ["render", "Экспорт Shorts"],
  ];
  const db = {
    projects: [],
    episodes: [],
    sources: [],
    jobs: [],
    plans: {},
    finishing: {},
    music: {
      enabled: false,
      volume: 0.15,
      mode: "random_per_part",
      track: null,
      part_tracks: {},
      tracks: [],
    },
    deepseek: { configured: false, model: null },
    health: { ready: false, busy: false, missing: [] },
  };
  const ui = {
    screen: "projects",
    projectId: null,
    episodeId: null,
    jobId: null,
    part: 0,
    segment: 0,
    search: "",
    filter: "all",
    editing: null,
    draftMusic: null,
    reviewMode: "compare",
    playing: false,
    localFileUrl: null,
    localFileName: null,
    localMedia: {},
    actionPending: false,
  };
  let toastTimer, processTimer;
  function sourceBy(id) {
    return db.sources.find((s) => s.id === id);
  }
  function projectBy(id) {
    return db.projects.find((p) => p.id === id);
  }
  function epBy(id) {
    return db.episodes.find((e) => e.id === id);
  }
  function currP() {
    return projectBy(ui.projectId);
  }
  function currE() {
    return epBy(ui.episodeId);
  }
  function jobsFor(eid) {
    return db.jobs
      .filter((j) => j.episode_id === eid)
      .sort((a, b) => b.created_at - a.created_at);
  }
  function latest(eid) {
    return jobsFor(eid)[0];
  }
  function jobBy(id) {
    return db.jobs.find((j) => j.id === id);
  }
  function currentJob() {
    const selected = jobBy(ui.jobId);
    return selected?.episode_id === ui.episodeId
      ? selected
      : latest(ui.episodeId);
  }
  function aliveP(p) {
    return Boolean(p) && !p.archived_at;
  }
  function aliveE(e) {
    return Boolean(e) && !e.archived_at && aliveP(projectBy(e.project_id));
  }
  function providerLabel(provider) {
    return {local: "На компьютере", local_fast_story: "На компьютере", local_flash_story: "На компьютере", antigravity_manual: "Antigravity", deepseek_plan: "DeepSeek", deepseek: "DeepSeek", hybrid: "На компьютере + DeepSeek"}[provider] || "Не указан";
  }
  function statusLabel(s) {
    return (
      {
        completed: "Готово",
        running: "Выполняется",
        queued: "В очереди",
        failed: "Ошибка",
        interrupted: "Прервано",
        cancelled: "Отменено",
        waiting_analysis: "Ожидает Antigravity",
      }[s] || "Не запускалось"
    );
  }
  function badge(s) {
    return `<span class="badge ${s === "completed" ? "good" : ["running", "queued"].includes(s) ? "warn" : ["failed", "cancelled"].includes(s) ? "rose" : "muted"}">${statusLabel(s)}</span>`;
  }
  // Server data is authoritative; do not invent completed Shorts or durations.
  function publicJob(j) {
    return {
      ...j,
      files: Array.isArray(j?.files) ? j.files : [],
      stage_progress: j?.stage_progress || {},
    };
  }
  async function request(method, path, body = null, { quiet = false } = {}) {
    try {
      return await window.KadrBridge.request(method, path, body, db, ui);
    } catch (error) {
      if (!quiet) notify(error.message, true);
      throw error;
    }
  }
  function notify(msg, error = false) {
    const el = $("toast");
    el.textContent = (error ? "Ошибка: " : "") + msg;
    el.style.borderColor = error ? "#a85b6c" : "#4e7181";
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 3700);
  }
  function modal({
    title,
    text = "",
    label = "",
    value = "",
    kind = "text",
    confirm = "Подтвердить",
    danger = false,
    onConfirm,
  }) {
    const host = $("modalHost");
    host.innerHTML = `<div class="modal-overlay" data-action="close-modal-bg"><div class="dialog" role="dialog" aria-modal="true"><div class="eyebrow">КАДР STUDIO</div><h2>${esc(title)}</h2><p>${esc(text)}</p>${label ? `<label class="form-label" for="modalField">${esc(label)}</label><input id="modalField" class="form-input" type="${kind === "number" ? "number" : "text"}" ${kind === "number" ? 'min="1" max="9999"' : ""} value="${esc(value)}">` : ""}<div class="buttons"><button class="btn clear" data-action="close-modal">Отмена</button><button id="confirmModal" class="btn ${danger ? "red" : "solid"}">${esc(confirm)}</button></div></div></div>`;
    const field = $("modalField");
    $("confirmModal").onclick = async () => {
      const v = field?.value || "";
      try {
        await onConfirm(v);
        host.innerHTML = "";
      } catch (e) {
        notify(e.message, true);
      }
    };
    if (field) {
      field.focus();
      field.addEventListener("keydown", (e) => {
        if (e.key === "Enter") $("confirmModal").click();
      });
    } else $("confirmModal").focus();
  }
  const productScreens = ["projects", "episodes", "editor", "processing", "review", "finishing", "trash"];
  function go(screen, { project, episode, job } = {}) {
    if (!productScreens.includes(screen)) screen = "projects";
    if (project) ui.projectId = project;
    if (episode) ui.episodeId = episode;
    if (job) ui.jobId = job;
    if (
      ["editor", "processing", "review", "finishing"].includes(screen) &&
      (!aliveE(currE()) || currE().project_id !== ui.projectId)
    ) {
      notify("Сначала выберите серию");
      screen = "projects";
    }
    if (screen === "episodes" && !aliveP(currP())) {
      notify("Сначала выберите проект");
      screen = "projects";
    }
    if (screen === "review" || screen === "finishing") {
      const selected = jobBy(ui.jobId),
        ready =
          selected?.episode_id === ui.episodeId &&
          selected.status === "completed"
            ? selected
            : jobsFor(ui.episodeId).find((x) => x.status === "completed");
      if (screen === "review" && !ready) {
        notify("Готовых шортсов для этой серии пока нет");
        screen = "editor";
      } else if (ready) {
        ui.jobId = ready.id;
        if (screen === "review") ui.part = 0;
      }
    }
    if (screen === "processing") {
      const j =
        (jobBy(ui.jobId)?.episode_id === ui.episodeId
          ? jobBy(ui.jobId)
          : null) || latest(ui.episodeId);
      if (!j) {
        screen = "editor";
        notify("Монтаж пока не запускался");
      } else ui.jobId = j.id;
    }
    ui.screen = screen;
    ui.playing = false;
    render();
    window.scrollTo({ top: 0, behavior: "instant" });
    if (screen === "editor" && ui.episodeId && !db.finishing[ui.episodeId]) {
      const expectedEpisode = ui.episodeId;
      window.KadrBridge.loadSelected(db, ui).then(() => {
        if (ui.episodeId === expectedEpisode && ui.screen === "editor") {
          ui.editing = null;
          render();
        }
      }).catch((error) => notify("Не удалось загрузить оформление: " + error.message, true));
    }
    if (
      (screen === "review" || screen === "finishing") &&
      ui.jobId &&
      (!db.plans[ui.jobId] ||
        (screen === "finishing" &&
          db.plans[ui.jobId]?.parts?.some(
            (p) => !db.captionOverrides?.[ui.jobId + ":" + p.index],
          )))
    ) {
      const expected = ui.jobId;
      window.KadrBridge.loadSelected(db, ui)
        .then(() => {
          if (ui.jobId === expected && ui.screen === screen) render();
        })
        .catch((e) =>
          notify("Не удалось загрузить монтаж: " + e.message, true),
        );
    }
  }
  function refreshCrumbs() {
    const project = currP(),
      ep = currE();
    let parts = [
      `<button data-action="nav" data-screen="projects">Проекты</button>`,
    ];
    if (!["projects", "trash"].includes(ui.screen) && project)
      parts.push(
        `<span class="slash">/</span><button data-action="go-project" data-id="${esc(project.id)}">${esc(project.title)}</button>`,
      );
    if (
      ["editor", "processing", "review", "finishing"].includes(ui.screen) &&
      ep
    )
      parts.push(
        '<span class="slash">/</span>',
        `<button data-action="nav" data-screen="editor">Серия ${ep.number}</button><span class="slash">/</span><span class="here">${ui.screen === "editor" ? "Настройки" : ui.screen === "processing" ? "Монтаж" : ui.screen === "finishing" ? "Оформление" : "Shorts"}</span>`,
      );
    else if (ui.screen === "trash")
      parts.push(
        `<span class="slash">/</span><span class="here">Корзина</span>`,
      );
    else if (ui.screen === "episodes")
      parts.push('<span class="slash">/</span><span class="here">Серии</span>');
    $("breadcrumbs").innerHTML = parts.join(" ");
    document
      .querySelectorAll(".navbtn")
      .forEach((b) =>
        b.classList.toggle("active", b.dataset.screen === (ui.screen === "trash" ? "trash" : "projects")),
      );
    $("nav-project-count").textContent = db.projects.filter(aliveP).length;
    $("nav-trash-count").textContent =
      db.projects.filter((p) => p.archived_at).length +
      db.episodes.filter(
        (e) => e.archived_at && aliveP(projectBy(e.project_id)),
      ).length;
  }
  function header(eye, title, sub, buttons = "") {
    return `<section class="headline"><div><div class="eyebrow">${eye}</div><h1>${title}</h1><p class="lede">${sub}</p></div><div class="headline-actions">${buttons}</div></section>`;
  }
  function render() {
    refreshCrumbs();
    const main = $("main");
    main.innerHTML = episodeNavigation() + (
      {
        projects: renderProjects,
        episodes: renderEpisodes,
        editor: renderEditor,
        processing: renderProcessing,
        review: renderReview,
        finishing: renderFinishing,
        trash: renderTrash,
      }[ui.screen] || renderProjects
    )();
    if (ui.screen === "editor") {
      bindEditor();
      syncPreview();
    }
    if (ui.screen === "review") bindReview();
    if (ui.screen === "processing") bindProcessing();
    if (ui.screen === "finishing" && $("fcCanvas") && $("fcVideo"))
      bindFinishing();
  }
  function episodeNavigation() {
    if (!["editor", "processing", "review", "finishing"].includes(ui.screen) || (!aliveE(currE()) || currE().project_id !== ui.projectId)) return "";
    const hasJob = Boolean(latest(ui.episodeId));
    const ready = jobsFor(ui.episodeId).some((job) => job.status === "completed");
    return `<nav class="episode-navigation" aria-label="Работа с серией">${[
      ["editor", "Настройки", true], ["processing", "Монтаж", hasJob],
      ["review", "Shorts", ready], ["finishing", "Оформление", true],
    ].map(([screen, title, available]) => `<button class="btn sm ${ui.screen === screen ? "selected" : "clear"}" data-action="nav" data-screen="${screen}" ${ui.screen === screen ? 'aria-current="page"' : ""} ${available ? "" : 'disabled title="Сначала завершите монтаж"'}>${title}</button>`).join("")}</nav>`;
  }
  function episodeHasCompleted(eid) {
    return jobsFor(eid).some(
      (j) =>
        j.status === "completed" &&
        Array.isArray(j.files) &&
        j.files.length > 0,
    );
  }
  function projectStatus(p) {
    const eps = db.episodes.filter((e) => e.project_id === p.id && aliveE(e));
    return {
      eps,
      ready: eps.filter((e) => episodeHasCompleted(e.id)).length,
      running: eps.filter((e) =>
        jobsFor(e.id).some((j) => j.status === "running"),
      ).length,
    };
  }
  function renderProjects() {
    const active = db.projects.filter(aliveP),
      q = ui.search.toLowerCase(),
      cards = active
        .filter((p) => p.title.toLowerCase().includes(q))
        .filter((p) => ui.filter !== "ready" || projectStatus(p).ready),
      episodes = db.episodes.filter(aliveE),
      ready = episodes.filter((e) => episodeHasCompleted(e.id)).length,
      running = db.jobs.filter((j) => j.status === "running").length;
    return `${header("ОБЗОР / ВАША БИБЛИОТЕКА", "Проекты", "Выберите проект или создайте новый.", `<button class="btn solid" data-action="new-project">＋ Новый проект</button>`)}
<div class="hero"><div class="hero-copy"><h2>От полной серии<br>до готовой истории.</h2><p>Одна библиотека для исходников, сценарного анализа, монтажа и проверки каждого шортса перед публикацией.</p><button class="btn solid" data-action="go-project" data-id="${esc(active[0]?.id || "")}">Продолжить работу →</button></div><div class="hero-art"><div class="moon"></div><div class="figure"></div><div class="ground"></div></div></div>
<div class="overview-stats"><div class="stat-card"><div class="stat-ico">▦</div><div><strong>${active.length}</strong><small>Проектов</small></div></div><div class="stat-card"><div class="stat-ico">▤</div><div><strong>${episodes.length}</strong><small>Серий</small></div></div><div class="stat-card"><div class="stat-ico">▷</div><div><strong>${ready}</strong><small>Готовых серий</small></div></div><div class="stat-card"><div class="stat-ico">◷</div><div><strong>${running}</strong><small>В обработке</small></div></div></div>
<div class="section-title"><h2>Коллекция аниме</h2></div><div class="library-row"><input class="search" id="projectSearch" placeholder="⌕   Поиск по проектам" value="${esc(ui.search)}" aria-label="Поиск проектов"><div class="seg"><button class="${ui.filter === "all" ? "active" : ""}" data-action="filter" data-id="all">Все</button><button class="${ui.filter === "ready" ? "active" : ""}" data-action="filter" data-id="ready">Готовые</button></div></div>
<div class="project-grid" id="projectCards">${cards
      .map((p) => {
        const v = projectStatus(p);
        return `<article class="panel project-card" data-action="go-project" data-id="${esc(p.id)}" tabindex="0"><div class="poster-art" data-tone="${p.tone || "blue"}"><span class="poster-symbol">${p.tone === "rose" ? "〃" : p.tone === "emerald" ? "◇" : "✧"}</span><span class="poster-tag">АНИМЕ / ${String(v.eps.length).padStart(2, "0")} СЕРИИ</span><span class="poster-count">${v.ready} готово · ${v.eps.length} всего</span></div><div class="project-info"><h3>${esc(p.title)}</h3><p>Создано ${stamp(p.created_at)}</p><div class="card-footer"><span class="badge ${v.ready ? "good" : "muted"}">${v.ready ? "✓ " + v.ready + " готово" : "Нет готовых"}</span><button class="btn sm clear" data-action="go-project" data-id="${esc(p.id)}">Открыть проект ↗</button></div></div></article>`;
      })
      .join(
        "",
      )}</div>${cards.length ? "" : `<div class="empty"><strong>Проекты не найдены</strong>Измените запрос или создайте новый проект.</div>`}`;
  }
  function renderEpisodes() {
    const p = currP();
    if (!p || !aliveP(p))
      return `<div class="empty">Выберите проект в библиотеке.</div>`;
    const eps = db.episodes
        .filter((e) => aliveE(e) && e.project_id === p.id)
        .sort((a, b) => a.number - b.number),
      summary = projectStatus(p);
    return `${header("ПРОЕКТ / БИБЛИОТЕКА СЕРИЙ", "Серии проекта", "Выберите серию, чтобы настроить монтаж или открыть готовые Shorts.", `<button class="btn clear" data-action="nav" data-screen="projects">← Библиотека</button><button class="btn solid" data-action="new-episode">＋ Добавить серию</button>`)}<div class="episode-cover" data-tone="${p.tone || "blue"}"><div class="inside"><div class="kicker">ПРОЕКТ · ${String(eps.length).padStart(2, "0")} ЭПИЗОДОВ</div><h1>${esc(p.title)}</h1><p>${summary.ready} готовых серий · ${summary.running ? "Монтаж идёт" : "Нет активных монтажей"} · Начат ${stamp(p.created_at)}</p><div class="inline-controls"><button class="btn sm" data-action="new-episode">＋ Новая серия</button><button class="btn sm red" data-action="delete-project" data-id="${esc(p.id)}">Удалить проект</button></div></div></div><div class="section-title"><h2>Список серий</h2><span class="tiny-note">${eps.length} · Отсортировано по номеру</span></div><div class="episodes-list">${eps
      .map((e) => {
        const j = latest(e.id);
        return `<article class="episode-item panel"><div class="episode-number">${String(e.number).padStart(2, "0")}</div><div class="episode-info"><h3>Серия ${e.number}</h3><p>${esc(sourceBy(e.source_id)?.name || "Видео ещё не выбрано")} · ${jobsFor(e.id).length} запусков</p></div><div class="status-col">${j ? badge(j.status) : '<span class="badge muted">Без монтажа</span>'}</div><div class="episode-actions"><button class="btn sm" data-action="open-episode" data-id="${esc(e.id)}">⚙ Настроить</button>${jobsFor(e.id).some((job) => job.status === "completed") ? `<button class="btn sm green" data-action="open-review" data-id="${esc(e.id)}">▷ Shorts</button>` : ""}${j && j.status !== "completed" ? `<button class="btn sm clear" data-action="open-job" data-id="${esc(j.id)}">◷ Монтаж</button>` : ""}<button class="btn sm red" data-action="delete-episode" data-id="${esc(e.id)}" title="Поместить в корзину">✕</button></div></article>`;
      })
      .join(
        "",
      )}</div>${eps.length ? "" : '<div class="empty"><strong>Серий пока нет</strong>Создайте первую серию — тогда появятся настройки исходного видео и монтажа.</div>'}`;
  }
  function currentEdit() {
    if (!ui.editing || ui.editing.episodeId !== ui.episodeId) {
      const e = currE();
      ui.editing = {
        episodeId: ui.episodeId,
        source_id: e?.source_id || "",
        ...e?.settings,
        frame_style: db.finishing[ui.episodeId]?.video?.frame_style || "plain",
        card_variant: db.finishing[ui.episodeId]?.video?.card_variant || "compact",
        channel_handle: db.finishing[ui.episodeId]?.video?.channel_handle || "",
        channel_name: db.finishing[ui.episodeId]?.video?.channel_name || "",
        post_caption: db.finishing[ui.episodeId]?.video?.post_caption || "",
      };
      ui.draftMusic = structuredClone(db.music);
    }
    return ui.editing;
  }
  function renderEditor() {
    const e = currE();
    if (!e || !aliveE(e)) return `<div class="empty">Выберите серию</div>`;
    if (!db.finishing[e.id]) return '<div class="empty">Загружаем оформление серии…</div>';
    const d = currentEdit(),
      m = ui.draftMusic,
      src = sourceBy(d.source_id),
      isRunning = jobsFor(e.id).some((x) => x.status === "running");
    const sourceOptions = db.sources
      .map((s) => {
        const used = db.episodes.some(
          (x) => x.id !== e.id && aliveE(x) && x.source_id === s.id,
        );
        return `<option value="${esc(s.id)}" ${s.id === d.source_id ? "selected" : ""} ${used ? "disabled" : ""}>${esc(s.name)}${used ? " (занят)" : ""}</option>`;
      })
      .join("");
    return `${header(`СЕРИЯ ${String(e.number).padStart(2, "0")} / ПАРАМЕТРЫ`, "Настройка монтажа", `Проект «${esc(currP()?.title || "")}». Настройки сохраняются отдельно от запуска монтажа.`, `<button class="btn clear" data-action="nav" data-screen="episodes">← К сериям</button>${jobsFor(e.id).some((x) => x.status === "completed") ? '<button class="btn" data-action="open-review">▷ Проверить готовые</button>' : ""}`)}
<div class="two-col"><div class="editor-left"><section class="panel setting-panel"><div class="section-heading"><div class="sym">▣</div><h2>Исходный видеофайл</h2><span>MP4 / MKV</span></div><label class="form-label" for="sourceSelect">Видео этой серии</label><div class="form-line"><select class="form-select" id="sourceSelect"><option value="">— Выберите видео —</option>${sourceOptions}</select><button class="btn" data-action="refresh-sources">↻</button></div><div class="field-hint" id="sourceInfo">${src ? `${esc(src.name)} · ${kb(src.size)}` : "Пока исходное видео не закреплено за серией."}</div><div class="divider"></div><div class="inline-controls"><button class="btn" data-action="upload-video">↥ Импортировать видео</button><span class="caption">До 20 ГБ · файл сохраняется в локальной библиотеке</span></div></section>
<section class="panel setting-panel"><div class="section-heading"><div class="sym">▧</div><h2>Оформление Shorts</h2><span>1080 × 1920 · 9:16</span></div><label class="form-label">Расположение видео</label><div class="choice-row"><label class="option-card"><input name="layout" type="radio" value="cinema" ${d.layout === "cinema" && d.frame_style !== "social" ? "checked" : ""}><span class="mini-layout"></span><strong>Весь кадр + мягкий фон</strong><small>Всё действие видно. Фон — размытая копия кадра.</small></label><label class="option-card"><input name="layout" type="radio" value="portrait" ${d.layout === "portrait" && d.frame_style !== "social" ? "checked" : ""}><span class="mini-layout crop"></span><strong>Умное кадрирование</strong><small>Крупный план героя, фокус на движении.</small></label><label class="option-card"><input name="layout" type="radio" value="social" ${d.frame_style === "social" ? "checked" : ""}><span class="mini-layout social"></span><strong>Карточка публикации</strong><small>Весь кадр, мягкий фон, канал и подпись.</small></label></div><div id="socialFields" class="social-fields" ${d.frame_style === "social" ? "" : "hidden"}><label class="form-label" for="socialVariant">Стиль карточки</label><select class="form-select" id="socialVariant"><option value="compact" ${d.card_variant === "compact" ? "selected" : ""}>Компактная карточка</option><option value="post" ${d.card_variant === "post" ? "selected" : ""}>Пост · крупная подпись</option></select><label class="form-label" for="socialChannel">Название канала</label><input class="form-input" id="socialChannel" maxlength="60" value="${esc(d.channel_name)}" placeholder="Название вашего канала"><div id="socialHandleField" ${d.card_variant === "post" ? "" : "hidden"}><label class="form-label" for="socialHandle">Адрес канала</label><input class="form-input" id="socialHandle" maxlength="60" value="${esc(d.channel_handle)}" placeholder="@ваш_канал"></div><label class="form-label" for="socialCaption">Подпись к видео</label><textarea class="area" id="socialCaption" maxlength="180" rows="3" placeholder="Ваша подпись">${esc(d.post_caption)}</textarea><p class="field-hint">Рамка и текст будут встроены в готовый MP4.</p></div><div class="divider"></div><label class="form-label">Субтитры</label><div class="choice-row"><label class="option-card"><input name="caption" type="radio" value="accent" ${d.caption_style === "accent" ? "checked" : ""}><strong style="color:#ffe383;font-size:14px">Яркие · короткие</strong><small>Жёлтые с обводкой, крупные фразы.</small></label><label class="option-card"><input name="caption" type="radio" value="classic" ${d.caption_style === "classic" ? "checked" : ""}><strong style="font-size:14px">Классические</strong><small>Белый текст с мягкой тенью.</small></label></div></section>
<section class="panel setting-panel"><div class="section-heading"><div class="sym">✧</div><h2>Анализ истории</h2></div><label class="form-label" for="analysisSelect">Способ анализа сцены и изображения</label><select class="form-select" id="analysisSelect"><option value="deepseek_plan" ${d.analysis_provider === "deepseek_plan" ? "selected" : ""}>DeepSeek · сюжет и план, кадрирование локально</option><option value="antigravity_manual">Antigravity CLI (ручной запуск)</option><option value="local" ${d.analysis_provider === "local" ? "selected" : ""}>На компьютере · без сети</option><option value="hybrid" ${d.analysis_provider === "hybrid" ? "selected" : ""}>Локально + DeepSeek при сомнениях</option><option value="deepseek" ${d.analysis_provider === "deepseek" ? "selected" : ""}>DeepSeek · анализ через облако</option></select><p id="providerHint" class="field-hint"></p><details class="expand"><summary>Подключение DeepSeek</summary><div class="expanded"><div class="data-row"><span>Настроен</span><b id="dConfigured">${db.deepseek.configured ? "Да" : "Нет"}</b></div><div class="data-row"><span>Модель</span><b>${esc(db.deepseek.model)}</b></div><div class="inline-controls spaced"><button class="btn sm" data-action="check-deepseek">Проверить подключение</button></div><p class="caption">Стоимость облачного анализа проверяйте в кабинете DeepSeek.</p></div></details></section>
<section class="panel setting-panel"><div class="section-heading"><div class="sym">♫</div><h2>Фоновая музыка</h2><span>${db.music.tracks.length} трека</span></div><label class="switch-line"><span>Добавлять музыку в шортсы</span><input id="musicEnabled" type="checkbox" ${m.enabled ? "checked" : ""}></label><div id="musicSettings" style="${m.enabled ? "" : "opacity:.45;pointer-events:none"}"><div class="divider"></div><div class="range-header"><label class="form-label" for="musicVolume">Громкость</label><output id="volumeValue">${Math.round(m.volume * 100)}%</output></div><input type="range" id="musicVolume" min="0" max="100" value="${Math.round(m.volume * 100)}"><div class="spaced"><label class="form-label" for="musicMode">Режим подстановки</label><select class="form-select" id="musicMode"><option value="single" ${m.mode === "single" ? "selected" : ""}>Один трек на все части</option><option value="random_per_part" ${m.mode === "random_per_part" ? "selected" : ""}>Случайный для каждой части</option><option value="per_part" ${m.mode === "per_part" ? "selected" : ""}>Выбор трека по частям</option></select></div><div id="musicTrackOptions" class="spaced">${musicOptions()}</div></div><div class="inline-controls spaced"><button class="btn sm" data-action="music-folder">▣ Открыть папку</button><button class="btn sm" data-action="refresh-music">↻ Обновить</button><button class="btn sm clear" data-action="copy-music-path">⧉ Путь</button></div><div class="field-hint">Музыка — глобальные настройки /api/music, независимо от параметров серии.</div></section>
<div class="sticky-bottom"><span class="form-status" id="editStatus"></span><button class="btn" data-action="save-settings">Сохранить настройки</button><button class="btn solid" data-action="launch" ${!d.source_id || isRunning ? "disabled" : ""}>▷ Запустить монтаж</button></div></div>
<aside class="editor-right"><section class="panel preview-panel"><div class="preview-header"><h3>Живой предпросмотр</h3><span class="badge good">9:16 / SHORTS</span></div><div class="phone-wrap">${phoneHTML(d.layout, d.caption_style, 0, true)}</div><div class="preview-controls"><span>Предпросмотр выбранного исходника</span><span>Параметры исходного видео</span></div><div class="ready-info panel" style="background:#0e1723"><h3>Что получим при экспорте</h3><div class="data-row"><span>Видео</span><b>H.264 / MP4</b></div><div class="data-row"><span>Аудио</span><b>Оригинал + музыка</b></div><div class="data-row"><span>Субтитры</span><b>Встроенные + SRT</b></div><div class="data-row"><span>Максимальная длина части</span><b>120 сек.</b></div>${latest(e.id) ? `<button class="btn sm" data-action="open-job" data-id="${esc(latest(e.id).id)}">◷ История последнего монтажа →</button>` : ""}</div></section></aside></div>`;
  }
  function musicOptions() {
    const m = ui.draftMusic || db.music,
      tracks = m.tracks || db.music.tracks;
    if (m.mode === "random_per_part")
      return `<div class="field-hint">При запуске для каждой части случайно выбирается один из ${tracks.length} треков.</div>`;
    if (m.mode === "single")
      return `<label class="form-label">Трек для всех частей</label><select class="form-select" id="musicTrack"><option value="">Случайный трек</option>${tracks.map((t) => `<option value="${esc(t)}" ${t === m.track ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
    const parts = db.plans[latest(ui.episodeId)?.id]?.parts || [];
    if (!parts.length) return `<div class="field-hint">Выбор музыки по частям доступен после составления монтажного плана.</div>`;
    return `<label class="form-label">Треки по частям</label><div class="music-tracks">${parts.map((part) => `<label class="music-track"><span>Часть ${String(part.index).padStart(2, "0")}</span><select class="form-select partTrack" data-part="${part.index}"><option value="">Случайный</option>${tracks.map((t) => `<option value="${esc(t)}" ${m.part_tracks?.[String(part.index)] === t ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`).join("")}</div><div class="field-hint">В приложении количество частей уточняется после составления плана.</div>`;
  }
  function phoneHTML(
    layout = "cinema",
    caption = "accent",
    part = 0,
    preview = false,
  ) {
    const local =
      ui.localMedia[
        preview ? currentEdit().source_id : currentJob()?.source_id
      ];
    const video =
      preview && local
        ? `<video muted autoplay loop playsinline src="${local}"></video>`
        : "";
    return `<div class="phone ${layout === "portrait" ? "crop" : ""} ${caption === "classic" ? "classic" : ""}" id="${preview ? "editorPhone" : "reviewPhone"}"><div class="phone-bg"></div><div class="part-label">ЧАСТЬ ${String(part + 1).padStart(2, "0")}</div><div class="phone-social-card"></div><div class="phone-social-header"><div><b></b><small class="phone-social-handle"></small></div><span>•••</span></div><div class="phone-scene">${video}</div><div class="phone-social-caption"></div><div class="subs" id="${preview ? "previewSubs" : "reviewSubs"}">${esc(db.plans[currentJob()?.id]?.parts?.[part]?.subtitles?.[0]?.text || "")}</div><div class="phone-bar"></div></div>`;
  }
  function fitPublicationText(element, maximum, minimum = 18) {
    if (!element?.clientWidth || !element.clientHeight) return;
    for (let size = maximum; size >= minimum; size--) {
      element.style.fontSize = (size / 1080 * 100) + "cqw";
      if (element.scrollHeight <= element.clientHeight && element.scrollWidth <= element.clientWidth) break;
    }
  }
  function syncPreview() {
    const d = currentEdit(),
      ph = $("editorPhone");
    if (!ph) return;
    ph.classList.toggle("crop", d.layout === "portrait");
    ph.classList.toggle("classic", d.caption_style === "classic");
    ph.classList.toggle("social-mode", d.frame_style === "social");
    ph.querySelector(".phone-social-header b").textContent = d.channel_name;
    ph.classList.toggle("post-card", d.card_variant === "post");
    ph.querySelector(".phone-social-handle").textContent = d.channel_handle ? "@" + d.channel_handle.replace(/^@+/, "") : "";
    if ($("socialHandleField")) $("socialHandleField").hidden = d.card_variant !== "post";
    ph.querySelector(".phone-social-caption").textContent = d.post_caption;
    fitPublicationText(ph.querySelector(".phone-social-header b"), 44, 12);
    fitPublicationText(ph.querySelector(".phone-social-caption"), d.card_variant === "post" ? 48 : 34);
    const socialFields = $("socialFields");
    if (socialFields) socialFields.hidden = d.frame_style !== "social";
    const launch = document.querySelector("[data-action=launch]");
    if (launch)
      launch.textContent =
        d.analysis_provider === "antigravity_manual"
          ? "Подготовить данные"
          : "▷ Запустить монтаж";
    const prov = $("providerHint");
    if (prov)
      prov.textContent =
        {
          antigravity_manual:
            "Облачный анализ через отдельный сценарий Antigravity. Инструкции появятся после запуска.",
          local:
            "Видео обрабатывается на компьютере без подключения к облаку.",
          deepseek_plan:
            "DeepSeek выбирает сюжет и план, окончательное кадрирование — локально.",
          hybrid:
            "Локальная модель работает первой; сомнения уточняются через DeepSeek.",
          deepseek:
            "Облачный анализ DeepSeek. Возможны платные запросы.",
        }[d.analysis_provider] || "";
  }
  function bindEditor() {
    if (!$("sourceSelect")) return;
    const d = currentEdit(),
      m = ui.draftMusic;
    $("socialVariant")?.addEventListener("change", (event) => { d.card_variant = event.target.value; syncPreview(); });
    $("sourceSelect")?.addEventListener("change", (e) => {
      d.source_id = e.target.value;
      const s = sourceBy(d.source_id);
      $("sourceInfo").textContent = s
        ? `${s.name} · ${kb(s.size)}`
        : "Видео не выбрано";
      const btn = document.querySelector("[data-action=launch]");
      if (btn) btn.disabled = !d.source_id;
    });
    document.querySelectorAll("input[name=layout]").forEach(
      (x) =>
        (x.onchange = () => {
          d.layout = x.value === "social" ? "cinema" : x.value;
          d.frame_style = x.value === "social" ? "social" : "plain";
          syncPreview();
        }),
    );
    for (const [id, key] of [["socialChannel", "channel_name"], ["socialHandle", "channel_handle"], ["socialCaption", "post_caption"]]) {
      $(id)?.addEventListener("input", (event) => {
        d[key] = event.target.value;
        syncPreview();
      });
    }
    document.querySelectorAll("input[name=caption]").forEach(
      (x) =>
        (x.onchange = () => {
          d.caption_style = x.value;
          syncPreview();
        }),
    );
    $("analysisSelect").onchange = (e) => {
      d.analysis_provider = e.target.value;
      syncPreview();
    };
    $("musicEnabled").onchange = (e) => {
      m.enabled = e.target.checked;
      $("musicSettings").style.opacity = m.enabled ? "1" : ".45";
      $("musicSettings").style.pointerEvents = m.enabled ? "auto" : "none";
    };
    $("musicVolume").oninput = (e) => {
      m.volume = Number(e.target.value) / 100;
      $("volumeValue").textContent = e.target.value + "%";
    };
    $("musicMode").onchange = (e) => {
      m.mode = e.target.value;
      $("musicTrackOptions").innerHTML = musicOptions();
      bindMusicExtra();
    };
    bindMusicExtra();
  }
  function bindMusicExtra() {
    $("musicTrack")?.addEventListener(
      "change",
      (e) => (ui.draftMusic.track = e.target.value || null),
    );
    document.querySelectorAll(".partTrack").forEach((x) =>
      x.addEventListener("change", (e) => {
        ui.draftMusic.part_tracks[e.target.dataset.part] =
          e.target.value || null;
      }),
    );
  }
  function tokenLabel(t) {
    if (!t) return "Статистика токенов ещё не загружена";
    const fmt = (n) => new Intl.NumberFormat("ru-RU").format(n || 0);
    const calls = (t.local?.calls || 0) + (t.deepseek?.calls || 0),
      unknown = t.unknown_calls || 0;
    if (t.available === false || (!calls && !unknown))
      return "Нет сохранённых данных о токенах";
    if (!calls)
      return (
        "Статистика токенов не предоставлена · " +
        fmt(unknown) +
        " ответов без статистики токенов"
      );
    const provider = (p) => (p?.calls ? fmt(p.total_tokens) : "нет данных");
    return (
      "Локально: " +
      provider(t.local) +
      " · DeepSeek: " +
      provider(t.deepseek) +
      " · " +
      (unknown ? "Известно: " : "Всего: ") +
      fmt(t.all_tokens) +
      " токенов (" +
      fmt(calls) +
      " запросов со статистикой)" +
      (unknown ? " · " + fmt(unknown) + " ответов без статистики токенов" : "")
    );
  }
  async function updateTokenView() {
    const j = currentJob();
    if (!j || ui.screen !== "processing") return;
    try {
      const tokens = await window.KadrBridge.get(
        "/api/jobs/" + encodeURIComponent(j.id) + "/tokens",
      );
      const el = $("jobTokens");
      if (el) el.textContent = tokenLabel(tokens);
    } catch (error) {
      const el = $("jobTokens");
      if (el) el.textContent = "Учёт токенов недоступен: " + error.message;
    }
  }
  function renderManualPanel(j) {
    const supported =
      ["local", "antigravity_manual"].includes(j.analysis_provider) &&
      j.status !== "completed";
    if (!supported) return "";
    const manual = j.analysis_provider === "antigravity_manual",
      idle = !["running", "queued"].includes(j.status),
      packets = manual ? db.manualAnalysis?.[j.id]?.packets || [] : [];
    const exchange = db.manualAnalysis?.[j.id] || {},
      automatic = !!exchange.automation?.enabled;
    const command = `powershell -NoProfile -ExecutionPolicy Bypass -File F:\\new_prodject\\scripts\\run_antigravity_job.ps1 -JobDirectory "${exchange.job_directory || ""}"`;
    return `<div class="panel" style="padding:24px;margin-top:17px"><div class="section-title"><h2>Antigravity CLI · отдельный запуск</h2></div><p class="caption">Запустите сценарий Antigravity отдельно и оставьте его открытым до завершения анализа. Результаты можно загрузить вручную.</p><div class="inline-controls"><button class="btn sm" data-action="manual-prepare" data-id="${esc(j.id)}" ${idle ? "" : "disabled"}>${automatic ? "Запустить / продолжить анализ" : "Подготовить данные"}</button><button class="btn sm" data-action="manual-open" data-id="${esc(j.id)}">Открыть папку анализа</button>${manual ? `<button class="btn sm" data-action="manual-auto" data-id="${esc(j.id)}" ${idle ? "" : "disabled"}>Автоимпорт: ${automatic ? "выключить" : "включить"}</button><button class="btn sm" data-action="manual-return" data-id="${esc(j.id)}" ${idle ? "" : "disabled"}>Вернуться к Qwen 9B</button>` : ""}</div>${automatic ? `<p class="caption">После запуска анализа один раз выполните эту команду в отдельном PowerShell. Оставьте окно открытым: ответы принимаются автоматически до готового монтажа. Общего лимита времени нет. При ошибке или отмене сценарий остановится.</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere;user-select:text">${esc(command)}</pre><p class="caption">Отдельный сценарий: ${esc({ waiting: "ожидает пакет", processing: "обрабатывает пакет", completed: "завершён", stopped: "остановлен", budget_exhausted: "тестовый лимит времени исчерпан; результаты сохранены", error: "ошибка" }[exchange.runner?.status] || "ещё не запущен")}</p>` : ""}${renderPacketSummary(packets, j.id, idle)}<input hidden type="file" id="manualResultFile" accept=".json,application/json"></div>`;
  }
  function processingMessage(job) {
    return typeof job.error === "string" && job.error.trim()
      ? job.error
      : job.message || "";
  }
  function renderPacketSummary(packets, jobId, idle) {
    if (!packets.length) return '<p class="caption">Пакетов пока нет.</p>';
    const counts = { waiting: 0, ready: 0, error: 0 };
    for (const packet of packets)
      if (packet.status in counts) counts[packet.status]++;
    const activeErrors = packets.filter((packet) => packet.status === "error");
    const entry = (packet) =>
      `<div class="data-row"><span>${esc(packet.purpose)}${packet.batch_size ? ` · ${esc(packet.batch_size)} задания в одном запросе` : ""} · ${esc(packet.id.slice(0, 12))}<br>${esc({ waiting: "Ожидает обработки", ready: "Ответ сохранён", error: "Ошибка" }[packet.status] || packet.status)}</span><button class="btn sm" data-action="manual-import" data-id="${esc(jobId)}" data-packet="${esc(packet.id)}" ${idle ? "" : "disabled"}>Импортировать результат</button></div>`;
    return `<p class="caption">Пакеты: ${counts.ready} готовы · ${counts.waiting} ожидают · ${counts.error} с ошибкой в истории</p>${idle && activeErrors.length ? `<p class="caption">Есть ошибки пакетов. Подробности доступны ниже.</p>` : ""}<details class="expand" id="manualPacketDetails"><summary>Подробности пакетов (${packets.length})</summary><div class="expanded" id="manualPackets">${packets.map(entry).join("")}</div></details>`;
  }
  async function updateManualView() {
    const j = currentJob();
    if (!j || j.analysis_provider !== "antigravity_manual") return;
    try {
      const data = await window.KadrBridge.get(`/api/jobs/${j.id}/antigravity`);
      db.manualAnalysis ||= {};
      const changed =
        JSON.stringify(db.manualAnalysis[j.id]) !== JSON.stringify(data);
      const expanded = $("manualPacketDetails")?.open;
      db.manualAnalysis[j.id] = data;
      if (changed && ui.screen === "processing") {
        render();
        if (expanded && $("manualPacketDetails"))
          $("manualPacketDetails").open = true;
      }
    } catch (error) {
      console.warn("Manual packet status unavailable:", error.message);
    }
  }
  function renderProcessing() {
    const e = currE(),
      j = currentJob();
    if (!j) return `<div class="empty">Монтажей ещё не было.</div>`;
    const current = processingProgress(j),
      progress = current.percent;
    const hist = jobsFor(e.id);
    return `${header(`МОНТАЖ / СЕРИЯ ${e.number}`, "Процесс обработки", "Следите за этапами монтажа и открывайте готовые Shorts.", `<button class="btn clear" data-action="nav" data-screen="editor">⚙ Параметры серии</button>${j.status === "completed" ? '<button class="btn solid" data-action="open-review">▷ Проверить Shorts</button>' : ""}`)}<div class="progress-dashboard"><section class="process-main"><div class="panel process-stat"><div class="progress-head"><div><div class="eyebrow">ЗАДАНИЕ / ${esc(j.id.slice(0, 8))}</div><h2>${j.status === "running" ? "Идёт монтаж серии" : statusLabel(j.status)}</h2></div>${badge(j.status)}</div><div class="percentage" id="percentage">${progress === null ? "…" : progress + '<span style="font-size:26px;letter-spacing:0">%</span>'}</div><p class="caption" id="currentStageLabel">${esc(current.label)}</p><p class="lede" id="stageMessage">${esc(processingMessage(j))}</p><div class="progress-track"><i id="jobBar" style="width:${progress === null ? 0 : progress}%"></i></div><div class="panel" style="padding:12px 15px;margin:14px 0;background:#101a16"><div class="section-title" style="margin-bottom:9px"><h2 style="font-size:12px">Токены моделей · этот запуск</h2><span class="tiny-note">Сохранённая статистика ответов моделей</span></div><div id="jobTokens" style="font-size:12px;color:#d4e8ba;line-height:1.8">Загружаем данные…</div></div><div class="inline-controls">${j.status === "running" ? `<button class="btn red" data-action="cancel-job" data-id="${esc(j.id)}">■ Отменить монтаж</button>` : ""}${["interrupted", "failed", "cancelled", "waiting_analysis"].includes(j.status) ? `<button class="btn solid" data-action="retry-job" data-id="${esc(j.id)}">↺ Продолжить обработку</button>` : ""}<button class="btn" data-action="read-job" data-id="${esc(j.id)}">↻ Обновить статус</button>${j.status === "completed" ? `<button class="btn solid" data-action="open-review">▷ К шортсам</button>` : ""}</div></div>
<div class="panel" style="padding:24px;margin-top:17px"><div class="section-title"><h2>Этапы монтажа</h2></div><div class="process-stage-list" id="stageRows">${processingStageRows(j)}</div></div>
<div class="panel" style="padding:24px;margin-top:17px"><div class="section-title"><h2>История монтажей</h2><span class="tiny-note">${hist.length} попыток</span></div>${hist.map((h) => `<div class="history-row"><div><strong>Монтаж ${esc(h.id.slice(0, 8))}</strong><br><span>${stamp(h.created_at)}</span></div>${badge(h.status)}<button class="btn sm" data-action="open-job" data-id="${esc(h.id)}">Открыть →</button></div>`).join("")}</div>${renderManualPanel(j)}</section>
<aside style="display:grid;gap:17px"><div class="panel" style="padding:23px"><div class="section-title"><h2>Параметры монтажа</h2></div><div class="data-row"><span>Видеофайл</span><b style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(j.source_name)}">${esc(j.source_name)}</b></div><div class="data-row"><span>Анализ</span><b>${esc(providerLabel(j.analysis_provider))}</b></div><div class="data-row"><span>Кадр</span><b>${j.layout === "cinema" ? "Весь кадр" : "Умное кадрирование"}</b></div><div class="data-row"><span>Субтитры</span><b>${j.caption_style === "accent" ? "С акцентом" : "Классические"}</b></div><div class="data-row"><span>Запущено</span><b>${stamp(j.created_at)}</b></div><div class="data-row"><span>Повтор</span><b>${j.attempt || 1}</b></div><div class="data-row"><span>Файлов</span><b>${publicJob(j).files.length}</b></div><div class="downloads">${j.status !== "running" ? `<button class="btn sm red" data-action="delete-job" data-id="${esc(j.id)}">Удалить запись</button>` : ""}</div></div><div class="panel" style="padding:23px"><div class="section-title"><h2>Сводка статуса</h2><span class="tiny-note">Последние события</span></div><div class="log-box" id="progressLog">${(
      j.logs || [
        { time: j.created_at, text: "Создано задание" },
        { time: j.updated_at, text: j.message },
      ]
    )
      .map(
        (l) =>
          `<p><time>${new Date(l.time).toLocaleTimeString("ru-RU")}</time> &nbsp; ${esc(l.text)}</p>`,
      )
      .join("")}</div></div></aside></div>`;
  }
  function bindProcessing() {
    if (ui.screen === "processing") {
      updateTokenView();
      updateManualView();
      runTicker();
    }
  }
  function processingProgress(job) {
    const rows = processingRows(job);
    if (job.status === "completed")
      return { percent: 100, label: "Все этапы завершены" };
    const code =
      Object.keys(rows).find((key) =>
        [
          "running",
          "cancelled",
          "failed",
          "interrupted",
          "waiting_analysis",
        ].includes(rows[key]?.status),
      ) || job.stage;
    const row = rows[code] || {},
      title =
        processingStages.find(([key]) => key === code)?.[1] || "Ожидание этапа";
    const fraction =
      typeof row.fraction === "number" && Number.isFinite(row.fraction)
        ? Math.max(0, Math.min(1, row.fraction))
        : null;
    return {
      percent: fraction === null ? null : Math.round(fraction * 100),
      label: `${title}${row.phase ? " · " + row.phase : ""}${fraction === null ? " · точный прогресс пока не сообщается" : ""}`,
    };
  }
  const analysisStages = [
    ["visual_analysis", "Анализ кадров и речи"],
    ["story_refinement", "Отбор смысловых сцен"],
    ["titles", "Проверка титров и заставок"],
    ["closing_novelty", "Проверка событий в финале"],
    ["source_roles", "Проверка речи, озвучки и анонсов"],
    ["global_visual_verification", "Независимая проверка сцен"],
    ["selection_adjudication", "Проверка спорного выбора"],
    ["global_story", "Проверка истории целиком"],
    ["pacing", "Проверка темпа сцен"],
    ["silent_sequences", "Проверка безречевых последовательностей"],
    ["final_selection_adjudication", "Проверка итогового отбора"],
    ["endings", "Проверка завершения истории"],
    [
      "ending_selection_adjudication",
      "Повторная проверка финала при необходимости",
    ],
    ["story_structure_analysis", "Построение сюжетных связей"],
    ["dialogue_relations", "Проверка связей между репликами"],
  ];
  const processingStages = [
    ...stages.slice(0, 3),
    ...analysisStages,
    ...stages.slice(5),
  ];
  function processingRows(job) {
    const rows = {
      ...(job.stage_progress || {}),
      ...(job.analysis_passes || {}),
    };
    if (!job.analysis_passes) {
      rows.visual_analysis = rows.analyze;
      rows.story_refinement = rows.condense;
    }
    return Object.fromEntries(
      processingStages.map(([code]) => [
        code,
        rows[code] || { status: "pending", fraction: 0 },
      ]),
    );
  }
  function processingStageRows(job) {
    const rows = processingRows(job);
    return processingStages
      .map(([code, title]) => {
        const row = rows[code] || {},
          done = row.status === "completed",
          active = row.status === "running",
          fraction =
            typeof row.fraction === "number" && Number.isFinite(row.fraction)
              ? Math.round(Math.max(0, Math.min(1, row.fraction)) * 100)
              : null;
        const count =
          Number.isInteger(row.completed) && Number.isInteger(row.total)
            ? ` · ${row.completed} из ${row.total}`
            : "";
        const label = done
          ? "100% · Готово"
          : active
            ? (fraction === null ? "Выполняется" : fraction + "%") + count
            : {
                failed:
                  row.phase === "Нужны уточнения"
                    ? "Нужны уточнения" +
                      (Number.isInteger(row.unresolved)
                        ? ` · ${row.unresolved} фрагм.`
                        : "")
                    : "Ошибка",
                cancelled: "Отменено",
                interrupted: "Прервано",
                waiting_analysis: "Ожидает ответа agy",
                not_required: "Не потребовалось",
              }[row.status] || "0% · Ожидает";
        return `<div class="stage-row ${done ? "done" : active ? "active" : ""}"><span>${done ? "✓" : active ? "◉" : "○"} &nbsp; ${esc(title)}</span><i>${esc(label)}</i></div>`;
      })
      .join("");
  }
  function runTicker() {
    clearInterval(processTimer);
    let polling = false;
    processTimer = setInterval(async () => {
      if (polling) return;
      if (ui.screen !== "processing") return;
      polling = true;
      try {
        updateTokenView();
        const current = ui.jobId;
        const previous = db.jobs.find((j) => j.id === current);
        const oldStatus = previous?.status,
          oldStage = previous?.stage;
        await window.KadrBridge.refresh(db, ui);
        await updateManualView();
        const job = db.jobs.find((j) => j.id === current);
        if (ui.screen === "processing" && job) {
          if (oldStatus !== job.status || oldStage !== job.stage) {
            render();
            if (oldStatus === "running" && job.status === "completed")
              notify("Монтаж завершён. Shorts готовы к проверке.");
          } else {
            const percentage = $("percentage"),
              bar = $("jobBar"),
              message = $("stageMessage");
            const current = processingProgress(job);
            if (percentage)
              percentage.innerHTML =
                current.percent === null
                  ? "…"
                  : current.percent + '<span style="font-size:26px">%</span>';
            if ($("currentStageLabel"))
              $("currentStageLabel").textContent = current.label;
            if ($("stageRows"))
              $("stageRows").innerHTML = processingStageRows(job);
            if (bar)
              bar.style.width =
                (current.percent === null ? 0 : current.percent) + "%";
            if (message) message.textContent = processingMessage(job);
          }
        }
        // Other views aren't re-rendered every few seconds: doing so would stop
        // video playback and lose focus while editing captions.
      } catch (error) {
        console.warn("Live status polling failed", error);
      } finally {
        polling = false;
      }
    }, 3200);
  }
  function reviewTime(sec) {
    const v = Math.max(0, Math.floor(Number(sec) || 0));
    return v >= 3600
      ? `${Math.floor(v / 3600)}:${String(Math.floor((v % 3600) / 60)).padStart(2, "0")}:${String(v % 60).padStart(2, "0")}`
      : `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`;
  }
  function reviewSegments(plan) {
    const cuts = (plan.parts || [])
      .flatMap((p, pi) =>
        (p.cuts || []).map((c, ci) => ({
          kind: "kept",
          start: Number(c.start),
          end: Number(c.end),
          part: pi,
          cut: ci,
          key: `k-${pi}-${ci}`,
        })),
      )
      .filter(
        (c) =>
          Number.isFinite(c.start) && Number.isFinite(c.end) && c.end > c.start,
      )
      .sort((a, b) => a.start - b.start);
    let result = [],
      cursor = 0;
    for (const c of cuts) {
      if (c.start > cursor + 0.001)
        result.push({
          kind: "removed",
          start: cursor,
          end: c.start,
          key: `r-${Math.round(cursor * 1000)}`,
        });
      if (c.end > cursor) {
        result.push({ ...c, start: Math.max(c.start, cursor) });
        cursor = c.end;
      }
    }
    if (cursor < plan.duration)
      result.push({
        kind: "removed",
        start: cursor,
        end: plan.duration,
        key: `r-${Math.round(cursor * 1000)}`,
      });
    return result;
  }
  function reviewSelection(plan) {
    const a = reviewSegments(plan);
    return (
      a.find((s) => s.key === ui.reviewSelection) ||
      a.find((s) => s.kind === "kept" && s.part === ui.part) ||
      a[0]
    );
  }
  function reviewGetSource(j) {
    return "/api/jobs/" + encodeURIComponent(j.id) + "/source";
  }
  function reviewGetShort(j, index) {
    return j?.files?.[index]?.url || "";
  }
  function reviewSourceStage(j, compact = false) {
    return `<div class="rv-source-box ${compact ? "rv-comp-source" : ""}"><video id="reviewSourceVideo" controls playsinline preload="metadata" aria-label="Исходная серия" src="${reviewGetSource(j)}"></video></div>`;
  }
  function reviewShortStage(j, idx, compact = false) {
    return `<div class="rv-phone-shell ${compact ? "rv-compare-phone" : ""}"><div class="rv-phone-grad"></div><div class="rv-phone-top"><b>КАДР</b><span>ЧАСТЬ ${String(idx + 1).padStart(2, "0")}</span></div><div class="rv-phone-film"><video id="reviewShortVideo" controls playsinline preload="metadata" aria-label="Готовый вертикальный Shorts, часть ${idx + 1}" src="${reviewGetShort(j, idx)}"></video></div><div class="rv-phone-captions ${j.caption_style === "classic" ? "is-white" : ""}"></div><div class="rv-phone-bottom"><span>9:16 · ${j.layout === "portrait" ? "крупный план" : "полный кадр"}</span><span>●</span></div></div>`;
  }
  function reviewStage(j, plan, sel) {
    const mode = ui.reviewMode || "short";
    if (mode === "source")
      return `<div class="rv-stage rv-single-source">${reviewSourceStage(j)}</div>`;
    if (mode === "compare")
      return `<div class="rv-stage rv-comparison"><div class="rv-compare-col"><div class="rv-stage-label"><span class="rv-dot blue"></span> Исходник <small>16:9</small></div>${reviewSourceStage(j, true)}</div><div class="rv-compare-col rv-compare-right"><div class="rv-stage-label"><span class="rv-dot purple"></span> Готовый Shorts <small>9:16</small></div>${reviewShortStage(j, ui.part, true)}</div></div>`;
    return `<div class="rv-stage rv-single-short">${reviewShortStage(j, ui.part)}</div>`;
  }
  function renderReview() {
    const e = currE(),
      j = currentJob(),
      plan = db.plans[j?.id];
    if (j?.status === "completed" && !plan)
      return `<div class="empty" role="status">Загружаем готовые Shorts…</div>`;
    if (!j || j.status !== "completed" || !Array.isArray(plan?.parts) || !plan.parts.length)
      return `<div class="empty"><strong>Нет готовых частей</strong>Сначала завершите монтаж выбранной серии.</div>`;
    ui.part = Math.max(0, Math.min(plan.parts.length - 1, ui.part));
    const part = plan.parts[ui.part],
      all = reviewSegments(plan),
      sel = reviewSelection(plan),
      files = publicJob(j).files,
      fmt = files[ui.part] || files[0],
      saved = all.filter((x) => x.kind === "kept"),
      keptTime = saved.reduce((a, s) => a + s.end - s.start, 0),
      mode = ui.reviewMode || "compare",
      warn = plan.quality_summary?.warnings || [],
      reasons = plan.debug_timeline?.reasons || [];
    const overview = all
      .filter((s) => s.kind === "kept")
      .map(
        (s) =>
          `<button class="rv2-mark ${s.part === ui.part ? "current" : ""}" style="left:${(s.start / plan.duration) * 100}%;width:${Math.max(0.14, ((s.end - s.start) / plan.duration) * 100)}%" title="${reviewTime(s.start)}–${reviewTime(s.end)} · Часть ${s.part + 1}" data-action="review-select-seg" data-id="${s.key}"></button>`,
      )
      .join("");
    const clips = all
      .map((s, i) => {
        const ev = (plan.events || []).find(
          (x) => x.start < s.end && x.end > s.start && x.summary,
        );
        const title =
          s.kind === "removed"
            ? "Вырезанный промежуток"
            : ev?.summary || `Сцена ${i + 1}`;
        return `<button class="rv2-clip ${s.kind === "kept" ? "kept" : "removed"} ${sel.key === s.key ? "active" : ""}" data-action="review-select-seg" data-id="${s.key}" title="${esc(title)}"><span class="rv2-clip-top"><b>${s.kind === "kept" ? `Часть ${s.part + 1} · сцена ${s.cut + 1}` : "Вырезано"}</b><i>${s.kind === "kept" ? "✓" : "✕"}</i></span><span class="rv2-clip-art ${s.kind === "kept" ? `scene-tone-${s.part % 5}` : ""}"><small>${s.kind === "kept" ? "▶ СМОТРЕТЬ" : "↪ ПРОПУСК"}</small></span><span class="rv2-clip-foot"><b>${reviewTime(s.start)}–${reviewTime(s.end)}</b><small>${reviewTime(s.end - s.start)}</small></span></button>`;
      })
      .join("");
    return `<div class="rv2-head"><div class="rv2-titleline"><button class="rv2-back" data-action="nav" data-screen="editor" title="Настройки серии">←</button><div><span class="rv2-kicker">КАДР STUDIO / СЕРИЯ ${e.number}</span><h1>Проверка монтажа</h1></div></div><div class="rv2-heading-actions"><select class="form-select rv2-run-select" id="reviewAttempt" aria-label="Выбор попытки монтажа">${jobsFor(
      e.id,
    )
      .filter((x) => x.status === "completed")
      .map(
        (x) =>
          `<option value="${esc(x.id)}" ${x.id === j.id ? "selected" : ""}>${x.review_draft ? "Черновик" : "Монтаж"} ${esc(x.id.slice(0, 8))}</option>`,
      )
      .join(
        "",
      )}</select><button class="btn sm solid" data-action="nav" data-screen="finishing">✎ Оформление</button><button class="btn sm clear" data-action="review-detail" data-id="quality">⚑ Замечания <span>${warn.length}</span></button><button class="btn sm clear" data-action="review-detail" data-id="context">✦ Для обложки</button></div></div>
 ${plan.review_draft ? `<div class="panel" role="status" style="padding:14px;margin-bottom:14px"><strong>Черновик для просмотра</strong><p>${esc(plan.review_draft.reason || "Монтаж ещё проверяется.")}</p></div>` : ""}
 <div class="rv2-layout">
  <div class="rv2-maincol">
   <section class="rv2-player panel" aria-label="Просмотр видео">
    <div class="rv2-player-top"><div class="rv2-playing-title"><span class="rv-dot purple"></span><strong>${mode === "source" ? "Исходная серия" : mode === "compare" ? "Исходник + готовый Shorts" : `Готовый Shorts · часть ${ui.part + 1}`}</strong></div><div class="rv-tabs" role="group" aria-label="Режим просмотра"><button data-action="review-mode" data-id="short" class="${mode === "short" ? "active" : ""}">Shorts</button><button data-action="review-mode" data-id="source" class="${mode === "source" ? "active" : ""}">Исходник</button><button data-action="review-mode" data-id="compare" class="${mode === "compare" ? "active" : ""}">Сравнить</button></div></div>
    ${reviewStage(j, plan, sel)}
    <div class="rv2-controls"><span class="rv2-playing-meta">${mode === "source" ? esc(sourceBy(j.source_id)?.name || "Исходное видео") : `Часть ${String(ui.part + 1).padStart(2, "0")} / ${String(plan.parts.length).padStart(2, "0")} · ${reviewTime(part.duration)}`}</span><div class="rv-transport"><button data-action="review-prev" title="Предыдущая часть">◀</button><button class="primary" id="rvPlayButton" data-action="review-toggle-play">▷ Смотреть</button><button data-action="review-next" title="Следующая часть">▶</button></div></div>
   </section>
   <section class="rv2-timeline panel" aria-label="Таймлайн исходной серии под видеоплеером">
    <div class="rv2-map-head"><div><span class="rv2-kicker">МОНТАЖНАЯ ЛЕНТА</span><h2>Сцены и вырезки <span>· ${reviewTime(plan.duration)}</span></h2></div><div class="rv2-legend"><span><i class="rv-square kept"></i> В монтаже ${reviewTime(keptTime)}</span><span><i class="rv-square deleted"></i> Убрано ${reviewTime(Math.max(0, plan.duration - keptTime))}</span></div></div>
    <div class="rv2-overview"><div class="rv2-overview-track">${overview}<span class="rv2-pointer" style="left:${Math.min(100, (sel.start / plan.duration) * 100)}%"></span></div><div class="rv2-ruler"><span>00:00</span><span>${reviewTime(plan.duration / 4)}</span><span>${reviewTime(plan.duration / 2)}</span><span>${reviewTime((plan.duration * 3) / 4)}</span><span>${reviewTime(plan.duration)}</span></div></div>
    <div class="rv2-strip" id="rvStrip" aria-label="Выбери фрагмент для просмотра">${clips}</div>
    <div class="rv2-selected"><div class="rv2-selection-label"><b>${sel.kind === "kept" ? "✓ Сохранено" : "✕ Вырезано"}</b><span>${reviewTime(sel.start)} – ${reviewTime(sel.end)} · ${reviewTime(sel.end - sel.start)}</span></div><div class="rv2-selection-actions"><label class="rv2-loop"><input type="checkbox" id="rvLimitSource" ${ui.limitSource ? "checked" : ""}> Только этот фрагмент</label><button class="btn sm solid" data-action="seek-source">▶ Смотреть отрезок</button></div></div>
   </section>
  </div>
  <aside class="rv2-rail panel" aria-label="Выбор готовых Shorts и экспорт"><div class="rv2-rail-head"><div><span class="rv2-kicker">ГОТОВЫЕ SHORTS</span><h2>${plan.parts.length} частей</h2></div><label title="Автоматически включать следующую часть"><input type="checkbox" id="rvAutoNext" ${ui.reviewAutoNext ? "checked" : ""}> Авто</label></div><div class="rv2-parts">${plan.parts.map((p, i) => `<button class="rv2-part ${i === ui.part ? "active" : ""}" data-action="choose-part" data-id="${i}"><span class="rv2-part-num">${String(i + 1).padStart(2, "0")}</span><span class="rv2-part-info"><b>Часть ${String(i + 1).padStart(2, "0")}</b><small>${reviewTime(p.duration)} · ${(p.cuts || []).length} сцен</small></span><span class="rv2-part-play">${i === ui.part ? "●" : "▶"}</span></button>`).join("")}</div><div class="rv2-rail-export"><span class="rv2-kicker">СКАЧИВАНИЕ</span><div class="rv2-export-main"><button class="btn sm solid" data-action="download-mp4">↓ MP4</button><button class="btn sm" data-action="download-srt">↓ SRT</button></div><button class="btn sm rv2-full" data-action="download-all">↓ Все части → папка</button><button class="rv2-text-btn" data-action="save-videos">▣ Сохранить в папку</button><button class="rv2-text-btn" data-action="open-output">↗ Папка результатов</button></div><div class="rv2-fileinfo">Сравнивайте исходник с готовыми Shorts и сохраняйте выбранные части.</div></aside>
 </div>`;
  }
  function showReviewDetail(kind) {
    const j = currentJob(),
      plan = db.plans[j?.id];
    if (!plan) return;
    const w = plan.quality_summary?.warnings || [],
      n = plan.quality_summary?.notes || [],
      r = plan.debug_timeline?.reasons || [],
      ctx = plan.parts?.[ui.part]?.cover_context || {};
    let body = "",
      heading = "";
    if (kind === "quality") {
      heading = "Замечания и решения монтажа";
      body = `<div class="rv2-detail-count">${w.length} замечаний · ${n.length} комментариев · ${r.length} обоснований</div>${w.map((x) => `<div class="rv2-detail-line"><b>⚠ ${esc(x.category || "Проверка")}</b><p>${esc(x.text)}</p></div>`).join("") || "<p>Предупреждений нет.</p>"}<h3>Комментарии анализа</h3>${n.map((x) => `<p>${esc(x.text)}</p>`).join("") || "<p>Нет комментариев.</p>"}<h3>Причины сохранения фрагментов</h3>${r.map((x) => `<div class="rv2-detail-line"><b>${reviewTime(x.start)}–${reviewTime(x.end)} · ${esc(x.title)}</b><p>${esc(x.detail || "")}</p></div>`).join("") || "<p>Нет подтверждённых причин.</p>"}`;
    } else {
      heading = `Для обложки · часть ${ui.part + 1}`;
      body = `<h3>${esc(ctx.title || `Часть ${ui.part + 1}`)}</h3><p>${esc(ctx.synopsis || "Контекст не предоставлен.")}</p><label class="rv2-detail-label" for="contextPrompt">Промпт для обложки</label><textarea id="contextPrompt" class="rv-prompt" readonly>${esc(ctx.prompt || "")}</textarea><button class="btn sm solid" data-action="copy-context">⧉ Скопировать промпт</button>`;
    }
    $("modalHost").innerHTML =
      `<div class="modal-overlay" data-action="close-modal-bg"><div class="dialog rv2-dialog" role="dialog" aria-modal="true" aria-label="${esc(heading)}"><div class="rv2-dialog-head"><h2>${esc(heading)}</h2><button class="btn sm clear" data-action="close-modal">✕ Закрыть</button></div><div class="rv2-dialog-body">${body}</div></div></div>`;
  }
  function reviewSeek(video, sourceTime, autoplay = true) {
    if (!video) return;
    const trySeek = () => {
      const d = Number(video.duration) || 0;
      let pos = Number(sourceTime) || 0;
      if (d > 0) {
        if (pos >= d) {
          pos = Math.max(0, Math.min(d - 0.1, pos % d));
        } else pos = Math.min(Math.max(pos, 0), Math.max(0, d - 0.1));
      }
      try {
        video.currentTime = pos;
      } catch {}
      if (autoplay) video.play().catch(() => {});
    };
    if (video.readyState >= 1) trySeek();
    else video.addEventListener("loadedmetadata", trySeek, { once: true });
  }
  function updateReviewTransport() {
    const button = $("rvPlayButton");
    if (!button) return;
    const source = $("reviewSourceVideo"),
      short = $("reviewShortVideo");
    const videos =
      ui.reviewMode === "compare"
        ? [source, short]
        : [ui.reviewMode === "source" ? source : short || source];
    const playing = videos.some(
      (video) => video && !video.paused && !video.ended,
    );
    button.textContent = playing ? "Ⅱ Пауза" : "▷ Смотреть";
    button.setAttribute(
      "aria-label",
      playing ? "Приостановить видео" : "Воспроизвести видео",
    );
  }
  function bindReview() {
    const sel = $("reviewAttempt");
    if (sel)
      sel.onchange = (e) => {
        ui.jobId = e.target.value;
        ui.part = 0;
        ui.reviewSelection = null;
        render();
      };
    const plan = db.plans[currentJob()?.id];
    if (!plan) return;
    const source = $("reviewSourceVideo"),
      short = $("reviewShortVideo"),
      current = reviewSelection(plan);
    for (const video of [source, short]) {
      if (video)
        for (const type of ["play", "pause", "ended"])
          video.addEventListener(type, updateReviewTransport);
    }
    updateReviewTransport();
    if (source) {
      source.addEventListener("timeupdate", () => {
        if (
          !ui.limitSource ||
          !Number.isFinite(source.duration) ||
          source.duration <= 0
        )
          return;
        const real = source.duration >= plan.duration * 0.75,
          limitEnd = real
            ? current.end
            : Math.min(
                source.duration - 0.05,
                (current.start % source.duration) +
                  Math.min(3, Math.max(0.5, current.end - current.start)),
              );
        if (source.currentTime >= limitEnd) source.pause();
      });
    }
    if (short) {
      short.addEventListener("ended", () => {
        if (ui.reviewAutoNext && ui.part < plan.parts.length - 1) {
          ui.part++;
          ui.reviewSelection = null;
          render();
          const v = $("reviewShortVideo");
          if (v) v.play().catch(() => {});
        }
      });
    }
    const autoplay = $("rvAutoNext");
    if (autoplay)
      autoplay.onchange = (e) => {
        ui.reviewAutoNext = e.target.checked;
      };
    const strip = $("rvStrip"),
      chosen = strip?.querySelector(".rv2-clip.active");
    if (chosen && ui.reviewScrollNeeded) {
      chosen.scrollIntoView({
        behavior: "instant",
        block: "nearest",
        inline: "center",
      });
      ui.reviewScrollNeeded = false;
    }
  }

  function renderTrash() {
    const projects = db.projects.filter((p) => p.archived_at),
      episodes = db.episodes.filter(
        (e) => e.archived_at && aliveP(projectBy(e.project_id)),
      );
    const all = [
      ...projects.map((p) => ({
        kind: "project",
        id: p.id,
        title: p.title,
        meta: `Проект · ${db.episodes.filter((e) => e.project_id === p.id).length} серий`,
        date: p.archived_at,
      })),
      ...episodes.map((e) => ({
        kind: "episode",
        id: e.id,
        title: `Серия ${e.number}`,
        meta: `${projectBy(e.project_id)?.title || ""} · Серия`,
        date: e.archived_at,
      })),
    ];
    return `${header("СИСТЕМА / БИБЛИОТЕКА", "Корзина", "Проекты и серии архивируются и могут быть восстановлены вместе с историей монтажа.", `<button class="btn clear" data-action="nav" data-screen="projects">← Проекты</button>`)}<div class="panel" style="padding:23px;margin-bottom:22px;background:linear-gradient(120deg,#191f30,#242536)"><div class="section-title"><h2>Данные сохраняются</h2><span class="badge muted">${all.length} объектов</span></div><p class="lede">Проекты и серии можно восстановить вместе с настройками и результатами монтажа.</p></div><div class="trash-list">${all.map((item) => `<article class="trash-card panel"><div class="trash-symbol">${item.kind === "project" ? "▦" : "▤"}</div><div><h3>${esc(item.title)}</h3><p>${esc(item.meta)} · Удалено ${stamp(item.date)}</p></div><button class="btn green" data-action="restore" data-kind="${item.kind}" data-id="${esc(item.id)}">↺ Восстановить</button></article>`).join("")}</div>${all.length ? "" : '<div class="empty"><strong>Корзина пуста</strong>Удалённые проекты и серии появятся здесь.</div>'}`;
  }
  async function doAction(action, el) {
    let path = "",
      j = currentJob(),
      e = currE(),
      p = currP(),
      rid = el?.dataset.id || "",
      idx = Number(rid),
      mode = el?.dataset.screen;
    try {
      switch (action) {
        case "nav":
          if (mode === "processing") ui.jobId = latest(ui.episodeId)?.id || null;
          go(mode);
          break;
        case "go-project":
          if (!aliveP(projectBy(rid))) return notify("Выберите проект");
          ui.projectId = rid;
          ui.episodeId =
            db.episodes.find((e) => aliveE(e) && e.project_id === rid)?.id ||
            null;
          ui.editing = null;
          go("episodes");
          break;
        case "open-episode": {
          const ep = epBy(rid);
          if (!aliveE(ep)) return;
          ui.projectId = ep.project_id;
          ui.episodeId = ep.id;
          ui.jobId = latest(ep.id)?.id || null;
          ui.editing = null;
          go("editor");
          break;
        }
        case "open-job": {
          const job = jobBy(rid);
          if (!job) return;
          ui.jobId = job.id;
          ui.episodeId = job.episode_id;
          ui.projectId = epBy(job.episode_id)?.project_id;
          go("processing");
          await request("GET", `/api/jobs/${rid}`);
          break;
        }
        case "open-review": {
          const ep = rid && epBy(rid) ? epBy(rid) : currE();
          if (!aliveE(ep)) return;
          ui.projectId = ep.project_id;
          ui.episodeId = ep.id;
          ui.jobId =
            jobsFor(ep.id).find((x) => x.status === "completed")?.id || "";
          go("review");
          break;
        }
        case "new-project":
          modal({
            title: "Новый проект",
            text: "Новый проект появится в вашей библиотеке.",
            label: "Название аниме",
            value: "",
            confirm: "Создать проект",
            onConfirm: async (title) => {
              const res = await request("POST", "/api/projects", { title });
              ui.projectId = res.id;
              ui.episodeId = null;
              notify("Проект создан");
              go("episodes");
            },
          });
          break;
        case "new-episode":
          modal({
            title: "Добавить серию",
            text: `Проект: ${p?.title || ""}. Номер должен быть уникальным среди активных серий.`,
            label: "Номер серии",
            value: String(
              Math.max(
                0,
                ...db.episodes
                  .filter((x) => aliveE(x) && x.project_id === p?.id)
                  .map((x) => x.number),
              ) + 1,
            ),
            kind: "number",
            confirm: "Создать серию",
            onConfirm: async (value) => {
              const ep = await request(
                "POST",
                `/api/projects/${p.id}/episodes`,
                { number: Number(value) },
              );
              ui.episodeId = ep.id;
              ui.editing = null;
              notify("Серия создана");
              go("editor");
            },
          });
          break;
        case "delete-project":
          modal({
            title: "Переместить проект в корзину?",
            text: `«${projectBy(rid)?.title || ""}» и его серии будут скрыты. Запуски и исходные файлы сохранятся.`,
            confirm: "Удалить проект",
            danger: true,
            onConfirm: async () => {
              await request("DELETE", `/api/projects/${rid}`);
              notify("Проект перемещён в корзину");
              go("projects");
            },
          });
          break;
        case "delete-episode": {
          const target = epBy(rid);
          modal({
            title: "Удалить серию?",
            text: `Серия ${target?.number} будет архивирована, результаты останутся на месте.`,
            confirm: "Удалить серию",
            danger: true,
            onConfirm: async () => {
              await request("DELETE", `/api/episodes/${rid}`);
              notify("Серия в корзине");
              if (ui.screen === "editor") go("episodes");
              else render();
            },
          });
          break;
        }
        case "restore": {
          const kind = el.dataset.kind;
          const res = await request(
            "POST",
            `/api/${kind === "project" ? "projects" : "episodes"}/${rid}/restore`,
          );
          notify("Восстановлено · " + res.id.slice(0, 8));
          render();
          break;
        }
        case "filter":
          ui.filter = rid;
          render();
          break;
        case "upload-video":
          $("uploadFile").click();
          break;
        case "refresh-sources":
          await request("GET", "/api/sources");
          notify(`Доступно ${db.sources.length} исходников`);
          render();
          break;
        case "save-settings": {
          const d = currentEdit();
          if (!d.source_id) throw new Error("Выберите исходное видео");
          const settings = await request(
            "PUT",
            `/api/episodes/${e.id}/settings`,
            {
              source_id: d.source_id,
              layout: d.layout,
              caption_style: d.caption_style,
              analysis_provider: d.analysis_provider,
            },
          );
          await saveEditorAppearance(d);
          await request("PUT", "/api/music", musicBody());
          ui.draftMusic = structuredClone(db.music);
          $("editStatus").textContent = "✓ Изменения сохранены";
          notify("Настройки сохранены: серия + музыка");
          break;
        }
        case "launch": {
          const d = currentEdit();
          if (!d.source_id) throw new Error("Нужно выбрать видео");
          await request("PUT", `/api/episodes/${e.id}/settings`, {
            source_id: d.source_id,
            layout: d.layout,
            caption_style: d.caption_style,
            analysis_provider: d.analysis_provider,
          });
          await saveEditorAppearance(d);
          await request("PUT", "/api/music", musicBody());
          const j = await request("POST", `/api/episodes/${e.id}/jobs`);
          ui.jobId = j.id;
          notify("Монтаж запущен");
          go("processing");
          break;
        }
        case "check-deepseek": {
          const res = await request("POST", "/api/deepseek/check");
          notify(
            res.available
              ? `Подключение установлено · ${res.model}`
              : "DeepSeek не подключён",
          );
          break;
        }
        case "music-folder": {
          const res = await request("POST", "/api/music/open");
          notify(
            res.opened ? "Папка музыки открыта" : "Не удалось открыть папку",
          );
          break;
        }
        case "copy-music-path": {
          const settings = await request("GET", "/api/music");
          if (!settings.folder)
            throw new Error("Сервер не сообщил путь к папке музыки");
          copyText(settings.folder);
          notify("Путь скопирован: " + settings.folder);
          break;
        }
        case "refresh-music":
          await request("GET", "/api/music");
          notify(`Музыка: ${db.music.tracks.length} файлов`);
          render();
          break;
        case "cancel-job":
          await request("POST", `/api/jobs/${rid}/cancel`);
          notify("Монтаж отменён");
          render();
          break;
        case "manual-prepare": {
          if (jobBy(rid)?.analysis_provider !== "antigravity_manual")
            await request("POST", `/api/jobs/${rid}/analysis-provider`, {
              provider: "antigravity_manual",
            });
          await request("POST", `/api/jobs/${rid}/antigravity/prepare`);
          notify("Подготовка пакета запущена; сохранённые этапы используются");
          go("processing");
          break;
        }
        case "manual-open":
          await request("POST", `/api/jobs/${rid}/antigravity/open`);
          notify("Папка анализа открыта");
          break;
        case "manual-auto": {
          const enabled = !db.manualAnalysis?.[rid]?.automation?.enabled;
          await request(
            "POST",
            `/api/jobs/${rid}/antigravity/automation?enabled=${enabled}`,
          );
          await updateManualView();
          notify(
            enabled
              ? "Автоимпорт включён. Запустите анализ и отдельный сценарий один раз"
              : "Вернулись к ручному импорту",
          );
          break;
        }
        case "manual-return":
          await request("POST", `/api/jobs/${rid}/analysis-provider`, {
            provider: "local",
          });
          notify("Qwen выбран для этого задания. Нажмите продолжение");
          render();
          break;
        case "manual-import": {
          const input = $("manualResultFile"),
            packet = el.dataset.packet;
          input.value = "";
          input.onchange = async () => {
            const file = input.files[0];
            if (!file) return;
            if (file.size > 8 * 1024 * 1024) {
              notify("Результат больше 8 МБ", true);
              return;
            }
            try {
              await request(
                "POST",
                `/api/jobs/${rid}/antigravity/${packet}/import`,
                { rawJsonFile: file },
              );
              await updateManualView();
              notify(
                "Результат принят. Продолжите обработку",
              );
            } catch (error) {
              notify(error.message, true);
            }
          };
          input.click();
          break;
        }
        case "retry-job":
          await request("POST", `/api/jobs/${rid}/retry`);
          notify("Обработка продолжена");
          go("processing");
          break;
        case "read-job":
          await request("GET", `/api/jobs/${rid}`);
          notify("Статус обновлён");
          render();
          break;
        case "delete-job":
          modal({
            title: "Удалить запись монтажа?",
            text: "Удаляется запись и история этого задания. Серия остаётся.",
            confirm: "Удалить запись",
            danger: true,
            onConfirm: async () => {
              await request("DELETE", `/api/jobs/${rid}`);
              ui.jobId = latest(ui.episodeId)?.id || null;
              go("editor");
              notify("Запись удалена");
            },
          });
          break;
        case "choose-part": {
          const pl = db.plans[j?.id];
          ui.part = Math.max(0, Math.min((pl?.parts?.length || 1) - 1, idx));
          ui.reviewSelection = null;
          ui.reviewMode = "short";
          ui.reviewScrollNeeded = true;
          render();
          $("reviewShortVideo")
            ?.play()
            .catch(() => {});
          break;
        }
        case "review-mode": {
          ui.reviewMode = rid;
          render();
          break;
        }
        case "review-detail": {
          await request("GET", `/api/jobs/${j.id}/plan`);
          showReviewDetail(rid);
          break;
        }
        case "review-select-seg": {
          const pl = db.plans[j?.id],
            segment = reviewSegments(pl).find((s) => s.key === rid);
          if (!segment) break;
          ui.reviewSelection = segment.key;
          if (segment.kind === "kept") ui.part = segment.part;
          ui.reviewMode = segment.kind === "removed" ? "source" : "compare";
          ui.reviewScrollNeeded = true;
          render();
          reviewSeek($("reviewSourceVideo"), segment.start, true);
          break;
        }
        case "review-prev": {
          const pl = db.plans[j?.id];
          ui.part = Math.max(0, ui.part - 1);
          ui.reviewSelection = null;
          ui.reviewMode = "short";
          ui.reviewScrollNeeded = true;
          render();
          break;
        }
        case "review-next": {
          const pl = db.plans[j?.id];
          ui.part = Math.min(pl.parts.length - 1, ui.part + 1);
          ui.reviewSelection = null;
          ui.reviewMode = "short";
          ui.reviewScrollNeeded = true;
          render();
          break;
        }
        case "review-toggle-play": {
          const source = $("reviewSourceVideo"),
            short = $("reviewShortVideo");
          const video = ui.reviewMode === "source" ? source : short || source;
          if (!video) {
            notify("Видео недоступно");
            break;
          }
          const playing =
            ui.reviewMode === "compare"
              ? [source, short].some((v) => v && !v.paused && !v.ended)
              : !video.paused && !video.ended;
          if (!playing) {
            await video
              .play()
              .catch(() => notify("Браузер не разрешил воспроизведение", true));
            if (
              ui.reviewMode === "compare" &&
              source &&
              short &&
              source !== video
            ) {
              source.play().catch(() => {});
            }
          } else {
            video.pause();
            if (ui.reviewMode === "compare" && source) source.pause();
          }
          updateReviewTransport();
          break;
        }
        case "seek-source": {
          const pl = db.plans[j?.id],
            segment = reviewSelection(pl);
          ui.reviewMode = ui.reviewMode === "compare" ? "compare" : "source";
          render();
          reviewSeek($("reviewSourceVideo"), segment.start, true);
          break;
        }
        case "copy-context":
          copyText($("contextPrompt")?.value || "");
          notify("Контекстный промпт скопирован");
          break;
        case "download-mp4": {
          const file = j.files?.[ui.part];
          if (!file) throw new Error("MP4 не найден");
          window.open(file.url + "?download=1", "_blank", "noopener");
          break;
        }
        case "download-srt": {
          const file = j.files?.[ui.part];
          if (!file?.subtitle_url) throw new Error("SRT не найден");
          window.open(file.subtitle_url + "?download=1", "_blank", "noopener");
          break;
        }
        case "download-all": {
          const res = await request("POST", `/api/jobs/${j.id}/save-videos`, {
            all: true,
          });
          notify(
            res.cancelled
              ? "Сохранение отменено"
              : "Видео сохранены на диск: " + (res.path || res.count || ""),
          );
          break;
        }
        case "save-videos": {
          const res = await request("POST", `/api/jobs/${j.id}/save-videos`, {
            all: true,
          });
          notify(
            res.cancelled
              ? "Сохранение отменено"
              : "Сохранено файлов: " + (res.count || 0),
          );
          break;
        }
        case "open-output": {
          const res = await request("POST", `/api/jobs/${j.id}/open-folder`);
          notify("Папка с готовыми Shorts открыта: " + (res.path || ""));
          break;
        }
        case "reset":
          await window.KadrBridge.refresh(db, ui);
          go("projects");
          notify("Проекты обновлены");
          break;
        case "close-modal":
          $("modalHost").innerHTML = "";
          break;
        case "close-modal-bg":
          break;
      }
    } catch (error) {
      notify(error.message || "Не удалось выполнить действие", true);
    }
  }
  function musicBody() {
    const m = ui.draftMusic;
    return {
      enabled: !!m.enabled,
      volume: Number(m.volume),
      mode: m.mode,
      track: m.track || null,
      part_tracks: m.part_tracks || {},
    };
  }
  $("uploadFile").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const res = await request("POST", "/api/import", { file });
      ui.editing = currentEdit();
      ui.editing.source_id = res.id;
      if (ui.localFileUrl) URL.revokeObjectURL(ui.localFileUrl);
      ui.localFileUrl = URL.createObjectURL(file);
      ui.localMedia[res.id] = ui.localFileUrl;
      ui.localFileName = file.name;
      render();
      notify(
        `Видео ${file.name} добавлено. В браузере доступен локальный предпросмотр.`,
      );
    } catch (e) {
      notify(e.message, true);
    }
    event.target.value = "";
  });
  document.addEventListener("click", (ev) => {
    if (ev.target.classList.contains("modal-overlay")) {
      $("modalHost").innerHTML = "";
      return;
    }
    const el = ev.target.closest("[data-action]");
    if (!el) return;
    if (el.tagName === "BUTTON" || el.tagName === "A") ev.preventDefault();
    doAction(el.dataset.action, el);
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") $("modalHost").innerHTML = "";
    if (ev.key === "Enter" && ev.target.matches(".project-card")) {
      ev.preventDefault();
      doAction("go-project", ev.target);
    }
  });
  document.addEventListener("input", (ev) => {
    if (ev.target.id === "projectSearch") {
      ui.search = ev.target.value;
      const scroll = window.scrollY;
      const root = $("projectCards");
      if (!root) return;
      const active = db.projects
        .filter(aliveP)
        .filter((p) => p.title.toLowerCase().includes(ui.search.toLowerCase()));
      root.querySelectorAll(".project-card").forEach((card) => {
        const id = card.dataset.id;
        card.style.display = active.some((p) => p.id === id) ? "" : "none";
      });
    }
  });
  /* Finishing: edit real completed job plans through the server API. */
  const finishingDefaults = () => ({
    version: 1,
    video: {
      layout: "cinema",
      frame_style: "plain",
      card_variant: "compact",
      channel_handle: "",
      channel_name: "",
      post_caption: "",
      zoom: 100,
      blur: 24,
      brightness: 100,
      vignette: 15,
    },
    subtitles: {
      enabled: true,
      text: "",
      x: 50,
      y: 74,
      font_size: 32,
      color: "#f6d779",
      outline: 3,
      background: false,
      align: "center",
      uppercase: true,
      safe_guides: true,
    },
    audio: {
      enabled: true,
      volume: 0.15,
      track: null,
      mode: "random_per_part",
      fade_in: 0.8,
      fade_out: 1.3,
      ducking: false,
      part_tracks: {},
    },
    part_overrides: {},
  });
  function getFinishing(id = ui.episodeId) {
    db.finishing ||= {};
    if (!db.finishing[id]) db.finishing[id] = finishingDefaults();
    return db.finishing[id];
  }
  async function saveEditorAppearance(d) {
    const { episode_id, ...profile } = structuredClone(getFinishing());
    profile.video = { ...profile.video, layout: d.layout, frame_style: d.frame_style, card_variant: d.card_variant, channel_handle: d.channel_handle,
      channel_name: d.channel_name, post_caption: d.post_caption };
    await request("PUT", `/api/episodes/${ui.episodeId}/finishing`, profile);
  }
  function selectedCues(partIndex = ui.finishPart ?? 0) {
    const job = currentJob(),
      part = db.plans[job?.id]?.parts?.[partIndex];
    db.captionOverrides ||= {};
    const key = job?.id + ":" + (part?.index ?? partIndex + 1);
    if (!db.captionOverrides[key])
      db.captionOverrides[key] = {
        job_id: job?.id,
        part_index: part?.index ?? partIndex + 1,
        revision: 0,
        cues: structuredClone(part?.subtitles || []),
      };
    return db.captionOverrides[key].cues;
  }
  function selectedSubtitle() {
    const f = getFinishing(),
      job = currentJob(),
      part = db.plans[job?.id]?.parts?.[ui.finishPart ?? 0],
      key = String(part?.index ?? (ui.finishPart ?? 0) + 1);
    f.part_overrides[key] ||= {};
    f.part_overrides[key].style ||= structuredClone(f.subtitles);
    return f.part_overrides[key].style;
  }
  function chosenCue(partIndex = ui.finishPart ?? 0) {
    const cues = selectedCues(partIndex);
    ui.finishCue = Math.max(0, Math.min(cues.length - 1, ui.finishCue ?? 0));
    return cues[ui.finishCue] || null;
  }
  function finishingPart() {
    return db.plans[currentJob()?.id]?.parts?.[ui.finishPart ?? 0];
  }
  function finishingPreviewSource() {
    const job = currentJob();
    const raw = getFinishing().video.frame_style === "social" ||
      db.plans[job?.id]?.render_video?.frame_style === "social";
    return { raw, url: raw ? reviewGetSource(job) : reviewGetShort(job, ui.finishPart ?? 0) };
  }
  function finishingClock(video) {
    if (video?.dataset.sourcePreview !== "true")
      return { time: Number(video?.currentTime) || 0, duration: Number(video?.duration) || 0 };
    const cuts = finishingPart()?.cuts || [];
    const index = Math.min(cuts.length - 1, Number(video.dataset.previewCut) || 0);
    const cut = cuts[index];
    const offset = cuts.slice(0, index).reduce((sum, item) => sum + item.end - item.start, 0);
    return { time: offset + (cut ? Math.max(0, Math.min(cut.end - cut.start, video.currentTime - cut.start)) : 0),
      duration: Number(finishingPart()?.duration) || 0 };
  }
  function seekFinishing(video, outputTime) {
    if (video.dataset.sourcePreview !== "true") {
      video.currentTime = outputTime;
      return;
    }
    const cuts = finishingPart()?.cuts || [];
    let offset = 0;
    for (let index = 0; index < cuts.length; index++) {
      const cut = cuts[index], length = cut.end - cut.start;
      if (outputTime < offset + length || index === cuts.length - 1) {
        video.dataset.previewCut = String(index);
        video.currentTime = cut.start + Math.max(0, Math.min(length - .001, outputTime - offset));
        return;
      }
      offset += length;
    }
  }
  function audioName(f) {
    const job = currentJob(),
      part = db.plans[job?.id]?.parts?.[ui.finishPart ?? 0],
      index = part?.index ?? (ui.finishPart ?? 0) + 1;
    const pick =
      f.audio.mode === "per_part" ? f.audio.part_tracks?.[String(index)] : null;
    if (["none", "__none__", "off", "без музыки"].includes(pick)) return "";
    return pick || f.audio.track || db.music.tracks?.[0] || "";
  }
  function finishCueBody(partIndex) {
    const j = currentJob(),
      part = db.plans[j?.id]?.parts?.[partIndex],
      index = part?.index ?? partIndex + 1,
      record = db.captionOverrides?.[j?.id + ":" + index];
    return {
      part_index: index,
      revision: record?.revision ?? 0,
      cues: structuredClone(selectedCues(partIndex)),
    };
  }
  function finishCueChanged(partIndex = ui.finishPart ?? 0) {
    const job = currentJob(),
      part = db.plans[job?.id]?.parts?.[partIndex];
    if (!job || !part) return;
    db.finishDirtyCues ||= {};
    db.finishDirtyCues[job.id + ":" + part.index] = true;
  }
  function finishPendingCaptions(job) {
    const dirty = db.finishDirtyCues || {};
    return (db.plans[job.id]?.parts || []).flatMap((part, i) =>
      dirty[job.id + ":" + part.index] ? [finishCueBody(i)] : [],
    );
  }
  async function persistSelectedCaptions(job, partIndex) {
    const part = db.plans[job.id]?.parts?.[partIndex];
    if (!part) throw new Error("Монтажная часть не найдена");
    await request(
      "PUT",
      `/api/jobs/${job.id}/parts/${part.index}/captions`,
      finishCueBody(partIndex),
    );
  }
  function escAttr(s) {
    return esc(String(s ?? ""));
  }
  function renderFinishing() {
    const e = currE();
    if (!e) return '<div class="empty">Выберите серию для настройки.</div>';
    const j = currentJob();
    if (!j || j.status !== "completed" || !db.plans[j.id]?.parts?.length) {
      return '<div class="empty"><strong>Для этой серии ещё нет готового монтажа</strong>Редактор оформления станет доступен после завершения Shorts. Выберите другую серию или запустите монтаж.</div>';
    }
    const f = getFinishing(),
      plan = db.plans[j.id],
      cnt = plan.parts.length;
    ui.finishPart = Math.max(
      0,
      Math.min(cnt - 1, ui.finishPart ?? ui.part ?? 0),
    );
    const s = selectedSubtitle(),
      a = f.audio,
      v = f.video,
      cue = chosenCue();
    const tab = ui.finishTab || "captions";
    const tone = ["#f6d779", "#ffffff", "#ace7d2", "#ffc7c7", "#d4c4ff"];
    const palette = tone
      .map(
        (c) =>
          `<button type="button" title="Цвет ${c}" class="fc-swatch ${s.color === c ? "active" : ""}" style="--swatch:${c}" data-fcolor="${c}"></button>`,
      )
      .join("");
    const r = (title, id, value, min, max, unit = "%") =>
      `<label class="fc-control"><span><b>${title}</b><output id="${id}Label">${value}${unit}</output></span><input type="range" id="${id}" min="${min}" max="${max}" value="${value}"></label>`;
    const label = (title, sub = "") =>
      `<div class="fc-group-heading"><strong>${title}</strong>${sub ? `<small>${sub}</small>` : ""}</div>`;
    const tabs = `<nav class="fc-switch" aria-label="Настройки финального оформления"><button type="button" class="${tab === "captions" ? "active" : ""}" data-ftab="captions">Субтитры</button><button type="button" class="${tab === "audio" ? "active" : ""}" data-ftab="audio">Звук</button><button type="button" class="${tab === "frame" ? "active" : ""}" data-ftab="frame">Кадр</button></nav>`;
    const controls =
      tab === "captions"
        ? `${label("Слова в кадре", "Изменения сразу видны в предпросмотре")}
 <p class="fc-inline-tip">Чтобы увидеть новые субтитры без наложения старых, создайте предпросмотр.</p>
 <div class="fc-cue-list">${selectedCues()
   .map(
     (c, i) =>
       `<button type="button" data-fcue="${i}" class="${i === (ui.finishCue || 0) ? "active" : ""}"><span>${reviewTime(c.start)}–${reviewTime(c.end)}</span><b>${esc(c.text.slice(0, 30)) || "Без текста"}</b></button>`,
   )
   .join("")}</div>
 <div class="fc-cue-actions"><button type="button" id="fcAddCue">＋ Реплика</button><button type="button" id="fcDeleteCue" ${selectedCues().length <= 1 ? "disabled" : ""}>Удалить</button></div>
 <div class="fc-cue-times"><label>Начало, с <input type="number" id="fcCueStart" min="0" step="0.1" value="${cue?.start ?? ""}" ${cue ? "" : "disabled"}></label><label>Конец, с <input type="number" id="fcCueEnd" min="0.1" step="0.1" value="${cue?.end ?? ""}" ${cue ? "" : "disabled"}></label></div>
 <label class="fc-field"><span>Текст реплики</span><textarea rows="3" id="fcCaptionText" maxlength="180" ${cue ? "" : "disabled"} placeholder="${cue ? "Напишите субтитры" : "В этой части нет реплик. Можно добавить свою."}">${escAttr(cue?.text)}</textarea></label>
 <div class="fc-preset-strip"><button type="button" data-fpreset="accent" class="${s.color === "#f6d779" ? "active" : ""}">Яркие</button><button type="button" data-fpreset="classic" class="${s.color === "#ffffff" ? "active" : ""}">Классика</button><button type="button" data-fpreset="soft">Минимализм</button></div>
 <div class="fc-colors">${palette}<label title="Свой цвет"><input type="color" id="fcCustomColor" value="${s.color}"></label></div>
 ${r("Размер", "fcSize", s.font_size, 18, 54, " px")}${r("По горизонтали", "fcX", s.x, 5, 95)}${r("По вертикали", "fcY", s.y, 8, 92)}${r("Обводка", "fcOutline", s.outline, 0, 6, " px")}
 <label class="fc-toggle"><input type="checkbox" id="fcCaptionEnabled" ${s.enabled ? "checked" : ""}><span>Показывать субтитры</span></label>
 <div class="fc-double"><label><input type="checkbox" id="fcUppercase" ${s.uppercase ? "checked" : ""}> Верхний регистр</label><label><input type="checkbox" id="fcCaptionBg" ${s.background ? "checked" : ""}> Подложка</label></div>
 <p class="fc-inline-tip">Перетаскивайте субтитры мышью прямо на видео. Двойной клик возвращает их в безопасную область.</p>`
        : tab === "audio"
          ? `${label("Звуковое сопровождение", "Оригинальная речь остаётся слышимой")}
 <label class="fc-toggle"><input type="checkbox" id="fcMusicEnabled" ${a.enabled ? "checked" : ""}><span>Добавлять музыку</span></label>
 <label class="fc-field"><span>Подстановка музыки</span><select id="fcMusicMode"><option value="single" ${a.mode === "single" ? "selected" : ""}>Один трек на всю серию</option><option value="random_per_part" ${a.mode === "random_per_part" ? "selected" : ""}>Случайный трек для каждой части</option><option value="per_part" ${a.mode === "per_part" ? "selected" : ""}>Выбор отдельно для каждой части</option></select></label>
 <label class="fc-field"><span>${a.mode === "per_part" ? "Музыка для текущей части" : "Трек из медиатеки"}</span><select id="fcTrack"><option value="">Выберите трек</option>${a.mode === "per_part" ? `<option value="none" ${a.part_tracks?.[String(plan?.parts?.[ui.finishPart]?.index ?? ui.finishPart + 1)] === "none" ? "selected" : ""}>Без музыки для этой части</option>` : ""}${(db.music.tracks || []).map((t) => `<option value="${escAttr(t)}" ${audioName(f) === t ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>
 <div class="fc-inline-controls"><button class="fc-secondary" id="fcImportAudio">＋ Загрузить свой аудиофайл</button><button class="fc-secondary" id="fcHearAudio">♫ Прослушать</button></div>
 <div class="fc-audio-source" id="fcAudioSource">${ui.finishAudioURL ? "Локальный аудиофайл загружен" : "Музыка из вашей библиотеки"}</div>
 ${r("Громкость фона", "fcVolume", Math.round(a.volume * 100), 0, 100)}
 ${r("Плавное начало", "fcFadeIn", Math.round(a.fade_in * 10) / 10, 0, 5, " с")}${r("Плавное окончание", "fcFadeOut", Math.round(a.fade_out * 10) / 10, 0, 5, " с")}
 <label class="fc-toggle"><input type="checkbox" id="fcDucking" ${a.ducking ? "checked" : ""}><span>Приглушать музыку во время реплик</span></label>
 <p class="fc-inline-tip">Прослушайте музыку вместе с видео. Сохраните результат через экспорт.</p>`
          : `${label("Композиция кадра", "Изменения не затрагивают исходное видео")}
 <div class="fc-layout-modes"><button type="button" data-flayout="cinema" class="${v.layout === "cinema" && v.frame_style !== "social" ? "active" : ""}"><span class="fc-layout-icon cine"></span><b>Полный кадр</b><small>На мягком фоне</small></button><button type="button" data-flayout="portrait" class="${v.layout === "portrait" && v.frame_style !== "social" ? "active" : ""}"><span class="fc-layout-icon crop"></span><b>Крупный план</b><small>С заполнением 9:16</small></button><button type="button" data-flayout="social" class="${v.frame_style === "social" ? "active" : ""}"><span class="fc-layout-icon social"></span><b>Карточка публикации</b><small>Канал и подпись</small></button></div>
 ${v.frame_style === "social" ? `<label class="fc-field"><span>Стиль карточки</span><select id="fcCardVariant"><option value="compact" ${v.card_variant !== "post" ? "selected" : ""}>Компактная карточка</option><option value="post" ${v.card_variant === "post" ? "selected" : ""}>Пост · крупная подпись</option></select></label><label class="fc-field"><span>Название канала</span><input id="fcChannel" maxlength="60" value="${escAttr(v.channel_name)}" placeholder="Название вашего канала"></label>${v.card_variant === "post" ? `<label class="fc-field"><span>Адрес канала</span><input id="fcHandle" maxlength="60" value="${escAttr(v.channel_handle)}" placeholder="@ваш_канал"></label>` : ""}<label class="fc-field"><span>Подпись к видео</span><textarea id="fcPostCaption" maxlength="180" rows="3" placeholder="Ваша подпись">${escAttr(v.post_caption)}</textarea></label><p class="fc-inline-tip">Весь исходный кадр остаётся виден. Серверный предпросмотр показывает итоговый MP4 с рамкой.</p>` : ""}
 ${v.frame_style === "social" ? "" : r("Масштаб", "fcZoom", v.zoom, 90, 160)}${r("Размытие фона", "fcBlur", v.blur, 0, 45, " px")}${r("Яркость", "fcBrightness", v.brightness, 60, 140)}${r("Виньетка", "fcVignette", v.vignette, 0, 60)}
 <label class="fc-toggle"><input type="checkbox" id="fcGuides" ${s.safe_guides ? "checked" : ""}><span>Безопасные зоны Shorts</span></label>
 `;
    const counts = plan.parts
      .map(
        (p, i) =>
          `<button type="button" class="fc-part ${i === ui.finishPart ? "selected" : ""}" data-fpart="${i}"><span class="fc-part-number">${String(i + 1).padStart(2, "0")}</span><span><b>Часть ${String(i + 1).padStart(2, "0")}</b><small>${Number.isFinite(p.duration) ? reviewTime(p.duration) : "Длительность неизвестна"} · ${i === ui.finishPart ? "редактируется" : "готова к выбору"}</small></span><span class="fc-part-arrow">→</span></button>`,
      )
      .join("");
    const audioLine =
      a.enabled && audioName(f)
        ? `♫ ${esc(audioName(f))} · ${Math.round(a.volume * 100)}%`
        : "Музыка выключена";
    const previewSource = finishingPreviewSource(), src = previewSource.url;
    return `<div class="fc-screen"><div class="fc-header"><div><div class="fc-overline">ОФОРМЛЕНИЕ / СЕРИЯ ${e.number}</div><h1>Финальный штрих<span class="fc-period">.</span></h1><p>Настройте кадр, субтитры и музыку, затем сохраните готовое видео.</p></div><div class="fc-header-actions"><button class="fc-secondary" id="fcReset">↶ Сбросить оформление</button><button class="fc-accent" id="fcSave">Сохранить правки <span>↗</span></button></div></div>
 <div class="fc-workspace"><section class="fc-controls"><div class="fc-controls-top"><span>ИНСТРУМЕНТЫ</span></div>${tabs}<div class="fc-controls-content">${controls}</div></section>
 <section class="fc-stage"><div class="fc-stage-toolbar"><span><i class="fc-live"></i> Предпросмотр</span><div><button id="fcGuideToggle" class="fc-minibtn ${s.safe_guides ? "active" : ""}" title="Показать границы безопасной области">⌗ Сетка</button><button id="fcPreviewReset" class="fc-minibtn" title="Вернуть предпросмотр">⤾</button></div></div><div class="fc-stage-inside"><div class="fc-canvas" id="fcCanvas" tabindex="0" aria-label="Предпросмотр 9 на 16. Перетаскивайте надпись, чтобы изменить позицию.">
 <video id="fcBackdrop" class="fc-backdrop" src="${src}" muted loop playsinline preload="metadata" aria-hidden="true"></video><video id="fcVideo" src="${src}" data-source-preview="${previewSource.raw}" data-preview-cut="0" loop playsinline preload="metadata"></video>
 <div class="fc-social-card" id="fcSocialCard"><div class="fc-social-header"><span id="fcSocialInitial"></span><div class="fc-social-identity"><b id="fcSocialChannel"></b><small id="fcSocialHandle"></small></div><i>•••</i></div><div class="fc-social-caption" id="fcSocialCaption"></div></div><div class="fc-frame-shade"></div><div class="fc-frame-number">KADR <span>STUDIO</span> <b> / ${String(ui.finishPart + 1).padStart(2, "0")}</b></div>
 <div class="fc-safe-zone ${s.safe_guides ? "shown" : ""}" id="fcSafeZone"></div>
 <div class="fc-caption" id="fcCaption" role="slider" tabindex="0" aria-label="Положение субтитров; стрелками переместить" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${s.y}">${escAttr(cue?.text)}</div>
 <div class="fc-waterline"></div></div></div>
 <div class="fc-playbar"><button id="fcPlay" class="fc-play" title="Воспроизвести или остановить">▶</button><span id="fcTime">0:00</span><input id="fcSeek" aria-label="Позиция в видео" type="range" min="0" max="100" value="0"><span id="fcDuration">—</span><button id="fcMute" class="fc-minibtn" title="Включить или выключить звук исходника">♬</button></div><div class="fc-stage-foot"><span>1080 × 1920 <b>·</b> 9:16 Shorts</span><span id="fcSoundTag">${audioLine}</span></div></section>
 <aside class="fc-queue"><div class="fc-queue-title"><span>МОНТАЖНЫЙ НАБОР</span><strong>${String(cnt).padStart(2, "0")} шортсов</strong></div><div class="fc-parts">${counts}</div><div class="fc-queue-divider"></div><div class="fc-tips"><span class="fc-tips-kicker">БЫСТРЫЕ ДЕЙСТВИЯ</span><button class="fc-menu-button" id="fcCopyStyle"><span>⧉</span> Применить стиль ко всем частям <b>→</b></button><button class="fc-menu-button" id="fcPreviewRequest"><span>▣</span> Создать предпросмотр <b>→</b></button></div><div class="fc-queue-bottom"><p>Экспорт создаст новое видео с выбранным оформлением.</p><button class="fc-export" id="fcExport">Экспортировать видео <span>↗</span></button></div></aside></div>
 <input hidden type="file" id="fcMusicFile" accept="audio/*,.mp3,.wav,.m4a,.ogg"><audio id="fcAudio" preload="metadata" loop></audio>
 </div>`;
  }
  function stopAudioPreview() {
    const audio = $("fcAudio");
    if (audio) audio.pause();
  }
  function syncFinishingCaption() {
    const cap = $("fcCaption"),
      video = $("fcVideo");
    if (!cap) return;
    if (video?.dataset.renderedPreview === "true") {
      cap.textContent = "";
      cap.style.visibility = "hidden";
      return;
    }
    const s = selectedSubtitle(),
      time = finishingClock(video).time;
    const cues = selectedCues();
    const playing = Boolean(video && !video.paused && !video.ended);
    const timedCue = cues.find((item) => item.start <= time && time < item.end);
    const cue = playing ? timedCue : cues[ui.finishCue ?? 0] || timedCue;
    cap.textContent = cue
      ? s.uppercase
        ? cue.text.toLocaleUpperCase("ru-RU")
        : cue.text
      : "";
    cap.style.visibility = cue && s.enabled !== false ? "visible" : "hidden";
  }
  function finishUpdateView() {
    const f = getFinishing(),
      s = selectedSubtitle(),
      v = f.video,
      cap = $("fcCaption"),
      canvas = $("fcCanvas"),
      vid = $("fcVideo");
    if (!cap || !canvas) return;
    syncFinishingCaption();
    cap.style.left = s.x + "%";
    cap.style.top = s.y + "%";
    cap.style.color = s.color;
    cap.style.fontSize = (s.font_size * 0.227).toFixed(3) + "cqw";
    cap.style.background = s.background ? "#0b0e11bd" : "transparent";
    cap.style.padding = s.background ? ".22em .42em" : "0";
    cap.style.textAlign = s.align;
    cap.style.textShadow = s.outline
      ? `${Array.from({ length: s.outline * 2 }, (_, i) => {
          const v1 = (i % 2 ? 1 : -1) * Math.ceil(i / 2);
          return `${v1}px ${Math.floor(i / 2) % 2 ? 2 : -2}px 0 #050609`;
        }).join(",")}, 0 3px 10px #000`
      : "0 2px 10px #000a";
    canvas.classList.toggle("zoom-mode", v.layout === "portrait");
    const bakedPreview = vid?.dataset.renderedPreview === "true";
    canvas.classList.toggle("social-mode", v.frame_style === "social" && !bakedPreview);
    canvas.classList.toggle("rendered-preview", bakedPreview);
    const source = db.plans[currentJob()?.id]?.source || {};
    const ratio = source.width > 0 && source.height > 0 ? source.width / source.height : 16 / 9;
    const padding = v.card_variant === "post" ? 420 : 300, videoTop = padding - 20;
    canvas.classList.toggle("post-card", v.card_variant === "post");
    const height = Math.min(800, 900 / ratio);
    const width = Math.min(900, height * ratio);
    canvas.style.setProperty("--social-top", ((1920 - height - padding) / 2 / 1920 * 100) + "%");
    canvas.style.setProperty("--social-height", ((height + padding) / 1920 * 100) + "%");
    canvas.style.setProperty("--social-video-top", (((1920 - height - padding) / 2 + videoTop) / 1920 * 100) + "%");
    canvas.style.setProperty("--social-video-height", (height / 1920 * 100) + "%");
    canvas.style.setProperty("--social-video-width", (width / 1080 * 100) + "%");
    if ($("fcSocialHandle")) $("fcSocialHandle").textContent = v.channel_handle ? "@" + v.channel_handle.replace(/^@+/, "") : "";
    if ($("fcSocialChannel")) $("fcSocialChannel").textContent = v.channel_name || "";
    if ($("fcSocialCaption")) $("fcSocialCaption").textContent = v.post_caption || "";
    if ($("fcSocialInitial")) $("fcSocialInitial").textContent = (v.channel_name || "").slice(0, 1).toLocaleUpperCase("ru-RU");
    fitPublicationText($("fcSocialChannel"), 44, 12);
    fitPublicationText($("fcSocialCaption"), v.card_variant === "post" ? 48 : 34);
    canvas.style.setProperty("--fc-blur", v.blur + "px");
    canvas.style.setProperty("--fc-vignette", v.vignette / 100);
    if (vid) {
      const baked = vid.dataset.renderedPreview === "true";
      vid.style.transform = baked || v.frame_style === "social" ? "none" : `scale(${v.zoom / 100})`;
      vid.style.filter = baked ? "none" : `brightness(${v.brightness}%)`;
    }
    const safe = $("fcSafeZone");
    if (safe) safe.classList.toggle("shown", s.safe_guides);
    const status = $("fcSoundTag");
    if (status)
      status.textContent =
        f.audio.enabled && audioName(f)
          ? `♫ ${audioName(f)} · ${Math.round(f.audio.volume * 100)}%`
          : "Музыка выключена";
  }
  function finishSaveCue(text) {
    const list = selectedCues();
    if (!chosenCue()) return;
    list[ui.finishCue ?? 0] = { ...chosenCue(), text };
    finishUpdateView();
  }

  async function waitForFinishingJob(path, onProgress) {
    for (let i = 0; i < 180; i++) {
      const state = await request("GET", path, null, { quiet: true });
      if (onProgress) onProgress(state);
      if (["completed", "failed", "cancelled"].includes(state.status))
        return state;
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
    throw new Error(
      "Экспорт выполняется слишком долго. Запомните адрес: " + path,
    );
  }
  function showFinishingFiles(files) {
    const valid = (files || []).filter((f) => f.url && f.name);
    modal({
      title: "Готовые Shorts",
      text: "Созданы новые файлы. Исходные видео и монтажный план не изменены.",
      confirm: "Закрыть",
      onConfirm: async () => {},
    });
    const dialog = document.querySelector("#modalHost .dialog");
    if (!dialog) return;
    const box = document.createElement("div");
    box.className = "buttons";
    for (const file of valid) {
      for (const [label, url] of [
        ["MP4", file.url],
        ["SRT", file.subtitle_url],
      ]) {
        if (!url) continue;
        const anchor = document.createElement("a");
        anchor.className = "btn sm green";
        anchor.href = url + "?download=1";
        anchor.target = "_blank";
        anchor.rel = "noopener";
        anchor.textContent = "↓ " + label + " · Часть " + file.part_index;
        box.appendChild(anchor);
      }
    }
    dialog.querySelector(".buttons")?.before(box);
  }
  function optionalElement(id) {
    return $(id) || {};
  }
  function bindFinishing() {
    const canvasRoot = $("fcCanvas");
    if (!canvasRoot || !$("fcVideo")) return;
    const f = getFinishing(),
      s = selectedSubtitle(),
      a = f.audio,
      v = f.video;
    finishUpdateView();
    document.querySelectorAll("[data-ftab]").forEach(
      (el) =>
        (el.onclick = () => {
          ui.finishTab = el.dataset.ftab;
          stopAudioPreview();
          render();
        }),
    );
    document.querySelectorAll("[data-fpart]").forEach(
      (el) =>
        (el.onclick = () => {
          ui.finishPart = Number(el.dataset.fpart);
          ui.part = ui.finishPart;
          ui.finishCue = 0;
          stopAudioPreview();
          render();
        }),
    );
    document.querySelectorAll("[data-fpreset]").forEach(
      (el) =>
        (el.onclick = () => {
          const presets = {
            accent: {
              color: "#f6d779",
              font_size: 32,
              outline: 3,
              background: false,
              uppercase: true,
            },
            classic: {
              color: "#ffffff",
              font_size: 30,
              outline: 2,
              background: false,
              uppercase: false,
            },
            soft: {
              color: "#ffffff",
              font_size: 28,
              outline: 0,
              background: true,
              uppercase: false,
            },
          };
          Object.assign(s, presets[el.dataset.fpreset]);
          render();
        }),
    );
    document.querySelectorAll("[data-fcolor]").forEach(
      (el) =>
        (el.onclick = () => {
          s.color = el.dataset.fcolor;
          render();
        }),
    );
    document.querySelectorAll("[data-flayout]").forEach(
      (el) =>
        (el.onclick = () => {
          v.layout = el.dataset.flayout === "social" ? "cinema" : el.dataset.flayout;
          v.frame_style = el.dataset.flayout === "social" ? "social" : "plain";
          render();
        }),
    );
    for (const [id, key] of [["fcChannel", "channel_name"], ["fcHandle", "channel_handle"], ["fcPostCaption", "post_caption"]]) {
      $(id)?.addEventListener("input", (event) => {
        v[key] = event.target.value;
        // A previously rendered preview is a fixed MP4. Reset it before
        // editing; otherwise changed metadata would look baked when it is not.
        if ($("fcVideo")?.dataset.renderedPreview === "true") $("fcPreviewReset")?.click();
        finishUpdateView();
      });
    }
    $("fcCardVariant")?.addEventListener("change", (event) => { v.card_variant = event.target.value; render(); });
    const binds = [
      ["fcSize", s, "font_size", Number],
      ["fcX", s, "x", Number],
      ["fcY", s, "y", Number],
      ["fcOutline", s, "outline", Number],
      ["fcZoom", v, "zoom", Number],
      ["fcBlur", v, "blur", Number],
      ["fcBrightness", v, "brightness", Number],
      ["fcVignette", v, "vignette", Number],
      ["fcVolume", a, "volume", (x) => Number(x) / 100],
      ["fcFadeIn", a, "fade_in", Number],
      ["fcFadeOut", a, "fade_out", Number],
    ];
    binds.forEach(([id, obj, key, convert]) => {
      const el = $(id);
      if (!el) return;
      el.addEventListener("input", () => {
        obj[key] = convert(el.value);
        const target = $(id + "Label");
        if (target)
          target.textContent =
            el.value +
            ({
              fcSize: " px",
              fcOutline: " px",
              fcBlur: " px",
              fcFadeIn: " с",
              fcFadeOut: " с",
            }[id] || "%");
        if (id === "fcVolume") {
          const audio = $("fcAudio");
          if (audio) audio.volume = Math.min(1, obj[key]);
        }
        finishUpdateView();
      });
    });
    for (const [id, obj, key] of [
      ["fcCaptionEnabled", s, "enabled"],
      ["fcUppercase", s, "uppercase"],
      ["fcCaptionBg", s, "background"],
      ["fcMusicEnabled", a, "enabled"],
      ["fcDucking", a, "ducking"],
      ["fcGuides", s, "safe_guides"],
    ]) {
      const el = $(id);
      if (el)
        el.onchange = () => {
          obj[key] = el.checked;
          finishUpdateView();
        };
    }
    document.querySelectorAll("[data-fcue]").forEach(
      (el) =>
        (el.onclick = () => {
          ui.finishCue = Number(el.dataset.fcue);
          render();
        }),
    );
    $("fcAddCue")?.addEventListener("click", () => {
      const cues = selectedCues();
      const prev = cues[cues.length - 1],
        st = Number(prev?.end) || 0;
      const duration = Number(finishingPart()?.duration);
      if (!Number.isFinite(duration) || st >= duration) {
        notify("В конце части нет места для новой реплики. Измените таймкод последней.", true);
        return;
      }
      cues.push({ start: st, end: Math.min(duration, st + 3), text: "Новая реплика" });
      ui.finishCue = cues.length - 1;
      finishCueChanged();
      render();
    });
    $("fcDeleteCue")?.addEventListener("click", () => {
      const cues = selectedCues();
      if (cues.length <= 1) return;
      cues.splice(ui.finishCue || 0, 1);
      ui.finishCue = 0;
      finishCueChanged();
      render();
    });
    const tstart = $("fcCueStart"),
      tend = $("fcCueEnd");
    if (tstart && tend) {
      const commit = () => {
        const c = chosenCue();
        if (!c) return;
        const st = Number(tstart.value),
          en = Number(tend.value);
        if (
          !Number.isFinite(st) ||
          !Number.isFinite(en) ||
          st < 0 ||
          en <= st
        ) {
          notify("Конец реплики должен быть позже начала", true);
          return;
        }
        c.start = st;
        c.end = en;
        finishCueChanged();
      };
      tstart.onchange = commit;
      tend.onchange = commit;
    }
    const txt = $("fcCaptionText");
    if (txt)
      txt.oninput = (e) => {
        finishSaveCue(e.target.value);
        finishCueChanged();
      };
    const col = $("fcCustomColor");
    if (col)
      col.oninput = (e) => {
        s.color = e.target.value;
        finishUpdateView();
      };
    const tr = $("fcTrack");
    if (tr)
      tr.onchange = (e) => {
        if (a.mode === "per_part") {
          a.part_tracks ||= {};
          const part = db.plans[currentJob()?.id]?.parts?.[ui.finishPart];
          a.part_tracks[String(part?.index ?? ui.finishPart + 1)] =
            e.target.value;
        } else a.track = e.target.value;
        const audio = $("fcAudio"),
          name = audioName(f);
        if (audio) {
          audio.pause();
          if (name && a.enabled)
            audio.src =
              "/api/music/tracks/" + encodeURIComponent(name) + "/stream";
          else audio.removeAttribute("src");
        }
        finishUpdateView();
      };
    const mode = $("fcMusicMode");
    if (mode)
      mode.onchange = (e) => {
        a.mode = e.target.value;
        render();
      };
    const canvas = $("fcCanvas"),
      cap = $("fcCaption");
    if (cap && canvas) {
      let drag = false;
      cap.onpointerdown = (e) => {
        if (e.button !== 0) return;
        drag = true;
        cap.setPointerCapture(e.pointerId);
        e.preventDefault();
      };
      cap.onpointermove = (e) => {
        if (!drag) return;
        const box = canvas.getBoundingClientRect();
        s.x = Math.max(
          6,
          Math.min(94, Math.round(((e.clientX - box.left) / box.width) * 100)),
        );
        s.y = Math.max(
          7,
          Math.min(92, Math.round(((e.clientY - box.top) / box.height) * 100)),
        );
        finishUpdateView();
        for (const k of ["fcX", "fcY"]) {
          if ($(k)) {
            $(k).value = k === "fcX" ? s.x : s.y;
            $(k + "Label").textContent = $(k).value + "%";
          }
        }
      };
      cap.onpointerup = () => {
        drag = false;
      };
      cap.ondblclick = () => {
        s.x = 50;
        s.y = 74;
        finishUpdateView();
      };
      cap.onkeydown = (e) => {
        const step = e.shiftKey ? 5 : 1;
        if (e.key === "ArrowUp") s.y = Math.max(6, s.y - step);
        else if (e.key === "ArrowDown") s.y = Math.min(94, s.y + step);
        else if (e.key === "ArrowLeft") s.x = Math.max(5, s.x - step);
        else if (e.key === "ArrowRight") s.x = Math.min(95, s.x + step);
        else return;
        e.preventDefault();
        finishUpdateView();
      };
    }
    const video = $("fcVideo"),
      audio = $("fcAudio");
    if (audio) {
      const name = audioName(f);
      if (a.enabled && name)
        audio.src =
          ui.finishAudioURL ||
          "/api/music/tracks/" + encodeURIComponent(name) + "/stream";
      else audio.removeAttribute("src");
      audio.volume = a.volume;
    }
    if (video) {
      const back = $("fcBackdrop");
      const bar = $("fcSeek");
      video.ontimeupdate = () => {
        if (video.dataset.sourcePreview === "true" && !video.paused) {
          const cuts = finishingPart()?.cuts || [];
          const index = Number(video.dataset.previewCut) || 0;
          if (cuts[index] && (video.currentTime >= cuts[index].end || video.currentTime < cuts[index].start)) {
            const next = video.currentTime < cuts[index].start ? 0 : (index + 1) % cuts.length;
            video.dataset.previewCut = String(next);
            video.currentTime = cuts[next].start;
          }
        }
        if (
          back &&
          Number.isFinite(back.duration) &&
          Math.abs(back.currentTime - video.currentTime) > 0.22
        ) {
          try {
            back.currentTime = video.currentTime;
          } catch {}
        }
        const clock = finishingClock(video);
        if (bar && clock.duration > 0) {
          bar.value = (clock.time / clock.duration) * 100;
          const t = $("fcTime");
          if (t) t.textContent = reviewTime(clock.time);
        }
        syncFinishingCaption();
      };
      video.onloadedmetadata = () => {
        if (video.dataset.sourcePreview === "true") seekFinishing(video, 0);
        const d = $("fcDuration");
        if (d) d.textContent = reviewTime(finishingClock(video).duration);
      };
      video.onplay = () => {
        syncFinishingCaption();
        if ($("fcPlay")) $("fcPlay").textContent = "Ⅱ";
        back?.play().catch(() => {});
        if (a.enabled && audio?.src && video.dataset.renderedPreview !== "true") {
          audio.volume = a.volume;
          audio.play().catch(() => {});
        }
      };
      video.onpause = () => {
        syncFinishingCaption();
        if ($("fcPlay")) $("fcPlay").textContent = "▶";
        audio?.pause();
        back?.pause();
      };
      video.onended = () => {
        syncFinishingCaption();
        audio?.pause();
        back?.pause();
      };
      if (bar)
        bar.oninput = () => {
          const duration = finishingClock(video).duration;
          if (duration > 0) seekFinishing(video, duration * Number(bar.value) / 100);
        };
    }
    optionalElement("fcPlay").onclick = () => {
      if (video.paused)
        video
          .play()
          .catch(() => notify("Видео не удалось воспроизвести", true));
      else video.pause();
    };
    optionalElement("fcMute").onclick = () => {
      video.muted = !video.muted;
      $("fcMute").classList.toggle("active", !video.muted);
      notify(video.muted ? "Исходник без звука" : "Оригинальный звук включён");
    };
    optionalElement("fcGuideToggle").onclick = () => {
      s.safe_guides = !s.safe_guides;
      finishUpdateView();
      $("fcGuideToggle").classList.toggle("active", s.safe_guides);
    };
    optionalElement("fcPreviewReset").onclick = () => {
      video.pause();
      video.dataset.renderedPreview = "";
      const originInfo = finishingPreviewSource(), origin = originInfo.url;
      video.dataset.sourcePreview = String(originInfo.raw);
      if (origin && video.getAttribute("src") !== origin) {
        video.src = origin;
        video.load();
        const back = $("fcBackdrop");
        if (back) {
          back.src = origin;
          back.load();
        }
      }
      seekFinishing(video, 0);
      finishUpdateView();
    };
    optionalElement("fcReset").onclick = () => {
      modal({
        title: "Сбросить стиль оформления?",
        text: "Вернуть стандартные цвет, положение, размер, музыку и кадр. Тексты и таймкоды субтитров текущего монтажа останутся без изменений.",
        confirm: "Сбросить стиль",
        danger: true,
        onConfirm: async () => {
          const fresh = finishingDefaults();
          fresh.revision = getFinishing().revision ?? 0;
          fresh.video.layout =
            currE()?.settings?.layout || getFinishing().video.layout;
          await request(
            "PUT",
            `/api/episodes/${ui.episodeId}/finishing`,
            fresh,
          );
          render();
          notify("Стиль сброшен. Реплики монтажа сохранены.");
        },
      });
    };
    optionalElement("fcSave").onclick = async () => {
      try {
        const j = currentJob();
        if (!j || j.status !== "completed")
          throw new Error("Нужен завершённый монтаж");
        await request("PUT", `/api/jobs/${j.id}/finishing/state`, {
          profile: getFinishing(),
          captions: finishPendingCaptions(j),
        });
        notify("Правки сохранены");
      } catch (e) {
        notify(e.message, true);
      }
    };
    optionalElement("fcCopyStyle").onclick = () => {
      const style = structuredClone(s);
      const prev = getFinishing().part_overrides;
      for (const part of db.plans[currentJob()?.id]?.parts || []) {
        prev[String(part.index)] ||= {};
        prev[String(part.index)].style = structuredClone(style);
      }
      notify(
        "Стиль выбранной части применён ко всем частям, тексты не изменены.",
      );
      render();
    };
    optionalElement("fcPreviewRequest").onclick = async () => {
      try {
        const job = currentJob(),
          part = ui.finishPart;
        if (!job || job.status !== "completed")
          throw new Error("Нужен завершённый монтаж");
        await persistSelectedCaptions(job, part);
        const task = await request(
          "POST",
          "/api/jobs/" + job.id + "/previews",
          {
            part_index: db.plans[job.id]?.parts?.[part]?.index ?? part + 1,
            from: 0,
            duration: 5,
            settings: f,
          },
        );
        notify("Создаём предпросмотр. Подождите несколько секунд.");
        const result = await waitForFinishingJob(
          "/api/jobs/" + job.id + "/previews/" + task.preview_id,
        );
        if (result.status === "completed" && result.url) {
          if (ui.finishPart === part && currentJob()?.id === job.id) {
            const video = $("fcVideo");
            if (video) {
              video.pause();
              video.dataset.renderedPreview = "true";
              video.dataset.sourcePreview = "false";
              video.src = result.url;
              video.load();
              const back = $("fcBackdrop");
              if (back) {
                back.src = result.url;
                back.load();
              }
              finishUpdateView();
            }
          }
          notify("Серверный предпросмотр готов: кадр и звук пересобраны.");
        } else throw new Error(result.error || "Ошибка предпросмотра");
      } catch (error) {
        notify(error.message, true);
      }
    };
    optionalElement("fcExport").onclick = () => {
      modal({
        title: "Повторный экспорт Shorts",
        text: "Будет создан новый MP4 с текущим оформлением. Существующие Shorts не перезаписываются.",
        confirm: "Запустить экспорт",
        onConfirm: async () => {
          const job = currentJob();
          if (!job || job.status !== "completed")
            throw new Error("Нужен завершённый монтаж");
          await persistSelectedCaptions(job, ui.finishPart);
          const task = await request(
            "POST",
            "/api/jobs/" + job.id + "/exports",
            {
              part_indices: [
                db.plans[job.id]?.parts?.[ui.finishPart]?.index ??
                  ui.finishPart + 1,
              ],
              settings: f,
            },
          );
          notify("Экспорт запущен. Видео появится после завершения обработки.");
          (async () => {
            const result = await waitForFinishingJob(
              "/api/exports/" + task.export_id,
            );
            if (result.status !== "completed")
              throw new Error(result.error || "Ошибка рендера");
            showFinishingFiles(result.files);
            notify("Новый MP4 готов к скачиванию");
          })().catch((error) => notify(error.message, true));
        },
      });
    };
    $("fcImportAudio")?.addEventListener("click", () =>
      $("fcMusicFile").click(),
    );
    $("fcMusicFile").onchange = async (ev) => {
      const file = ev.target.files?.[0];
      if (!file) return;
      try {
        await request("POST", "/api/music/import", { file });
      } catch (err) {
        notify(err.message, true);
        return;
      }
      if (ui.finishAudioURL) URL.revokeObjectURL(ui.finishAudioURL);
      ui.finishAudioURL = URL.createObjectURL(file);
      a.track = file.name;
      $("fcAudio").src = ui.finishAudioURL;
      $("fcAudio").volume = a.volume;
      $("fcAudioSource").textContent = "Локальный файл · " + file.name;
      finishUpdateView();
      notify(
        "Аудиофайл загружен и доступен для одновременного прослушивания с видео.",
      );
    };
    $("fcHearAudio")?.addEventListener("click", async () => {
      const a = $("fcAudio");
      try {
        if (!a || !a.src) throw new Error("Нет аудиотрека для прослушивания");
        if (a.paused) {
          await a.play();
          notify("Воспроизводится выбранный трек");
        } else {
          a.pause();
          notify("Прослушивание остановлено");
        }
      } catch (e) {
        notify(e.message, true);
      }
    });
    canvas.addEventListener("keydown", (ev) => {
      if (ev.target === canvas && ev.code === "Space") {
        ev.preventDefault();
        $("fcPlay").click();
      }
    });
  }

  // Live Studio Edition: preserve original DOM/CSS, read records from the local backend.
  (async () => {
    try {
      try {
        localStorage.removeItem("kadr-authentic-ui-v2");
      } catch {}
      const refreshButton = document.querySelector(
        '.side-help [data-action="reset"]',
      );
      if (refreshButton) {
        refreshButton.textContent = "↻ Обновить";
        refreshButton.title = "Обновить проекты";
      }
      $("main").innerHTML =
        '<section class="empty"><strong>Загрузка проектов…</strong></section>';
      await window.KadrBridge.refresh(db, ui);
      const q = new URLSearchParams(location.search);
      const requestedProject = q.get("project"),
        requestedEpisode = q.get("episode"),
        requestedJob = q.get("job");
      if (requestedProject && projectBy(requestedProject)) {
        ui.projectId = requestedProject;
        ui.episodeId =
          db.episodes.find(
            (e) => e.project_id === requestedProject && !e.archived_at,
          )?.id || null;
        ui.jobId = null;
      }
      if (requestedEpisode && epBy(requestedEpisode)) {
        ui.episodeId = requestedEpisode;
        ui.projectId = epBy(requestedEpisode).project_id;
      }
      if (requestedJob && jobBy(requestedJob)) {
        ui.jobId = requestedJob;
        ui.episodeId = jobBy(requestedJob).episode_id || ui.episodeId;
        ui.projectId = epBy(ui.episodeId)?.project_id || ui.projectId;
      }
      const screen = q.get("screen") || "projects";
      if (["editor", "review", "finishing"].includes(screen) && ui.episodeId) {
        try {
          await window.KadrBridge.loadSelected(db, ui);
        } catch (e) {
          console.warn("Load selected montage:", e);
        }
      }
      go(
        [
          "projects",
          "episodes",
          "editor",
          "processing",
          "review",
          "finishing",
          "trash",
        ].includes(screen)
          ? screen
          : "projects",
      );
      runTicker();
    } catch (e) {
      $("main").innerHTML =
        '<section class="empty"><strong>Сервер недоступен</strong>Запустите КАДР и обновите страницу. ' +
        esc(e.message) +
        "</section>";
    }
  })();
})();
