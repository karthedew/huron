<script lang="ts">
	import type { Lifecycle } from '$api/types';

	interface Props {
		state: Lifecycle;
	}
	let { state }: Props = $props();
</script>

<span class="chip {state.toLowerCase()}">{state}</span>

<style>
	.chip {
		display: inline-block;
		font-size: 0.7rem;
		font-weight: 700;
		letter-spacing: 0.06em;
		padding: 0.1rem 0.5rem;
		border-radius: var(--radius-sm);
		border: 1px solid var(--line);
		color: var(--muted);
	}
	.draft {
		color: var(--accent2);
		background: var(--warn-bg);
		border-color: var(--warn-line);
	}
	.active {
		color: var(--accent);
		background: var(--note-bg);
		border-color: var(--note-line);
	}
	.retired {
		text-decoration: line-through;
	}
</style>
