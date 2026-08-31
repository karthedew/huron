<script lang="ts">
	import Breadcrumbs from '$design/components/Breadcrumbs.svelte';
	import DataTable from '$design/components/DataTable.svelte';
	import LayerBadges from '$design/components/LayerBadges.svelte';
	import LifecycleChip from '$design/components/LifecycleChip.svelte';
	import Badge from '$design/components/Badge.svelte';
	import EmptyState from '$design/components/EmptyState.svelte';
	import Callout from '$design/components/Callout.svelte';
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
	{#each data.dataset.tags as tag}<Badge>{tag}</Badge>{/each}
</p>

{#if data.dataset.lifecycle === 'DRAFT'}
	<Callout kind="warn">
		This dataset is a <strong>DRAFT</strong>. A steward must complete the activation checklist —
		identity, kind, ownership, contract, retention, classification, duplication — before it accepts
		ingest. The checklist UI is P5 work.
	</Callout>
{/if}

<h2>Releases</h2>
{#if data.releases.length === 0}
	<EmptyState title="No releases" detail="Nothing has been ingested into this dataset yet." />
{:else}
	<DataTable caption="Per-release materialization state across the four layers.">
		{#snippet head()}
			<tr><th>Release</th><th>Created</th><th>Revisions</th><th>Layers</th><th>Sealed</th></tr>
		{/snippet}
		{#each data.releases as release}
			<tr>
				<td><a href="{base}/{release.slug}">{release.slug}</a></td>
				<td class="mono">{release.createdAt.slice(0, 10)}</td>
				<td>{release.revisionCount}</td>
				<td><LayerBadges layers={release.layers} /></td>
				<td>{release.sealed ? 'yes' : 'no'}</td>
			</tr>
		{/each}
	</DataTable>
{/if}

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
