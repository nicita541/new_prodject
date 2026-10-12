import { copyFileSync, existsSync, lstatSync, mkdirSync, readdirSync, realpathSync, renameSync, rmSync, watch } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, sep } from 'node:path';
import { spawnSync } from 'node:child_process';

const frontend = fileURLToPath(new URL('..', import.meta.url));
const dist = resolve(frontend, 'dist');
const files = ['studio-edition.html', 'studio-edition.css', 'studio-edition-app.js', 'studio-live-bridge.js', 'favicon.svg'];
function build() {
  for (const file of files.filter(name => name.endsWith('.js'))) {
    const result = spawnSync(process.execPath, ['--check', resolve(frontend, 'public', file)], { stdio: 'inherit' });
    if (result.status !== 0) throw new Error('Studio JavaScript syntax check failed');
  }
  if (existsSync(dist) && lstatSync(dist).isSymbolicLink()) throw new Error('dist must not be a symlink');
  mkdirSync(dist, { recursive: true });
  for (const file of files) {
    const pending = resolve(dist, file + '.pending');
    copyFileSync(resolve(frontend, 'public', file), pending);
    renameSync(pending, resolve(dist, file));
  }
  // Only obsolete frontend build products; never touch jobs or source media.
  for (const name of readdirSync(dist)) {
    if (files.includes(name)) continue;
    const target = resolve(dist, name);
    if (lstatSync(target).isSymbolicLink() || !realpathSync(target).startsWith(realpathSync(dist) + sep)) {
      throw new Error('Unexpected path outside Studio build directory');
    }
    rmSync(target, { recursive: true });
  }
  console.log('Studio built: ' + files.join(', '));
}
build();
if (process.argv.includes('--watch')) {
  let timer;
  watch(resolve(frontend, 'public'), () => { clearTimeout(timer); timer = setTimeout(build, 100); });
}
