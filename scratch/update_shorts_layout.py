from pathlib import Path

# Update index.html
html_path = Path("app/static/index.html")
html = html_path.read_text("utf-8")

old_results = """          <!-- 3. ПОД НИМ: ГОТОВЫЕ ШОРТСЫ И AI КОНТЕКСТ -->
          <div class="review-bottom-grid" style="display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(360px, 1fr); gap: 24px; align-items: start;">
            
            <!-- Левая колонка: Шортсы, Плейлист, Скачивание -->
            <section id="results-panel" class="panel playlist-panel" hidden>
              <div class="panel-heading">
                <h2 id="results-heading" class="panel-title">Готовые шортсы (<span id="parts-count"></span>)</h2>
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

              <div class="shorts-display-row" style="display: flex; gap: 24px; align-items: flex-start; flex-wrap: wrap;">
                <div class="shorts-preview-box" style="width: 180px; flex-shrink: 0; margin: 0;">
                  <video id="player" controls playsinline preload="metadata" loop></video>
                </div>
                <div style="flex: 1; min-width: 220px;">
                  <p class="small muted" style="margin-bottom: 8px; font-weight: 600;">Список фрагментов серии:</p>
                  <div id="playlist" class="playlist-list" style="max-height: 290px; overflow-y: auto;"></div>
                </div>
              </div>

              <div id="part-music-badge" class="badge" hidden style="margin-top: 14px;"></div>

              <div style="display:flex; flex-wrap:wrap; gap:10px; margin-top:18px;">
                <button id="download-video" class="btn-primary" type="button">Скачать видео (.mp4)</button>
                <button id="download-all" class="btn-secondary" type="button">Скачать все шортсы (.mp4)</button>
                <button id="download-subtitle" class="btn-secondary" type="button">Субтитры (.srt)</button>
              </div>
              <p id="download-status" class="muted small" style="margin-top:8px;"></p>
              <p id="player-message" class="message" hidden></p>
            </section>

            <!-- Правая колонка: Контекст нейросети и системный промпт -->
            <section id="part-context" class="panel form-group" hidden>
              <div class="panel-heading" style="margin-bottom:12px;">
                <h3 id="part-context-heading" class="panel-title" style="font-size:15px;">Контекст для ИИ</h3>
              </div>
              <p id="part-context-title" style="font-weight:700; font-size:14px; margin-bottom:4px; color:var(--accent-light);"></p>
              <p id="part-context-synopsis" class="small muted" style="line-height:1.6; margin-bottom:12px;"></p>
              <p id="part-context-fallback" class="small" style="color:var(--danger); margin-bottom:8px;" hidden>Генерация не удалась.</p>
              <details open>
                <summary class="settings-summary" style="font-size:13px;">Системный промпт нейросети</summary>
                <div class="settings-content">
                  <textarea id="part-context-prompt" readonly rows="8" class="form-input" style="font-family:monospace; font-size:11.5px; line-height:1.5;"></textarea>
                  <div style="display:flex; align-items:center; gap:12px;">
                    <button id="copy-part-context" type="button" class="btn-secondary">Копировать промпт</button>
                    <span id="context-copy-status" class="small muted"></span>
                  </div>
                </div>
              </details>
            </section>

          </div>"""

new_results = """          <!-- 3. ПОД НИМ: ГОТОВЫЕ ШОРТСЫ (ВИДЕОПЛЕЕР СЛЕВА, СПИСОК ЧАСТЕЙ СПРАВА) -->
          <section id="results-panel" class="panel playlist-panel" hidden>
            <div class="panel-heading">
              <h2 id="results-heading" class="panel-title">Готовые шортсы (<span id="parts-count"></span>)</h2>
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

            <!-- Двухколоночный просмотрщик: Видеоплеер слева, выбор частей справа -->
            <div class="shorts-viewer-layout">
              <!-- СЛЕВА: Вертикальный плеер 9:16 -->
              <div class="shorts-player-col">
                <div class="shorts-preview-box">
                  <video id="player" controls playsinline preload="metadata" loop></video>
                </div>
                <div id="part-music-badge" class="badge" hidden style="margin-top: 10px; width: 100%; justify-content: center;"></div>
              </div>

              <!-- СПРАВА: Список частей для выбора и кнопки скачивания -->
              <div class="shorts-playlist-col">
                <p class="small muted" style="margin-bottom: 10px; font-weight: 600;">Выберите часть для просмотра:</p>
                <div id="playlist" class="playlist-list" style="max-height: 380px; overflow-y: auto;"></div>
                
                <div style="display:flex; flex-wrap:wrap; gap:10px; margin-top:18px;">
                  <button id="download-video" class="btn-primary" type="button">Скачать видео (.mp4)</button>
                  <button id="download-all" class="btn-secondary" type="button">Скачать все шортсы (.mp4)</button>
                  <button id="download-subtitle" class="btn-secondary" type="button">Субтитры (.srt)</button>
                </div>
                <p id="download-status" class="muted small" style="margin-top:8px;"></p>
                <p id="player-message" class="message" hidden></p>
              </div>
            </div>
          </section>

          <!-- 4. ПОД ШОРТСАМИ: КОНТЕКСТ ДЛЯ ИИ И ПРОМПТ -->
          <section id="part-context" class="panel form-group" hidden>
            <div class="panel-heading" style="margin-bottom:12px;">
              <h3 id="part-context-heading" class="panel-title" style="font-size:15px;">Контекст для ИИ</h3>
            </div>
            <p id="part-context-title" style="font-weight:700; font-size:14px; margin-bottom:4px; color:var(--accent-light);"></p>
            <p id="part-context-synopsis" class="small muted" style="line-height:1.6; margin-bottom:12px;"></p>
            <p id="part-context-fallback" class="small" style="color:var(--danger); margin-bottom:8px;" hidden>Генерация не удалась.</p>
            <details open>
              <summary class="settings-summary" style="font-size:13px;">Системный промпт нейросети</summary>
              <div class="settings-content">
                <textarea id="part-context-prompt" readonly rows="7" class="form-input" style="font-family:monospace; font-size:11.5px; line-height:1.5;"></textarea>
                <div style="display:flex; align-items:center; gap:12px;">
                  <button id="copy-part-context" type="button" class="btn-secondary">Копировать промпт</button>
                  <span id="context-copy-status" class="small muted"></span>
                </div>
              </div>
            </details>
          </section>"""

if old_results in html:
    html = html.replace(old_results, new_results)
    html_path.write_text(html, "utf-8")
    print("index.html replaced successfully")
else:
    print("old_results not matched exactly")
