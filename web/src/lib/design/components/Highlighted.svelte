<script lang="ts">
	import { highlight } from '$lib/search';

	interface Props {
		text: string;
		/** The search text; what it matches is marked. */
		q: string;
	}

	let { text, q }: Props = $props();

	const parts = $derived(highlight(text, q));
</script>

<!--
	The parts of one text, in order; two may be alike. The match keeps the text's own color, which
	reads on the mark in both themes where that color is the foreground (see `--mark`).
-->
{#each parts as part}
	{#if part.match}
		<mark class="rounded-xs bg-app-mark box-decoration-clone text-inherit">{part.text}</mark>
	{:else}
		{part.text}
	{/if}
{/each}
