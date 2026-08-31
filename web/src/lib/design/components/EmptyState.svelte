<script lang="ts">
	interface Props {
		title: string;
		detail?: string;
		children?: import('svelte').Snippet;
	}
	let { title, detail, children }: Props = $props();
</script>

<div class="empty">
	<p class="title">{title}</p>
	{#if detail}<p class="detail">{detail}</p>{/if}
	{@render children?.()}
</div>

<style>
	.empty {
		border: 1px dashed var(--line);
		border-radius: var(--radius);
		padding: 2rem 1.5rem;
		text-align: center;
		color: var(--muted);
	}
	.title {
		margin: 0 0 0.3rem;
		font-weight: 600;
		color: var(--fg);
	}
	.detail {
		margin: 0;
		font-size: 0.9rem;
	}
</style>
