import { createHash } from 'node:crypto';
import { lstatSync, readFileSync, readdirSync } from 'node:fs';
import { resolve, relative, sep } from 'node:path';

export const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
export const json = (value) => JSON.stringify(value, null, 2) + '\n';

export function inside(root, name) {
  const path = resolve(root, name);
  const rel = relative(resolve(root), path);
  if (rel === '..' || rel.startsWith(`..${sep}`) || rel.startsWith(sep)) throw new Error(`Path escape: ${name}`);
  return path;
}

export function noSymlinks(root, name, missing = false) {
  const path = inside(root, name);
  let current = resolve(root);
  for (const part of ['', ...relative(current, path).split(sep).filter(Boolean)]) {
    current = resolve(current, part);
    try {
      if (lstatSync(current).isSymbolicLink()) throw new Error(`Symlink refused: ${current}`);
    } catch (error) {
      if (missing && error.code === 'ENOENT') continue;
      throw error;
    }
  }
  return path;
}

export function regular(root, name) {
  const path = noSymlinks(root, name);
  if (!lstatSync(path).isFile()) throw new Error(`Not a regular input: ${name}`);
  return readFileSync(path);
}

export function inventory(root) {
  const entries = {};
  function walk(dir) {
    for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name, 'en'))) {
      const path = noSymlinks(root, relative(root, resolve(dir, entry.name)));
      if (entry.isDirectory()) walk(path);
      else if (entry.isFile()) entries[relative(root, path).split(sep).join('/')] = sha256(readFileSync(path));
      else throw new Error(`Unknown output type: ${path}`);
    }
  }
  walk(root);
  return entries;
}
