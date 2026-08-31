<script lang="ts">
	import { page } from '$app/state';
	import EmptyState from '$design/components/EmptyState.svelte';
</script>

<svelte:head><title>Snapshot · Huron</title></svelte:head>

<h1>Snapshot <span class="mono muted">{page.params.id}</span></h1>

<h2>Provenance</h2>
<p class="muted">
	The exact revision and extractor digest this snapshot came from. Not built (P6).
</p>

<h2>Open in Python</h2>
<pre><code
		>import huron

ds = huron.open_snapshot("{page.params.id}")  # pinned — reproduces byte-identically</code
	></pre>

<h2>Lineage</h2>
<EmptyState title="Lineage mini-graph not built" detail="Arrives with the lineage API (P9)." />
