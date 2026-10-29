import { test as baseTest, expect, type Page, type Locator } from '@playwright/test';

const base = process.env.DOCS_BASE ?? '/';
const origin = 'http://127.0.0.1:4327';
const adr = `${base}adr/0001-controller-generation-is-the-verification-epoch/`;
const raw = `${base}reference/raw-first/`;

type Evidence = { browserVersion: string; requests: string[]; external: string[]; errors: string[] };
const test = baseTest.extend<{ evidence: Evidence }>({
  evidence: async ({ page, context }, use, testInfo) => {
    const evidence: Evidence = { browserVersion: context.browser()?.version() ?? 'unknown', requests: [], external: [], errors: [] };
    await context.route('**/*', async (route) => {
      const url = route.request().url();
      evidence.requests.push(url);
      if (new URL(url).origin === origin) await route.continue();
      else { evidence.external.push(url); await route.abort('blockedbyclient'); }
    });
    page.on('pageerror', (error) => evidence.errors.push(`page: ${error.message}`));
    page.on('console', (message) => { if (message.type() === 'error') evidence.errors.push(`console: ${message.text()}`); });
    await use(evidence);
    await testInfo.attach('network-and-console', { body: JSON.stringify(evidence, null, 2), contentType: 'application/json' });
    expect(evidence.external, 'No external runtime request, including blocked attempts').toEqual([]);
    await context.unroute('**/*');
  },
});

async function tabTo(page: Page, locator: Locator) {
  for (let i = 0; i < 100; i++) {
    if (await locator.evaluate((element) => element === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  await expect(locator, 'Control must be reachable with Tab').toBeFocused();
}

async function search(page: Page, query: string) {
  await page.getByRole('button', { name: 'Search', exact: true }).waitFor({ state: 'visible' });
  await expect(page.getByRole('button', { name: 'Search', exact: true })).toBeEnabled();
  await page.keyboard.press('Control+k');
  const dialog = page.getByRole('dialog', { name: 'Search', exact: true });
  await expect(dialog).toBeVisible();
  const input = dialog.getByRole('textbox', { name: 'Search', exact: true });
  await expect(input).toBeVisible();
  // If the idle-loaded input appears after opening, Tab must still reach it.
  await tabTo(page, input);
  await input.fill(query);
  return dialog;
}

test('Built local search supports keyboard page and section activation and honest empty results', async ({ page, evidence }) => {
  await page.goto(base);
  let dialog = await search(page, 'Controller generation');
  const controller = dialog.locator(`a[href="${adr}#_top"]`);
  await expect(controller).toBeVisible();
  await tabTo(page, controller);
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(origin + adr + '#_top');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Controller generation is the verification epoch');
  dialog = await search(page, 'pinned base');
  const section = dialog.locator(`a[href="${raw}#metadata-and-reproducibility"]`);
  await expect(section).toBeVisible();
  await tabTo(page, section);
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(origin + raw + '#metadata-and-reproducibility');
  await expect(page.getByRole('heading', { name: 'Metadata and reproducibility', exact: true })).toBeInViewport();
  dialog = await search(page, 'zzzz_nonexistent_quasar_7391');
  await expect(dialog.getByText('No results for zzzz_nonexistent_quasar_7391', { exact: true })).toBeVisible();
  await expect(dialog.getByRole('link')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  expect(evidence.errors).toEqual([]);
});

test('Theme, skip link, navigation, copying and long content remain usable without viewport overflow', async ({ page, evidence }, testInfo) => {
  await page.goto(base);
  await expect(page.locator('html')).toHaveAttribute('data-theme', testInfo.project.use.colorScheme as string);
  await page.keyboard.press('Tab');
  const skip = page.getByRole('link', { name: 'Skip to content', exact: true });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  expect(await skip.evaluate((element) => getComputedStyle(element).outlineStyle)).not.toBe('none');
  await page.screenshot({ path: testInfo.outputPath('skip-focus.png') });
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(origin + base + '#_top');
  const menu = page.getByRole('button', { name: 'Menu', exact: true });
  if (await menu.isVisible()) {
    await tabTo(page, menu);
    await page.keyboard.press('Enter');
    await expect(page.locator('#starlight__sidebar')).toBeVisible();
  }
  const nav = page.getByRole('navigation', { name: 'Main', exact: true });
  const probe = nav.getByRole('link', { name: 'Rendering probe', exact: true });
  await expect(probe).toBeVisible();
  await tabTo(page, probe);
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(origin + base + 'probe/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Rendering probe');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole('complementary', { name: 'Read-only example', exact: true })).toBeVisible();
  const copy = page.getByRole('button', { name: 'Copy to clipboard', exact: true }).first();
  await copy.scrollIntoViewIfNeeded();
  await tabTo(page, copy);
  await page.keyboard.press('Enter');
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain('payload = {"url": "[not a link](missing.md#absent)"');
  await page.getByRole('heading', { name: 'Long content', exact: true }).scrollIntoViewIfNeeded();
  const dimensions = await page.locator('table, pre').evaluateAll((elements) => elements.map((element) => ({ width: element.clientWidth, scroll: element.scrollWidth, overflow: getComputedStyle(element).overflowX })));
  for (const element of dimensions) if (element.scroll > element.width + 1) expect(['auto', 'scroll']).toContain(element.overflow);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('long-content.png') });
  const dialog = await search(page, 'pinned base');
  await expect(dialog.locator(`a[href="${raw}#metadata-and-reproducibility"]`)).toBeVisible();
  for (let i = 0; i < 25; i++) {
    await page.keyboard.press('Tab');
    const focus = await page.evaluate(() => ({ inside: !!document.activeElement?.closest('dialog'), documentFocus: document.hasFocus() }));
    if (!focus.inside) {
      expect(focus.documentFocus, 'Background page controls must never receive modal focus').toBe(false);
      await page.keyboard.press('Tab');
      const firstControl = (page.viewportSize()?.width ?? 0) < 800
        ? dialog.getByRole('button', { name: 'Cancel', exact: true })
        : dialog.getByRole('textbox', { name: 'Search', exact: true });
      await expect(firstControl, 'Tab from browser chrome returns to the first visible modal control').toBeFocused();
    }
  }
  await page.screenshot({ path: testInfo.outputPath('search.png') });
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(copy, 'Escape restores the pre-dialog keyboard focus').toBeFocused();
  expect(evidence.errors).toEqual([]);
});

test('A delayed search index exposes loading and then real results', async ({ page, evidence }, testInfo) => {
  let release!: () => void;
  const delayed = new Promise<void>((resolve) => { release = resolve; });
  let requested!: () => void;
  const started = new Promise<void>((resolve) => { requested = resolve; });
  const indexURL = /\/pagefind\/pagefind-entry\.json(?:\?.*)?$/;
  await page.route(indexURL, async (route) => { requested(); await delayed; await route.continue(); });
  try {
    await page.goto(base);
    const dialog = await search(page, 'Controller generation');
    await started;
    await expect(dialog.getByText('Searching for Controller generation...', { exact: true })).toBeVisible();
    await expect(dialog.getByRole('link')).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath('search-loading.png') });
    release();
    await expect(dialog.locator(`a[href="${adr}#_top"]`)).toBeVisible();
    expect(evidence.errors).toEqual([]);
  } finally {
    release();
    await page.unroute(indexURL);
  }
});

