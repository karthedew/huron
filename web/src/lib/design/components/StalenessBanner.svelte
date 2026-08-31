<script lang="ts">
	interface Props {
		reason: string;
	}
	let { reason }: Props = $props();
</script>

<!-- Every stale product wears its badge with the reason — design/frontend.html §1. -->
<div class="stale" role="alert">
	<strong>STALE</strong>
	<span>{reason}</span>
</div>

<style>
	.stale {
		display: flex;
		gap: 0.6rem;
		align-items: baseline;
		flex-wrap: wrap;
		border-left: 4px solid var(--warn-line);
		background: var(--warn-bg);
		padding: 0.7rem 1rem;
		border-radius: 0 var(--radius) var(--radius) 0;
		margin: 1.2rem 0;
	}
	strong {
		color: var(--accent2);
		letter-spacing: 0.06em;
		font-size: 0.78rem;
	}
	span {
		font-size: 0.9rem;
	}
</style>
