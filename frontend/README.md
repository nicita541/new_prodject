# KADR Studio frontend

`public/studio-edition.html`, its CSS/application script and `studio-live-bridge.js` provide the main studio served by FastAPI. Vite copies these files into `dist` during the build. `studio-edition-reference.html` is the visual reference used by CI. React source under `src` remains available through `/react-debug`; the older static interface is served through `/legacy`.

Use the portable Node runtime in `../tools/node`. Run from this directory:

```powershell
$env:PATH = (Resolve-Path ../tools/node).Path + ';' + $env:PATH
$env:npm_config_cache = (Resolve-Path ../cache).Path + '/npm'
$npmCli = '../tools/node/node_modules/npm/bin/npm-cli.js'
& ../tools/node/node.exe $npmCli test
& ../tools/node/node.exe $npmCli run lint
& ../tools/node/node.exe $npmCli run build
```

`npm run dev` starts the React development server. Its `/api` proxy uses `127.0.0.1:8765`, configurable through `KADR_STUDIO_API_PORT`. Start the backend through the root launcher.

The standalone Studio checks run from the repository root:

```powershell
& tools/node/node.exe frontend/scripts/smoke-studio-exact.mjs
& tools/node/node.exe frontend/scripts/smoke-studio-bridge.mjs
```

For full project verification, see [ТЕСТЫ/README.md](../ТЕСТЫ/README.md). Keep all dependencies, generated files and caches inside the project.