test('An aborted search index shows a truthful failure and recovers after network restoration', async ({ page, evidence }, testInfo) => {
  let aborted = 0;
  const indexURL = /\/pagefind\/pagefind-entry\.json(?:\?.*)?$/;
  await page.route(indexURL, async (route) => { aborted++; await route.abort('internetdisconnected'); });
  await page.goto(base);
  const dialog = await search(page, 'Controller generation');
  await expect.poll(() => aborted).toBeGreaterThan(0);
  await expect.soft(dialog.getByText(/(unavailable|failed|offline|could not|error)/i), 'Index failure must be visible, not an endless loading message').toBeVisible({ timeout: 2_000 });
  await expect.soft(dialog.getByText('Searching for Controller generation...', { exact: true }), 'Failed search must leave loading').toHaveCount(0, { timeout: 2_000 });
  await page.screenshot({ path: testInfo.outputPath('search-aborted.png') });
  await testInfo.attach('injected-index-failure', { body: JSON.stringify({ aborted, text: await dialog.innerText(), errors: evidence.errors }, null, 2), contentType: 'application/json' });
  await page.unroute(indexURL);
  await page.reload();
  const recovered = await search(page, 'Controller generation');
  await expect(recovered.locator(`a[href="${adr}#_top"]`)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('search-recovered.png') });
});

test('A missing page returns a real 404 rather than a false content success', async ({ page, evidence }, testInfo) => {
  const response = await page.goto(`${base}not-a-real-doc/`);
  expect(response?.status()).toBe(404);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('404');
  await expect(page.getByText(/couldn.t find|not found|doesn.t exist/i).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('not-found.png') });
  expect(evidence.errors.filter((message) => !message.startsWith('console: Failed to load resource: the server responded with a status of 404'))).toEqual([]);
});
