import adapter from '@sveltejs/adapter-node';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// Node adapter: the UI is server-rendered (design/frontend.html §1) and deployed
		// alongside the API, not on a serverless platform.
		adapter: adapter(),
		alias: {
			$design: 'src/lib/design',
			$api: 'src/lib/api'
		}
	}
};

export default config;
