import { test as setup } from '@playwright/test';
import { seed } from './support/seed.mjs';
import { stack } from './support/harness.ts';

setup('seed the fixture through the API', async () => {
	setup.setTimeout(120_000);
	await seed({ apiUrl: stack.apiUrl, issuer: stack.issuer });
});
