# KADR Studio frontend

Единственный интерфейс — `public/studio-edition.html`, `studio-edition.css`, `studio-edition-app.js` и `studio-live-bridge.js`. Данные поступают из FastAPI; при недоступном сервере показывается ошибка подключения, вымышленные проекты и результаты не создаются.

`npm run build` вызывает `scripts/build-studio.mjs`: проверяет синтаксис JavaScript, копирует Studio в `dist` и удаляет устаревшие продукты frontend-сборки только внутри `dist`. Для сборки достаточно portable Node в `../tools/node`; React, Vite и TypeScript не используются. `npm run dev` следит за изменениями `public` и пересобирает ту же Studio; HTTP предоставляет основной backend на `127.0.0.1:8765`.

Из корня проекта:

```powershell
& tools/node/node.exe frontend/scripts/build-studio.mjs
& tools/node/node.exe frontend/scripts/check-studio.mjs --lint
& tools/node/node.exe frontend/scripts/check-studio.mjs
```

Последняя команда выполняет две проверки Studio в jsdom. Если тестовые зависимости отсутствуют, установите их проектным `scripts/npm.cmd ci --prefix frontend --no-audit --no-fund`. Это единственная dev-зависимость; она не нужна для работы приложения или сборки.

API-адаптер `studio-live-bridge.js` отвечает за запросы, нормализацию и загрузку реальных записей. `studio-edition-app.js` отвечает за экраны, действия пользователя и воспроизведение. Backend-маршруты Studio принадлежат `app/studio_routes.py`. Удалённые `/legacy`, `/react-debug` и reference HTML возвращают 404. Подробная карта: [docs/audit/architecture.md](../docs/audit/architecture.md).
