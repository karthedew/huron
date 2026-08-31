<script lang="ts">
	interface Props {
		kind?: 'note' | 'warn';
		children?: import('svelte').Snippet;
	}
	let { kind = 'note', children }: Props = $props();
</script>

<div class="callout {kind}" role={kind === 'warn' ? 'alert' : undefined}>
	{@render children?.()}
</div>

<style>
	.callout {
		border-left: 4px solid var(--note-line);
		background: var(--note-bg);
		padding: 0.7rem 1rem;
		border-radius: 0 var(--radius) var(--radius) 0;
		margin: 1.2rem 0;
	}
	.warn {
		border-left-color: var(--warn-line);
		background: var(--warn-bg);
	}
</style>
