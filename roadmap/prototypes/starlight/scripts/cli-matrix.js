async page => {
  const origin = 'http://127.0.0.1:4327';
  const base = page.url().startsWith(origin + '/huron-docs/') ? '/huron-docs/' : '/';
  const output = '/home/karl/repo/huron/roadmap/prototypes/starlight/evidence/screenshots';
  const errors = [];
  const external = [];
  const requests = [];
  const require = (condition, message) => { if (!condition) throw new Error(message); };
  const onError = error => errors.push(error.message);
  const onConsole = message => { if (message.type() === 'error') errors.push(message.text()); };
  page.on('pageerror', onError);
  page.on('console', onConsole);
  await page.unroute('**/*');
  await page.route('**/*', route => {
    const url = route.request().url();
    requests.push(url);
    if (url.startsWith(origin + '/')) return route.continue();
    external.push(url);
    return route.abort('blockedbyclient');
  });
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin });
  const tabTo = async locator => {
    for (let i = 0; i < 100; i++) {
      if (await locator.evaluate(element => element === document.activeElement)) return;
      await page.keyboard.press('Tab');
    }
    throw new Error('Control not reachable by Tab');
  };
  const openSearch = async query => {
    await page.getByRole('button', { name: 'Search', exact: true }).waitFor({ state: 'visible' });
    await page.waitForFunction(() => !document.querySelector('button[data-open-modal]').disabled);
    await page.keyboard.press('Control+k');
    const dialog = page.getByRole('dialog', { name: 'Search', exact: true });
    const input = dialog.getByRole('textbox', { name: 'Search', exact: true });
    await input.waitFor({ state: 'visible' });
    await tabTo(input);
    await input.fill(query);
    return dialog;
  };
  const matrix = [];
  try {
    for (const [width, height] of [[390, 844], [816, 900], [1440, 1000]]) {
      for (const theme of ['light', 'dark']) {
        const label = `${base === '/' ? '' : 'subbase-'}${width}-${theme}`;
        await page.setViewportSize({ width, height });
        await page.emulateMedia({ colorScheme: theme });
        await page.goto(origin + base);
        require(await page.locator('html').getAttribute('data-theme') === theme, 'Theme must reflect the emulated system setting');
        await page.keyboard.press('Tab');
        const skip = page.getByRole('link', { name: 'Skip to content', exact: true });
        require(await skip.evaluate(element => element === document.activeElement && getComputedStyle(element).outlineStyle !== 'none'), 'Visible skip-link keyboard focus');
        await page.screenshot({ path: `${output}/cli-${label}-skip.png` });
        await page.keyboard.press('Enter');
        require(page.url() === origin + base + '#_top', 'Skip link reaches main heading');
        const menu = page.getByRole('button', { name: 'Menu', exact: true });
        if (await menu.isVisible()) {
          await tabTo(menu);
          await page.keyboard.press('Enter');
          await page.locator('#starlight__sidebar').waitFor({ state: 'visible' });
          require(await page.locator('#starlight__sidebar').evaluate(element => element.matches(':popover-open')), 'Native navigation popover opens');
          await page.screenshot({ path: `${output}/cli-${label}-navigation.png` });
        }
        const probe = page.getByRole('navigation', { name: 'Main', exact: true }).getByRole('link', { name: 'Rendering probe', exact: true });
        await probe.waitFor({ state: 'visible' });
        await tabTo(probe);
        await page.keyboard.press('Enter');
        await page.waitForURL(origin + base + 'probe/');
        await page.getByRole('heading', { name: 'Rendering probe', exact: true }).waitFor();
        const copy = page.getByRole('button', { name: 'Copy to clipboard', exact: true }).first();
        await copy.scrollIntoViewIfNeeded();
        await tabTo(copy);
        await page.keyboard.press('Enter');
        const clipboard = await page.evaluate(() => navigator.clipboard.readText());
        require(clipboard.includes('payload = {"url": "[not a link](missing.md#absent)"'), 'Copy preserves literal Python braces and link text');
        await page.getByRole('heading', { name: 'Long content', exact: true }).scrollIntoViewIfNeeded();
        const layout = await page.evaluate(() => ({ viewport: innerWidth, page: document.documentElement.scrollWidth, scrollables: Array.from(document.querySelectorAll('table, pre')).map(element => ({ width: element.clientWidth, scroll: element.scrollWidth, overflow: getComputedStyle(element).overflowX })) }));
        require(layout.page <= layout.viewport, 'No horizontal page clipping');
        for (const element of layout.scrollables) if (element.scroll > element.width + 1) require(['auto', 'scroll'].includes(element.overflow), 'Long content has a real scroll container');
        await page.screenshot({ path: `${output}/cli-${label}-long-content.png` });
        let dialog = await openSearch('Controller generation');
        const controller = dialog.locator(`a[href="${base}adr/0001-controller-generation-is-the-verification-epoch/#_top"]`);
        await controller.waitFor({ state: 'visible' });
        await tabTo(controller);
        await page.keyboard.press('Enter');
        await page.waitForURL(origin + base + 'adr/0001-controller-generation-is-the-verification-epoch/#_top');
        dialog = await openSearch('pinned base');
        const metadata = dialog.locator(`a[href="${base}reference/raw-first/#metadata-and-reproducibility"]`);
        await metadata.waitFor({ state: 'visible' });
        await tabTo(metadata);
        require(await metadata.evaluate(element => getComputedStyle(element.parentElement).outlineStyle !== 'none' || getComputedStyle(element).outlineStyle !== 'none' || element === document.activeElement), 'Result has keyboard focus');
        await page.screenshot({ path: `${output}/cli-${label}-search.png` });
        await page.keyboard.press('Enter');
        await page.waitForURL(origin + base + 'reference/raw-first/#metadata-and-reproducibility');
        dialog = await openSearch('zzzz_nonexistent_quasar_7391');
        await dialog.getByText('No results for zzzz_nonexistent_quasar_7391', { exact: true }).waitFor();
        require(await dialog.getByRole('link').count() === 0, 'Empty query result must not fabricate hits');
        await page.keyboard.press('Escape');
        require(!await dialog.isVisible(), 'Escape closes the search dialog');
        matrix.push({ width, height, theme, layout, keyboardQueries: 2, empty: true, copy: true, screenshots: `cli-${label}-*.png` });
      }
    }
    require(errors.length === 0, `Normal console/hydration errors: ${JSON.stringify(errors)}`);
    require(external.length === 0, `External runtime attempts: ${JSON.stringify(external)}`);
    return { verdict: 'PASS for normal named-session matrix only; injected failure remains separate', browser: page.context().browser().version(), matrix, normalErrors: errors, externalRequests: external, localRequests: requests };
  } finally {
    await page.unroute('**/*');
    page.off('pageerror', onError);
    page.off('console', onConsole);
    await page.context().clearPermissions();
  }
}
