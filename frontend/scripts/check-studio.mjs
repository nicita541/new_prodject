import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const lint = process.argv.includes("--lint");
const targets = lint
  ? [
      "public/studio-edition-app.js",
      "public/studio-live-bridge.js",
      "scripts/build-studio.mjs",
    ]
  : ["scripts/smoke-studio-bridge.mjs", "scripts/smoke-studio-exact.mjs"];
for (const target of targets) {
  const path = fileURLToPath(new URL("../" + target, import.meta.url));
  const result = spawnSync(
    process.execPath,
    lint ? ["--check", path] : [path],
    { stdio: "inherit" },
  );
  if (result.status !== 0) process.exit(result.status || 1);
}
