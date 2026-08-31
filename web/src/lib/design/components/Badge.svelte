<script lang="ts">
	interface Props {
		tone?: 'neutral' | 'accent' | 'warn' | 'danger' | 'ok';
		title?: string;
		children?: import('svelte').Snippet;
	}
	let { tone = 'neutral', title, children }: Props = $props();
</script>

<span class="badge {tone}" {title}>{@render children?.()}</span>

<style>
	.badge {
		display: inline-block;
		font-size: 0.72rem;
		font-weight: 700;
		letter-spacing: 0.05em;
		padding: 0.05rem 0.5rem;
		border-radius: var(--radius-pill);
		border: 1px solid var(--line);
		color: var(--muted);
		text-transform: uppercase;
		vertical-align: middle;
		white-space: nowrap;
	}
	.accent {
		color: var(--accent);
		border-color: var(--accent);
	}
	.warn {
		color: var(--accent2);
		border-color: var(--warn-line);
		background: var(--warn-bg);
	}
	.danger {
		color: var(--del);
		border-color: var(--del);
	}
	.ok {
		color: var(--accent);
		border-color: var(--note-line);
		background: var(--note-bg);
	}
</style>
