<script lang="ts">
	import Breadcrumbs from '$design/components/Breadcrumbs.svelte';
	import LifecycleChip from '$design/components/LifecycleChip.svelte';
	import Badge from '$design/components/Badge.svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	const base = $derived(
		`/${data.dataset.orgSlug}/${data.dataset.projectSlug}/${data.dataset.slug}`
	);
</script>

<svelte:head><title>{data.dataset.name} · Huron</title></svelte:head>

<Breadcrumbs
	crumbs={[
		{ label: 'Browse', href: '/browse' },
		{ label: data.dataset.orgSlug, href: `/${data.dataset.orgSlug}` },
		{
			label: data.dataset.projectSlug,
			href: `/${data.dataset.orgSlug}/${data.dataset.projectSlug}`
		},
		{ label: data.dataset.name, href: base }
	]}
/>

<div class="title">
	<h1>{data.dataset.name}</h1>
	<LifecycleChip state={data.dataset.lifecycle} />
</div>
<p class="muted">{data.dataset.description}</p>

<p class="meta">
	<Badge>{data.dataset.classification}</Badge>
	<Badge tone="accent">{data.dataset.profile}</Badge>
	{#each data.dataset.tags as tag (tag)}<Badge>{tag}</Badge>{/each}
</p>

<h2>Canonical contract</h2>
<p class="muted">Variables, dims, units, and version history. Not built (P7).</p>

<h2>Open in Python</h2>
<pre><code
		>import huron

ds = huron.open_dataset("{base.slice(1)}")  # pinned to the latest snapshot</code
	></pre>
<p class="muted">
	The deliberate hand-off: no in-browser array rendering, which would require broad storage
	credentials in the browser. The client package ships at P8.
</p>

<h2>Validation history</h2>
<p class="muted">Pass/fail sparkline with structured findings. Not built (P6).</p>

<h2>Retention and holds</h2>
<p class="muted">Per-category TTL, pins, legal holds. Not built (P5).</p>

<style>
	.title {
		display: flex;
		gap: 0.7rem;
		align-items: baseline;
		flex-wrap: wrap;
	}
	.meta {
		display: flex;
		gap: 0.4rem;
		flex-wrap: wrap;
		margin: 0.8rem 0 0;
	}
</style>
