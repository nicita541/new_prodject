/* KADR STUDIO / LIVE.  Exact reference DOM/CSS; real same-origin FastAPI.
   No demo records are ever sent to the server. */
(() => {
  "use strict";
  async function get(path, options = {}) {
    const { onResponse, ...fetchOptions } = options;
    const response = await fetch(path, {
      credentials: "same-origin",
      ...fetchOptions,
    });
    const type = response.headers.get("content-type") || "";
    const value = type.includes("json") ? await response.json() : { url: path };
    if (!response.ok) {
      const detail = value?.detail;
      const e = new Error(
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((v) => v.msg || "Ошибка").join("; ")
            : "Ошибка HTTP " + response.status,
      );
      e.status = response.status;
      throw e;
    }
    if (typeof onResponse === "function") onResponse(response.status);
    return value;
  }
  const date = (value) => {
    const n = typeof value === "number" ? value : Date.parse(value || "");
    return Number.isFinite(n) ? n : Date.now();
  };
  // Real montage plans expose source.duration, not plan.duration.
  // The reference timeline uses plan.duration, so normalize at the API border.
  function normalizePlan(plan) {
    const cuts = (plan.parts || []).flatMap((part) => part.cuts || []);
    const last = Math.max(0, ...cuts.map((c) => Number(c.end) || 0));
    const duration = Number(plan.source?.duration) || last || 1;
    return { ...plan, duration: Math.max(duration, last, 1) };
  }
  async function refresh(db, ui) {
    // Music/health are optional for browsing already rendered Shorts. One
    // misconfigured audio file must not blank the entire projects page.
    const [library, sources, jobs, musicOutcome, healthOutcome] =
      await Promise.all([
        get("/api/library"),
        get("/api/sources"),
        get("/api/jobs?summary=true" +
          (ui.screen === "processing" && ui.jobId
            ? "&progress_job_id=" + encodeURIComponent(ui.jobId) : "")),
        get("/api/music").then(
          (value) => ({ value }),
          (error) => ({ error }),
        ),
        get("/api/health").then(
          (value) => ({ value }),
          (error) => ({ error }),
        ),
      ]);
    const music = musicOutcome.value || {
      enabled: false,
      volume: 0.15,
      track: null,
      mode: "random_per_part",
      part_tracks: {},
      tracks: [],
    };
    const health = healthOutcome.value || {
      ready: false,
      busy: false,
      missing: ["Сервис недоступен"],
    };
    if (musicOutcome.error)
      console.warn("Music settings unavailable:", musicOutcome.error);
    if (healthOutcome.error)
      console.warn("Server health unavailable:", healthOutcome.error);
    db.projects = library.projects || [];
    db.episodes = library.episodes || [];
    db.sources = sources || [];
    db.jobs = (jobs || []).map((j) => ({
      ...j,
      created_at: date(j.created_at),
      updated_at: date(j.updated_at),
      episode_id:
        j.episode_id ||
        library.episodes?.find((e) => e.jobs?.some((a) => a.id === j.id))?.id,
    }));
    db.health = health;
    db.music = {
      ...music,
      tracks: Array.isArray(music.tracks) ? music.tracks : [],
    };
    db.plans ||= {};
    db.finishing ||= {};
    // A library can have hundreds of old jobs. Never fetch *every* plan/profile
    // during startup or the 3-second progress refresh: that blocked the UI.
    try {
      db.deepseek = await get("/api/deepseek");
    } catch (error) {
      console.warn("DeepSeek status unavailable:", error);
      db.deepseek = {
        configured: false,
        remaining_usd: null,
        model: "недоступна",
      };
    }
    const activeProjects = new Set(
      db.projects.filter((p) => !p.archived_at).map((p) => p.id),
    );
    const activeEpisode = (e) =>
      !e.archived_at && activeProjects.has(e.project_id);
    if (!activeProjects.has(ui.projectId)) {
      ui.projectId = db.projects.find((p) => !p.archived_at)?.id || null;
    }
    if (
      !db.episodes.some(
        (e) =>
          e.id === ui.episodeId &&
          e.project_id === ui.projectId &&
          activeEpisode(e),
      )
    ) {
      ui.episodeId =
        db.episodes.find(
          (e) => e.project_id === ui.projectId && activeEpisode(e),
        )?.id ||
        db.episodes.find(activeEpisode)?.id ||
        null;
    }
    if (
      !db.jobs.some((j) => j.id === ui.jobId && j.episode_id === ui.episodeId)
    ) {
      const list = db.jobs.filter((j) => j.episode_id === ui.episodeId);
      ui.jobId =
        list.find((j) => j.status === "completed")?.id || list[0]?.id || null;
    }
  }
  async function loadSelected(db, ui) {
    if (ui.episodeId && !db.finishing[ui.episodeId]) {
      db.finishing[ui.episodeId] = await get(
        "/api/episodes/" + encodeURIComponent(ui.episodeId) + "/finishing",
      );
    }
    const job = db.jobs.find((j) => j.id === ui.jobId);
    if (!job || job.status !== "completed") return;
    if (!db.plans[job.id])
      db.plans[job.id] = normalizePlan(
        await get("/api/jobs/" + encodeURIComponent(job.id) + "/plan"),
      );
    if (job.episode_id && !db.finishing[job.episode_id]) {
      db.finishing[job.episode_id] = await get(
        "/api/episodes/" + encodeURIComponent(job.episode_id) + "/finishing",
      );
    }
    // Eagerly resolve captions only for the *selected* completed job.
    // Never re-use episode-level cue text from a previous montage attempt.
    db.captionOverrides ||= {};
    // The prior Promise.all launched one request per part at once.
    // Long jobs could saturate FastAPI's thread pool and freeze the Studio.
    // Fetch at most four caption files concurrently, preserving already-loaded
    // parts if a later request needs to be retried.
    const pending = (db.plans[job.id]?.parts || []).filter(
      (part) => !db.captionOverrides[job.id + ":" + part.index],
    );
    for (let offset = 0; offset < pending.length; offset += 4) {
      await Promise.all(
        pending.slice(offset, offset + 4).map(async (part) => {
          const key = job.id + ":" + part.index;
          db.captionOverrides[key] = await get(
            "/api/jobs/" +
              encodeURIComponent(job.id) +
              "/parts/" +
              encodeURIComponent(part.index) +
              "/captions",
          );
        }),
      );
    }
  }
  async function request(method, path, body, db, ui, onResponse) {
    let options = { method, onResponse };
    if (!["GET", "HEAD"].includes(method) && body != null) {
      if (body.rawJsonFile instanceof File) {
        options.body = body.rawJsonFile;
        options.headers = { "Content-Type": "application/json" };
      } else if (body.file instanceof File) {
        const form = new FormData();
        form.append("file", body.file);
        options.body = form;
      } else if (body instanceof FormData) {
        options.body = body;
      } else {
        let data = body;
        if (
          method === "PUT" &&
          /^\/api\/episodes\/[^/]+\/finishing$/.test(path)
        ) {
          const { episode_id, ...profile } = body;
          data = {
            ...profile,
            part_overrides: Object.fromEntries(
              Object.entries(profile.part_overrides || {}).map(
                ([key, override]) => [key, { ...override, cues: undefined }],
              ),
            ),
          };
        }
        if (
          method === "PUT" &&
          /^\/api\/jobs\/[^/]+\/finishing\/state$/.test(path)
        ) {
          const { episode_id, ...profile } = body.profile;
          data = {
            ...body,
            profile: {
              ...profile,
              part_overrides: Object.fromEntries(
                Object.entries(profile.part_overrides || {}).map(
                  ([key, override]) => [key, { ...override, cues: undefined }],
                ),
              ),
            },
          };
        }
        if (
          method === "POST" &&
          /\/api\/jobs\/[^/]+\/(?:previews|exports)$/.test(path) &&
          body.settings
        ) {
          const { episode_id, revision, ...settings } = body.settings;
          data = { ...body, settings };
        }
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify(data);
      }
    }
    const result = await get(path, options);
    if (
      /^\/api\/jobs\/[^/]+\/previews(?:\/[^/]+)?$/.test(path) &&
      result.preview_id
    ) {
      db.previews ||= {};
      db.previews[result.preview_id] = result;
    }
    if (
      (/^\/api\/jobs\/[^/]+\/exports$/.test(path) ||
        /^\/api\/exports\/[^/]+$/.test(path)) &&
      result.export_id
    ) {
      db.exports ||= {};
      db.exports[result.export_id] = result;
    }
    if (method === "GET") {
      if (path === "/api/music") db.music = { ...db.music, ...result };
      else if (path === "/api/health") db.health = result;
      else if (path === "/api/sources")
        db.sources = Array.isArray(result) ? result : [];
      else if (path === "/api/jobs") {
        db.jobs = (Array.isArray(result) ? result : []).map((j) => ({
          ...j,
          created_at: date(j.created_at),
          updated_at: date(j.updated_at),
          episode_id:
            j.episode_id ||
            db.episodes.find((e) => e.jobs?.some((a) => a.id === j.id))?.id,
        }));
      } else if (/^\/api\/jobs\/[^/]+$/.test(path)) {
        const id = path.split("/")[3];
        const item = {
          ...result,
          created_at: date(result.created_at),
          updated_at: date(result.updated_at),
          episode_id:
            result.episode_id ||
            db.episodes.find((e) => e.jobs?.some((a) => a.id === id))?.id,
        };
        const index = db.jobs.findIndex((j) => j.id === id);
        if (index >= 0) db.jobs[index] = item;
        else db.jobs.push(item);
      } else if (path === "/api/deepseek") db.deepseek = result;
      else if (path === "/api/library") await refresh(db, ui);
      else if (/^\/api\/jobs\/[^/]+\/plan$/.test(path)) {
        db.plans[path.split("/")[3]] = normalizePlan(result);
      }
    } else if (
      method === "PUT" &&
      /^\/api\/jobs\/[^/]+\/finishing\/state$/.test(path)
    ) {
      db.finishing ||= {};
      db.finishing[result.profile.episode_id] = result.profile;
      db.captionOverrides ||= {};
      for (const caption of result.captions) {
        db.captionOverrides[caption.job_id + ":" + caption.part_index] =
          caption;
        if (db.finishDirtyCues)
          delete db.finishDirtyCues[caption.job_id + ":" + caption.part_index];
      }
    } else if (
      method === "PUT" &&
      /^\/api\/episodes\/[^/]+\/finishing$/.test(path)
    ) {
      db.finishing ||= {};
      db.finishing[path.split("/")[3]] = result;
    } else if (method === "PUT" && /\/captions$/.test(path)) {
      db.captionOverrides ||= {};
      const key = path.split("/")[3] + ":" + path.split("/")[5];
      db.captionOverrides[key] = result;
      if (db.finishDirtyCues) delete db.finishDirtyCues[key];
    } else {
      // Retrying the SAME job may regenerate plan.json. Drop the old browser
      // snapshot so review/finishing never show cuts from an earlier attempt.
      const retry =
        method === "POST" && path.match(/^\/api\/jobs\/([^/]+)\/(?:retry|analysis-provider|analysis-checks)$/);
      if (retry) {
        delete db.plans[retry[1]];
      }
      await refresh(db, ui);
    }
    return result;
  }
  // Lightweight client diagnostics. No form content, filenames, query
  // strings, credentials, request payloads or input values are recorded.
  let lastError = "",
    lastErrorAt = 0;
  function sendDiagnostic(kind, action = "", message = "", line = 0) {
    try {
      const body = JSON.stringify({
        kind,
        action: String(action).slice(0, 80),
        message: String(message).slice(0, 500),
        line: Number(line) || 0,
      });
      fetch("/api/diagnostics/client", {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body,
        keepalive: true,
      }).catch(() => {});
    } catch (_ignore) {}
  }
  document.addEventListener(
    "click",
    (event) => {
      const el = event.target?.closest?.("[data-action]");
      if (!el) return;
      const action = String(el.dataset.action || "").slice(0, 50);
      const screen = String(el.dataset.screen || "").slice(0, 25);
      if (!/^[a-z0-9_-]{1,50}$/i.test(action)) return;
      sendDiagnostic(
        "ui_action",
        screen ? "click:" + action + ":" + screen : "click:" + action,
      );
    },
    true,
  );
  window.addEventListener("error", (event) => {
    const label = String(event.message || "Browser JavaScript error");
    const now = Date.now();
    if (label === lastError && now - lastErrorAt < 3000) return;
    lastError = label;
    lastErrorAt = now;
    sendDiagnostic("ui_error", "runtime", label, event.lineno || 0);
  });
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    sendDiagnostic(
      "unhandled_rejection",
      "promise",
      String(reason?.message || "Unhandled promise rejection"),
    );
  });
  window.KadrBridge = { get, refresh, loadSelected, request };
})();
