<script lang="ts">
	import type { LayerAvailability } from '$api/types';

	interface Props {
		layers: LayerAvailability;
	}
	let { layers }: Props = $props();

	const order = ['raw', 'bronze', 'silver', 'gold'] as const;
</script>

<!--
	Layer availability, per design/frontend.html §2: result cards show raw · bronze · silver · gold.
	A layer that is absent is rendered as absent, never omitted — "what isn't built yet" is
	information a scientist needs.
-->
<ul class="layers" aria-label="Layer availability">
	{#each order as layer}
		{@const state = layers[layer]}
		<li
			class="layer {layer}"
			class:absent={state.state === 'absent'}
			title={state.detail ?? `${layer}: ${state.state}`}
		>
			<span class="name">{layer}</span>
			<span class="mark" aria-hidden="true">
				{#if state.state === 'present'}✓{:else if state.state === 'building'}…{:else}—{/if}
			</span>
			<span class="visually-hidden">{state.state}{state.detail ? `, ${state.detail}` : ''}</span>
		</li>
	{/each}
</ul>

<style>
	.layers {
		display: flex;
		gap: 0.35rem;
		list-style: none;
		margin: 0;
		padding: 0;
		flex-wrap: wrap;
	}
	.layer {
		display: inline-flex;
		align-items: baseline;
		gap: 0.3rem;
		font-size: 0.72rem;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		padding: 0.05rem 0.5rem;
		border-radius: var(--radius-pill);
		border: 1px solid currentColor;
	}
	.raw {
		color: var(--raw);
	}
	.bronze {
		color: var(--bronze);
	}
	.silver {
		color: var(--silver);
	}
	.gold {
		color: var(--gold);
	}
	.absent {
		color: var(--muted);
		border-color: var(--line);
		opacity: 0.7;
	}
	.mark {
		font-weight: 400;
	}
</style>
