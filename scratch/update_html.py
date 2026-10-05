from pathlib import Path

html_content = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>КАДР STUDIO</title>
  <link rel="stylesheet" href="/static/style.css?v=2.0">
  <script src="/static/app.js?v=2.0" defer></script>
  <script src="/static/library.js?v=2.0" defer></script>
</head>
<body>
<div class="app-layout">
  
  <!-- Sidebar Navigation -->
  <aside class="sidebar">
    <a href="#projects" class="brand" aria-label="Кадр, проекты">
      <span class="brand-mark" aria-hidden="true">К</span>
      КАДР STUDIO
    </a>
    
    <nav class="nav-menu" aria-label="Главное меню">
      <a href="#projects" class="nav-link nav-active">Проекты</a>
      <a href="#trash" class="nav-link">Корзина</a>
    </nav>
    
    <span id="connection" class="status-pill">
      <span class="status-dot"></span>
      <span id="connection-label">Подключение...</span>
    </span>
  </aside>

  <!-- Main Workspace -->
  <div class="main-content">
    <main class="screen-shell">
      
      <!-- Global Headers -->
      <nav id="breadcrumbs" class="breadcrumbs" aria-label="Путь проекта"></nav>
      <div class="screen-toolbar">
        <div>
          <h1 id="workspace-title" class="page-title">Проекты аниме</h1>
          <p id="screen-context" class="page-desc"></p>
        </div>
      </div>
      <p id="library-message" class="message" role="status"></p>

      <!-- SCREEN: TRASH -->
      <section id="trash-screen" class="app-screen" aria-label="Корзина" hidden>
        <div id="trash-cards" class="grid-cards"></div>
        <div id="trash-empty" class="empty-state" hidden>Корзина пуста</div>
      </section>

      <!-- SCREEN: PROJECTS -->
      <section id="projects-screen" class="app-screen" aria-label="Проекты" hidden>
        <div class="action-bar">
          <form id="project-form" class="action-bar-form">
            <input type="text" id="project-title" class="form-input" placeholder="Название нового проекта (например: Магическая битва)" required style="flex:1;">
            <button type="submit" class="btn-primary" style="white-space: nowrap;">+ Создать проект</button>
          </form>
        </div>
        <div id="project-cards" class="grid-cards"></div>
        <div id="projects-empty" class="empty-state" hidden>Нет проектов. Создайте первый проект выше.</div>
      </section>

      <!-- SCREEN: EPISODES -->
      <section id="episodes-screen" class="app-screen" aria-label="Серии" hidden>
        <div class="action-bar" style="justify-content: space-between;">
          <form id="episode-form" style="display: flex; align-items: center; gap: 12px;">
            <span class="muted small" style="white-space: nowrap; font-weight: 600;">Номер серии:</span>
            <input type="number" id="episode-number" class="form-input" min="1" step="1" required style="width: 80px;">
            <button type="submit" class="btn-primary" style="white-space: nowrap;">+ Добавить серию</button>
          </form>
          <button id="delete-current-project" class="btn-danger" type="button">Удалить проект</button>
        </div>
        <div id="episode-cards" class="grid-cards"></div>
        <div id="episodes-empty" class="empty-state" hidden>Нет добавленных серий.</div>
      </section>

      <!-- SCREEN: EDIT (Settings) -->
      <section id="edit-screen" class="app-screen" aria-label="Настройки серии" hidden>
        <div class="editor-layout">
          
          <!-- Left Column: Source and Configuration -->
          <div class="panel source-panel">
            <div class="panel-heading">
              <h2 id="source-heading" class="panel-title">Исходник</h2>
              <div style="display:flex; gap:10px; align-items:center;">
                <button id="delete-current-episode" class="btn-danger" type="button">Удалить серию</button>
                <a id="edit-review-link" class="btn-secondary" hidden>К проверке монтажа</a>
              </div>
            </div>
            
            <form id="create-form">
              <!-- Source Selection -->
              <div class="form-group">
                <label class="form-label" for="source">Видеофайл</label>
                <div style="display:flex; gap:12px;">
                  <select id="source" class="form-select" required style="flex:1;">
                    <option value="" hidden disabled selected>Выберите видео этой серии</option>
                  </select>
                  <button id="refresh-sources" type="button" class="btn-secondary" title="Обновить список">↻</button>
                </div>
                <div style="display:flex; justify-content:space-between; margin-top:8px;">
                  <span id="source-size" class="small muted"></span>
                </div>
              </div>

              <div class="upload-zone" id="upload-button" tabindex="0" role="button" aria-label="Загрузить файл">
                <span class="upload-icon">⇪</span>
                <span class="upload-text" id="upload-label">Перетащите или нажмите для загрузки видео</span>
                <span class="upload-hint">MP4, MKV или WebM</span>
                <input type="file" id="file-input" accept="video/mp4,video/x-matroska,video/webm" hidden>
              </div>
              <div id="upload-progress" class="form-group" hidden style="margin-top:14px;">
                <progress id="upload-meter" max="100" value="0"></progress>
              </div>

              <!-- Layout & Styling -->
              <div class="settings-group">
                <div class="form-group">
                  <label class="form-label" for="layout">Формат кадра</label>
                  <select id="layout" class="form-select">
                    <option value="portrait" selected>Вертикальный (9:16) — для Shorts/Reels/TikTok</option>
                    <option value="landscape">Горизонтальный (16:9)</option>
                  </select>
                  <p id="layout-description" class="muted small" style="margin-top:6px;"></p>
                </div>
                <div class="form-group">
                  <label class="form-label" for="caption-style">Стиль субтитров</label>
                  <select id="caption-style" class="form-select">
                    <option value="accent" selected>Акцент (Жёлтый с обводкой)</option>
                    <option value="classic">Классика (Белый с тенью)</option>
                  </select>
                  <div id="style-preview" class="panel" style="margin-top:12px; display:flex; align-items:flex-end; justify-content:center; height:100px; background:#000; border: 1px solid var(--border-light);">
                     <strong id="preview-subtitle" style="text-align:center;">Пример субтитров</strong>
                  </div>
                </div>
              </div>

              <!-- AI Provider Config -->
              <div class="settings-group">
                <div class="form-group">
                  <label class="form-label" for="analysis-provider">Сценарист (Нейросеть)</label>
                  <select id="analysis-provider" class="form-select">
                    <option value="deepseek" selected>DeepSeek (Облако)</option>
                    <option value="local">Локальная (Быстрая)</option>
                  </select>
                  <p id="provider-description" class="muted small" style="margin-top:8px;"></p>
                  <p id="deepseek-config" class="muted small" style="margin-top:8px; color:var(--danger);"></p>
                </div>

                <details id="deepseek-details" class="form-group">
                  <summary class="settings-summary">Настройки DeepSeek <span class="muted small" id="provider-balance-time"></span></summary>
                  <div class="settings-content">
                    <div id="deepseek-notice" class="notice" hidden>
                      <strong id="deepseek-notice-title"></strong>
                      <p id="deepseek-notice-description" class="muted small" style="margin-top:4px;"></p>
                      <p class="muted small" style="margin-top:8px;"><label style="display:flex; align-items:center; gap:8px;"><input type="checkbox" id="hybrid-fallback"> Использовать локальную нейросеть при ошибках DeepSeek</label></p>
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
                      <div><label class="form-label">Бюджет серии</label><div id="deepseek-budget" style="font-size:18px; font-weight:700; color:var(--accent-light);"></div></div>
                      <div><label class="form-label">Остаток</label><div id="deepseek-remaining" style="font-size:18px; font-weight:700;"></div></div>
                      <div style="grid-column: 1 / -1;"><label class="form-label">Потрачено в этом месяце</label><div id="deepseek-charged" style="font-size:14px; color:var(--text-secondary);"></div></div>
                    </div>
                    <div style="display:flex; gap:12px; margin-top:8px;">
                      <a href="/docs/ai/deepseek-setup.md" class="btn-text">Инструкция по ключам</a>
                      <button id="balance-refresh-button" type="button" class="btn-secondary">Обновить баланс</button>
                    </div>
                  </div>
                </details>
              </div>

              <!-- Music Config -->
              <div class="settings-group">
                <details id="music-section" class="form-group" open>
                  <summary class="settings-summary">Фоновая музыка <span id="music-summary" class="muted small"></span></summary>
                  <div class="settings-content">
                    <label style="display:flex; align-items:center; gap:8px; font-size:13.5px;"><input type="checkbox" id="music-enabled"> Добавлять фоновую музыку</label>
                    <div style="display:flex; gap:10px; flex-wrap:wrap;">
                      <button id="music-open-folder" type="button" class="btn-secondary">Открыть папку</button>
                      <button id="music-copy-path" type="button" class="btn-secondary">Скопировать путь</button>
                      <button id="music-refresh" type="button" class="btn-secondary">↻ Обновить</button>
                    </div>
                    <p id="music-folder-path" class="muted small"></p>
                    <div class="form-group">
                      <label id="music-volume-label" class="form-label" for="music-volume">Громкость (15%)</label>
                      <input type="range" id="music-volume" min="0.01" max="1.0" step="0.01" value="0.15" style="width:100%;">
                    </div>
                    <div class="form-group">
                      <label class="form-label" for="music-mode">Режим подстановки</label>
                      <select id="music-mode" class="form-select">
                        <option value="single" selected>Один трек на всё видео</option>
                        <option value="random_per_part">Случайный трек для каждой части</option>
                        <option value="manual_per_part">Выбрать вручную для каждой части</option>
                      </select>
                    </div>
                    <div id="music-single-panel" class="form-group">
                      <label class="form-label" for="music-track">Трек</label>
                      <select id="music-track" class="form-select"></select>
                      <label style="display:flex; align-items:center; gap:8px; margin-top:8px; font-size:12px;"><input type="checkbox" id="music-random"> Выбрать случайный при монтаже</label>
                    </div>
                    <div id="music-parts-panel" hidden class="form-group">
                      <p id="music-parts-count" class="form-label"></p>
                      <p id="music-parts-hint" class="muted small"></p>
                      <div id="music-parts-list" style="max-height: 200px; overflow-y: auto; display:flex; flex-direction:column; gap:8px; margin-top:12px;"></div>
                    </div>
                    <p id="music-current" class="muted small"></p>
                    <p id="music-message" class="message" role="status" hidden></p>
                  </div>
                </details>
              </div>

              <!-- Submission -->
              <div class="settings-group">
                <p id="processing-note" class="muted small" style="margin-bottom:12px;"></p>
                <div style="display:flex; gap:16px; align-items:center; justify-content:space-between;">
                  <label style="display:flex; align-items:center; gap:8px; font-size:13px;"><input type="checkbox" id="save-settings"> Сохранить по умолчанию</label>
                  <button id="create-button" type="submit" class="btn-primary">Смонтировать</button>
                </div>
                <p id="form-message" class="message" role="status" hidden></p>
                
                <!-- Dependencies check -->
                <div id="readiness" class="notice" hidden style="margin-top:16px;">
                  <strong>Требуются компоненты</strong>
                  <ul id="missing-list" style="margin-top:8px; padding-left:16px;"></ul>
                </div>
                <!-- DeepSeek check -->
                <div id="deepseek-check" class="notice" hidden style="margin-top:16px;">
                  <strong>Проблема с DeepSeek</strong>
                  <p id="deepseek-check-message"></p>
                </div>
                <!-- Recovery block -->
                <div id="deepseek-recovery" class="notice" hidden style="margin-top:16px;">
                  <strong>Восстановление сеанса</strong>
                  <p id="recovery-description"></p>
                  <button id="recovery-button" type="button" class="btn-secondary" style="margin-top:12px;">Продолжить с локальной нейросетью</button>
                  <p id="recovery-message" class="message" role="status" hidden></p>
                </div>
              </div>
            </form>
          </div>

          <!-- Right Column: Job Progress & History -->
          <div style="display:flex; flex-direction:column; gap:24px;">
            <div id="job-panel" class="panel" hidden>
              <div class="panel-heading">
                <h2 id="job-heading" class="panel-title">Монтаж</h2>
                <span id="job-status" class="badge"></span>
              </div>
              
              <div>
                <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:8px;">
                  <span id="stage-label" style="font-weight:600;"></span>
                  <span id="progress-label" class="muted"></span>
                </div>
                <progress id="job-progress" max="100" value="0"></progress>
                <p id="job-message" class="message" role="status" hidden></p>
                <pre id="job-error" class="message" style="color:var(--danger); white-space:pre-wrap;" hidden></pre>
              </div>
              
              <ul class="stages-list">
                <li class="stage-item" data-stage="prepare"><div class="stage-icon"></div><div class="stage-copy"><strong>Подготовка видео</strong><div class="small muted" data-stage-owner></div><div class="small muted" data-stage-state></div></div></li>
                <li class="stage-item" data-stage="transcribe"><div class="stage-icon"></div><div class="stage-copy"><strong>Распознавание речи</strong><div class="small muted" data-stage-owner></div><div class="small muted" data-stage-state></div></div></li>
                <li class="stage-item" data-stage="analyze"><div class="stage-icon"></div><div class="stage-copy"><strong>Сценарий</strong><div class="small muted" data-stage-owner></div><div class="small muted" data-stage-state></div></div></li>
                <li class="stage-item" data-stage="condense"><div class="stage-icon"></div><div class="stage-copy"><strong>Смысловая выжимка</strong><div class="small muted" data-stage-owner></div><div class="small muted" data-stage-state></div></div></li>
                <li class="stage-item" data-stage="framing"><div class="stage-icon"></div><div class="stage-copy"><strong>Кадрирование</strong><div class="small muted" data-stage-owner></div><div class="small muted" data-stage-state></div></div></li>
                <li class="stage-item" data-stage="plan"><div class="stage-icon"></div><div class="stage-copy"><strong>План монтажа</strong><div class="small muted" data-stage-owner></div><div class="small muted" data-stage-state></div></div></li>
                <li class="stage-item" data-stage="render"><div class="stage-icon"></div><div class="stage-copy"><strong>Сборка видео</strong><div class="small muted" data-stage-owner></div><div class="small muted" data-stage-state></div></div></li>
              </ul>

              <div style="display:flex; gap:12px; margin-top:24px;">
                <button id="cancel-button" type="button" class="btn-danger" hidden>Отменить</button>
                <button id="retry-button" type="button" class="btn-primary" hidden>Повторить</button>
              </div>
              
              <details class="settings-group" style="margin-top:24px;">
                <summary class="settings-summary">Информация о задаче</summary>
                <div class="settings-content">
                  <p class="muted small">Исходник: <span id="job-source" style="color:var(--text-primary);"></span></p>
                  <p class="muted small">Сценарист: <span id="job-provider" style="color:var(--text-primary);"></span></p>
                  <p class="muted small">Стиль: <span id="job-editing" style="color:var(--text-primary);"></span></p>
                  <div style="margin-top:12px;">
                    <span class="muted small">Потрачено на сценарий:</span>
                    <div id="job-spending" style="font-size:16px; font-weight:600; color:var(--accent-light);"></div>
                  </div>
                  <div style="margin-top:12px;">
                    <span class="muted small">Оценка бюджета (до старта):</span>
                    <div id="job-budget-estimate" style="font-size:16px; font-weight:600;"></div>
                    <button id="reset-budget-button" type="button" class="btn-text" style="margin-top:4px;" hidden>Забыть бюджет и сбросить ошибку</button>
                  </div>
                  <p style="margin-top:12px;"><a id="plan-link" href="#" target="_blank" class="btn-text" hidden>План монтажа (JSON)</a></p>
                  <p id="episode-source-note" class="muted small" style="margin-top:12px;"></p>
                </div>
              </details>
            </div>

            <div class="panel history-panel">
              <div class="panel-heading">
                <h2 class="panel-title">История монтажа (<span id="history-count">0</span>)</h2>
              </div>
              <div id="history-empty" class="muted small">Истории пока нет.</div>
              <div id="history-list" class="playlist-list"></div>
            </div>
          </div>

        </div>
      </section>

      <!-- SCREEN: REVIEW (NLE) -->
      <section id="review-screen" class="app-screen" aria-label="Проверка монтажа" hidden>
        <div class="screen-toolbar">
          <label class="form-label" for="episode-attempt" style="display:flex; align-items:center; gap:12px; margin:0;">
            <span class="muted small" style="font-weight:600;">Попытка монтажа:</span> 
            <select id="episode-attempt" class="form-select" style="width:auto;"></select>
          </label>
          <a id="review-edit-link" class="btn-secondary">⚙ Настройки серии</a>
        </div>
        
        <div class="review-workspace">
          
          <!-- Top Row: Source & Shorts -->
          <div class="review-top-row">
            
            <section id="source-panel-review" class="panel source-panel-review">
              <div class="panel-heading">
                <h2 class="panel-title">Исходник</h2>
              </div>
              <div class="player-container">
                <video id="source-player" controls playsinline preload="metadata"></video>
              </div>
              <div style="display:flex; justify-content:space-between; align-items:center; margin-top:16px;">
                <p id="source-clock" class="muted small"></p>
                <label style="display:flex; align-items:center; gap:8px; font-size:12px;"><input id="source-limit" type="checkbox"> В пределах фрагмента</label>
              </div>
              <p id="source-selection" class="small muted" style="margin-top:8px;">Выбери фрагмент на таймлайне.</p>
              <button id="source-full-button" class="btn-secondary" type="button" style="margin-top:12px;">Смотреть целиком</button>
              <p id="source-error" class="message" hidden></p>
            </section>

            <section id="results-panel" class="panel playlist-panel" hidden>
              <div class="panel-heading">
                <h2 id="results-heading" class="panel-title">Шортсы (<span id="parts-count"></span>)</h2>
              </div>
              <details id="quality-warnings" class="quality-warnings form-group" hidden>
                <summary class="settings-summary"><span id="quality-summary"></span></summary>
                <div class="settings-content">
                   <p id="quality-message" class="muted small"></p>
                   <ul id="quality-warning-list" style="padding-left:16px; font-size:12px;"></ul>
                </div>
              </details>
              <details id="quality-notes" class="quality-notes form-group" hidden>
                <summary class="settings-summary">Комментарии</summary>
                <div class="settings-content">
                  <ul id="quality-note-list" style="padding-left:16px; font-size:12px;"></ul>
                </div>
              </details>
              <div class="shorts-preview-box">
                <video id="player" controls playsinline preload="metadata" loop></video>
              </div>
              <div id="playlist" class="playlist-list"></div>
              <div id="part-music-badge" class="badge" hidden></div>
              <div style="display:flex; flex-wrap:wrap; gap:10px; margin-top:16px;">
                <button id="download-video" class="btn-primary" type="button">Скачать видео</button>
                <button id="download-all" class="btn-secondary" type="button">Скачать всё (.zip)</button>
                <button id="download-subtitle" class="btn-secondary" type="button">Субтитры (.srt)</button>
              </div>
              <p id="download-status" class="muted small" style="margin-top:8px;"></p>
              <p id="player-message" class="message" hidden></p>
              
              <div id="part-context" class="form-group" hidden style="margin-top:24px; padding-top:24px; border-top:1px solid var(--border-subtle);">
                <h3 id="part-context-heading" style="font-size:14px; margin-bottom:12px;">Контекст для ИИ</h3>
                <p id="part-context-title" class="small"></p>
                <p id="part-context-synopsis" class="small muted" style="margin-top:4px;"></p>
                <p id="part-context-fallback" class="small" style="color:var(--danger); margin-top:4px;" hidden>Генерация не удалась.</p>
                <details style="margin-top:12px;">
                  <summary class="settings-summary">Системный промпт</summary>
                  <div class="settings-content">
                    <textarea id="part-context-prompt" readonly rows="6" class="form-input"></textarea>
                    <button id="copy-part-context" type="button" class="btn-secondary">Копировать</button>
                    <span id="context-copy-status" class="small muted" style="margin-left:12px;"></span>
                  </div>
                </details>
              </div>
            </section>
          </div>

          <!-- Bottom Row: Timeline -->
          <div class="review-bottom-row">
            <section id="timeline-panel" class="panel timeline-panel" hidden>
              <div class="panel-heading">
                <h2 id="timeline-heading" class="panel-title">Таймлайн (<span id="timeline-duration"></span>)</h2>
                <label style="font-size:12px; display:flex; gap:8px; align-items:center;">
                  <span class="muted">Масштаб:</span>
                  <select id="timeline-zoom" class="form-select" style="padding: 6px 10px; width:auto;">
                     <option value="1">По ширине окна</option>
                     <option value="2">2x (Крупнее)</option>
                     <option value="5">5x (Детально)</option>
                     <option value="10">10x (Монтаж)</option>
                  </select>
                </label>
              </div>
              <div class="timeline-scroll">
                <div id="timeline-map" class="timeline-map">
                  <div id="timeline-ruler" class="timeline-ruler"></div>
                  <div id="timeline-groups" class="timeline-groups"></div>
                  <div class="timeline-line">
                    <div id="timeline-overview" class="timeline-track"></div>
                    <div id="timeline-playhead" class="timeline-playhead"></div>
                  </div>
                  <div id="analysis-debug-lane" class="timeline-track" style="margin-top:8px; background:rgba(0,0,0,0.3); border-color:transparent; height:24px;" hidden></div>
                </div>
              </div>
              <div id="analysis-debug-info" class="form-group" hidden style="margin-top:16px;">
                 <p id="analysis-debug-title" class="small font-weight:600"></p>
                 <p id="analysis-debug-detail" class="small muted"></p>
              </div>
              <label style="display:flex; align-items:center; gap:8px; font-size:12px; margin-top:16px;"><input type="checkbox" id="analysis-debug"> Показать отладочный слой</label>
            </section>
            <p id="review-empty" class="empty-state" hidden>Готового монтажа пока нет. Вернитесь в настройки серии.</p>
          </div>
        </div>
      </section>
    </main>

    <!-- Footer -->
    <footer class="app-footer">
      <span style="font-weight: 700; letter-spacing: -0.2px; color: #fff;">КАДР STUDIO</span>
      <div style="display: flex; align-items: center; gap: 8px;">
        <span class="storage-badge" id="storage-title"></span>
        <span id="storage-description"></span>
      </div>
    </footer>
  </div>
</div>
</body>
</html>"""

Path("app/static/index.html").write_text(html_content, "utf-8")
print("app/static/index.html successfully updated")
