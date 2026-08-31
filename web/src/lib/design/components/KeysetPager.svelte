<script lang="ts">
	interface Props {
		nextCursor?: string | null;
		prevCursor?: string | null;
		basePath: string;
	}
	let { nextCursor = null, prevCursor = null, basePath }: Props = $props();
</script>

<!--
	Keyset pagination end-to-end (design/frontend.html §4) — cursors are opaque and
	versioned; the UI never constructs offsets of its own.
-->
<nav class="pager" aria-label="Pagination">
	{#if prevCursor}
		<a href="{basePath}?cursor={encodeURIComponent(prevCursor)}">← Previous</a>
	{:else}
		<span class="muted">← Previous</span>
	{/if}
	{#if nextCursor}
		<a href="{basePath}?cursor={encodeURIComponent(nextCursor)}">Next →</a>
	{:else}
		<span class="muted">Next →</span>
	{/if}
</nav>

<style>
	.pager {
		display: flex;
		gap: 1.2rem;
		justify-content: space-between;
		margin: 1.4rem 0;
		font-size: 0.9rem;
		border-top: 1px solid var(--line);
		padding-top: 0.8rem;
	}
</style>
