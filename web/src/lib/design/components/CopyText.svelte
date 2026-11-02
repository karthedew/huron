<script lang="ts">
	import { Copy } from '@lucide/svelte';
	import { Clipboard } from './clipboard.svelte';

	interface Props {
		/** What the value is, e.g. "share path"; it names the copy button. */
		label: string;
		value: string;
		/** What to show of a long value, e.g. the end of an id; the whole value is its title. */
		shown?: string;
	}

	let { label, value, shown }: Props = $props();

	/** Without a clipboard (an insecure origin), and until mounted, the text alone shows. */
	const clipboard = new Clipboard();
	/**
	 * The text in parts that each end in a `/`: a path then breaks after one, between its
	 * segments, as browsers offer no break there themselves. A segment too long on its own still
	 * breaks anywhere.
	 */
	const parts = $derived((shown ?? value).split(/(?<=\/)/));
</script>

<span class="inline-flex max-w-full min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
	<!-- In their order and not keyed: two segments may read alike. -->
	<code class="min-w-0 wrap-anywhere text-app-fg" title={shown === undefined ? undefined : value}
		>{#each parts as part, index}{#if index > 0}<wbr />{/if}{part}{/each}</code
	>
	{#if clipboard.available}
		<button
			type="button"
			onclick={() => clipboard.copy(value, "Couldn't copy; select the text instead.")}
			aria-label="Copy {label}"
			title="Copy {label}"
			class="inline-grid size-7 shrink-0 place-items-center rounded-md border border-app-line bg-app-card text-app-muted hover:border-app-line-strong hover:text-app-fg"
			><Copy size={14} aria-hidden="true" /></button
		>
	{/if}
	<!-- Always rendered, so screen readers know the live region before it speaks. -->
	<span role="status" class="text-xs font-semibold text-brand-strong">{clipboard.status}</span>
</span>
