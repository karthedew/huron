<script lang="ts">
	import { page } from '$app/state';
	import StalenessBanner from '$design/components/StalenessBanner.svelte';
	import EmptyState from '$design/components/EmptyState.svelte';
</script>

<svelte:head><title>Product · Huron</title></svelte:head>

<h1>Product <span class="mono muted">{page.params.id}</span></h1>

<StalenessBanner reason="upstream revision corrected — recompute pending (fixture)" />

<h2>Derivation record</h2>
<p class="muted">
	Inputs, transform digest, parameters — the record that alone re-executes to a bit-identical output
	(invariant K). Not built (P9).
</p>

<h2>Lineage</h2>
<EmptyState
	title="Lineage graph not built"
	detail="Rendered client-side from /lineage, depth-limited with expand-on-demand; redacted nodes render as locked rather than vanishing. UI-β, after P9."
/>

<h2>Validation evidence</h2>
<p class="muted">Structured pass/fail with details. Not built (P6).</p>
