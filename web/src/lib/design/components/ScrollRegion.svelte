<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		/** What scrolls, e.g. "Fields of the catalog's schema". */
		label: string;
		children: Snippet;
	}

	let { label, children }: Props = $props();
</script>

<!--
	Content wider than the screen scrolls here, never the page. Keyboard users scroll it once it
	has focus, so the region takes focus although it is no control (WCAG 2.1.1; the scrollable-
	region rule of accessibility checkers). Svelte's tabindex rule does not know that exception.
-->
<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div
	role="region"
	aria-label={label}
	tabindex="0"
	class="overflow-x-auto rounded-card border border-app-line bg-app-card"
>
	{@render children()}
</div>
