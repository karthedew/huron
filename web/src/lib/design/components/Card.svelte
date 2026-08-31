<script lang="ts">
	interface Props {
		href?: string;
		children?: import('svelte').Snippet;
	}
	let { href, children }: Props = $props();
</script>

{#if href}
	<a class="card link" {href}>{@render children?.()}</a>
{:else}
	<div class="card">{@render children?.()}</div>
{/if}

<style>
	.card {
		display: block;
		border: 1px solid var(--line);
		background: var(--card);
		border-radius: 10px;
		padding: 0.9rem 1rem;
	}
	.link {
		text-decoration: none;
		color: inherit;
	}
	.link:hover {
		border-color: var(--accent);
	}
</style>
