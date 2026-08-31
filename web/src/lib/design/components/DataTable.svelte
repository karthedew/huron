<script lang="ts">
	interface Props {
		caption?: string;
		head?: import('svelte').Snippet;
		children?: import('svelte').Snippet;
	}
	let { caption, head, children }: Props = $props();
</script>

<!--
	Plain semantic table. Virtualization for 10k-row manifests and audit streams is a
	UI-β concern (design/frontend.html §4) and deliberately not faked here.
-->
<div class="scroll">
	<table>
		{#if caption}<caption>{caption}</caption>{/if}
		{#if head}<thead>{@render head()}</thead>{/if}
		<tbody>{@render children?.()}</tbody>
	</table>
</div>

<style>
	.scroll {
		overflow-x: auto;
	}
	table {
		border-collapse: collapse;
		width: 100%;
		margin: 1rem 0;
		font-size: 0.92rem;
	}
	caption {
		text-align: left;
		color: var(--muted);
		font-size: 0.85rem;
		padding-bottom: 0.4rem;
	}
	:global(th),
	:global(td) {
		border: 1px solid var(--line);
		padding: 0.45rem 0.6rem;
		text-align: left;
		vertical-align: top;
	}
	:global(th) {
		background: var(--code-bg);
	}
</style>
