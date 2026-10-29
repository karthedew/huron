import { defineConfig } from '@playwright/test';

const base = process.env.DOCS_BASE ?? '/';
if (!['/', '/huron-docs/'].includes(base)) throw new Error('Invalid test base');
const run = process.env.DOCS_RUN ?? 'full';
if (!/^[a-z0-9-]+$/.test(run)) throw new Error('Invalid evidence run name');
const outputDir = `./evidence/e2e-${base === '/' ? 'root' : 'subbase'}-${run}`;
export default defineConfig({
  testDir: './e2e',
  outputDir,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: [['list'], ['json', { outputFile: `${outputDir}.json` }]],
  use: {
    browserName: 'chromium',
    baseURL: `http://127.0.0.1:4327${base}`,
    serviceWorkers: 'block',
    permissions: ['clipboard-read', 'clipboard-write'],
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    ...([{ name: 'mobile', width: 390, height: 844 }, { name: 'compact', width: 816, height: 900 }, { name: 'wide', width: 1440, height: 1000 }] as const).flatMap(({ name, width, height }) =>
      (['light', 'dark'] as const).map((colorScheme) => ({ name: `${name}-${colorScheme}`, use: { viewport: { width, height }, colorScheme } }))),
  ],
});
