import adapter from '@sveltejs/adapter-node';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// A long-running Node server: sessions and their Huron tokens live in its memory.
		adapter: adapter(),
		alias: {
			$design: 'src/lib/design',
			$api: 'src/lib/api'
		},
		csp: {
			mode: 'auto',
			// No form-action: Chromium applies it to the redirect after POST /logout, which
			// continues to the IdP's end_session_endpoint.
			directives: {
				'default-src': ['self'],
				'script-src': ['self'],
				'style-src': ['self', 'unsafe-inline'],
				'img-src': ['self', 'data:'],
				'font-src': ['self'],
				'connect-src': ['self'],
				'object-src': ['none'],
				'base-uri': ['self'],
				'frame-ancestors': ['none']
			}
		}
	}
};

export default config;
