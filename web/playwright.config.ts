import { defineConfig } from '@playwright/test';

export default defineConfig({
	webServer: {
		command: 'npm run build && npm run preview',
		port: 4173,
		env: { HURON_PREVIEW_SESSION_SECRET: 'e2e-preview-session-secret' },
		reuseExistingServer: !process.env.CI
	},
	testDir: 'e2e',
	use: { baseURL: 'http://localhost:4173' }
});
