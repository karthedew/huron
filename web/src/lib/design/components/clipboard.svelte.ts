import { onMount } from 'svelte';

/** How long the status of a copy stays before it clears, in milliseconds. */
const STATUS_MS = 4000;

/**
 * Copying text from a component: whether the browser offers the clipboard, and what the last
 * copy said. Construct it while the component initializes: it learns of the clipboard once
 * mounted, so the server and a browser without scripts never offer to copy, and it clears its
 * timer when the component goes.
 */
export class Clipboard {
	/**
	 * `null` until mounted, then whether the browser can write text to the clipboard: it cannot
	 * on an insecure origin, such as plain http other than loopback.
	 */
	available = $state<boolean | null>(null);
	/** "Copied", or why copying failed, for a live region; empty again after a few seconds. */
	status = $state('');
	#reset: ReturnType<typeof setTimeout> | undefined;

	constructor() {
		onMount(() => {
			this.available = typeof navigator.clipboard?.writeText === 'function';
			return () => clearTimeout(this.#reset);
		});
	}

	/** Copy `text`; `failure` is what the status says when the browser refuses. */
	copy = async (text: string, failure: string): Promise<void> => {
		clearTimeout(this.#reset);
		try {
			await navigator.clipboard.writeText(text);
			this.status = 'Copied';
		} catch {
			this.status = failure;
		}
		this.#reset = setTimeout(() => (this.status = ''), STATUS_MS);
	};
}
