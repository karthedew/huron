import { readFileSync, existsSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

const lockBytes = readFileSync('package-lock.json');
const lock = JSON.parse(lockBytes);
const lifecycle = [];
for (const path of Object.keys(lock.packages).filter(Boolean).sort()) {
  if (!existsSync(`${path}/package.json`)) continue;
  const pkg = JSON.parse(readFileSync(`${path}/package.json`, 'utf8'));
  const scripts = Object.fromEntries(Object.entries(pkg.scripts ?? {}).filter(([name]) => ['preinstall', 'install', 'postinstall', 'prepare'].includes(name)));
  if (Object.keys(scripts).length || lock.packages[path].hasInstallScript) lifecycle.push({ path, version: pkg.version, scripts });
}
const roots = { ...lock.packages[''].dependencies, ...lock.packages[''].devDependencies };
const result = {
  node: process.version,
  lockSha256: createHash('sha256').update(lockBytes).digest('hex'),
  lockPackages: Object.keys(lock.packages).length - 1,
  roots: Object.fromEntries(Object.keys(roots).sort().map((name) => [name, {
    version: lock.packages[`node_modules/${name}`].version,
    integrity: lock.packages[`node_modules/${name}`].integrity,
  }])), lifecycle,
  exports: { docsLoader: typeof docsLoader, docsSchema: typeof docsSchema, loader: docsLoader().name },
};
console.log(JSON.stringify(result, null, 2));
if (process.argv.includes('--save')) writeFileSync('evidence/package-proof.json', JSON.stringify(result, null, 2) + '\n');
