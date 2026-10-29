async page => {
  const origin = 'http://127.0.0.1:4327';
  const base = page.url().startsWith(origin + '/huron-docs/') ? '/huron-docs/' : '/';
  const label = base === '/' ? 'root-settled' : 'subbase-settled';
  const output = '/home/karl/repo/huron/roadmap/prototypes/starlight/evidence/screenshots';
  const indexURL = /\/pagefind\/pagefind-entry\.json(?:\?.*)?$/;
  const errors = [];
  const external = [];
  const onError = error => errors.push(error.message);
  const onConsole = message => { if (message.type() === 'error') errors.push(message.text()); };
  page.on('pageerror', onError);
  page.on('console', onConsole);
  await page.route('**/*', route => {
    if (route.request().url().startsWith(origin + '/')) return route.continue();
    external.push(route.request().url());
    return route.abort('blockedbyclient');
  });
  const open = async () => {
    await page.waitForFunction(() => !document.querySelector('button[data-open-modal]').disabled);
    await page.getByRole('button', { name: 'Search', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Search', exact: true });
    await dialog.getByRole('textbox', { name: 'Search', exact: true }).fill('Controller generation');
    return dialog;
  };
  let release;
  try {
    let requested;
    const started = new Promise(resolve => { requested = resolve; });
    const delayed = new Promise(resolve => { release = resolve; });
    await page.route(indexURL, async route => { requested(); await delayed; await route.continue(); });
    await page.goto(origin + base);
    let dialog = await open();
    await started;
    await dialog.getByText('Searching for Controller generation...', { exact: true }).waitFor();
    if (await dialog.getByRole('link').count()) throw new Error('Delayed search must not fabricate results');
    await page.screenshot({ path: `${output}/cli-${label}-delayed-index.png` });
    release();
    await dialog.locator(`a[href="${base}adr/0001-controller-generation-is-the-verification-epoch/#_top"]`).waitFor();
    if (errors.length) throw new Error('Unexpected normal loading error: ' + errors.join('; '));
    await page.unroute(indexURL);

    let abortObserved;
    let aborted = 0;
    const failed = new Promise(resolve => { abortObserved = resolve; });
    await page.route(indexURL, async route => { aborted++; await route.abort('internetdisconnected'); abortObserved(); });
    const runtimeFailure = page.waitForEvent('pageerror', { predicate: error => /Failed to fetch|undefined|Pagefind/i.test(error.message), timeout: 10_000 });
    await page.reload();
    dialog = await open();
    await failed;
    // Wait on the actual worker-reported failure, not an arbitrary sleep.
    await runtimeFailure;
    await dialog.getByText('Searching for Controller generation...', { exact: true }).waitFor();
    const failedText = await dialog.innerText();
    const visibleFailure = await dialog.getByText(/(unavailable|failed|offline|could not|error)/i).count();
    await page.screenshot({ path: `${output}/cli-${label}-aborted-index.png` });
    await page.unroute(indexURL);
    await dialog.getByRole('textbox', { name: 'Search', exact: true }).fill('pinned base');
    // A complete reload is the observed recovery action, not an invented retry UI.
    await page.reload();
    dialog = await open();
    await dialog.locator(`a[href="${base}adr/0001-controller-generation-is-the-verification-epoch/#_top"]`).waitFor();
    await page.screenshot({ path: `${output}/cli-${label}-recovered-index.png` });
    const injectedErrors = [...errors];
    errors.length = 0;
    await page.keyboard.press('Escape');
    const response = await page.goto(origin + base + 'not-a-real-doc/');
    if (response.status() !== 404) throw new Error('Missing page must return 404');
    await page.getByRole('heading', { level: 1, name: '404' }).waitFor();
    await page.screenshot({ path: `${output}/cli-${label}-404.png` });
    if (external.length) throw new Error('External request attempted');
    return { verdict: visibleFailure ? 'Visible failure observed; inspect full assertions' : 'FAIL: built-in search has no truthful visible index-failure state', browser: page.context().browser().version(), base, delayedLoading: true, aborted, failedText, visibleFailure, recovery: 'Network restored plus full reload returns real results', injectedErrors, notFoundStatus: response.status(), notFoundConsole: errors, external };
  } finally {
    if (release) release();
    await page.unroute(indexURL);
    await page.unroute('**/*');
    page.off('pageerror', onError);
    page.off('console', onConsole);
  }
}
