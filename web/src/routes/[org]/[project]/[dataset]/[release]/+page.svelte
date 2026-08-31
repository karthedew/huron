<script lang="ts">
	import Breadcrumbs from '$design/components/Breadcrumbs.svelte';
	import DataTable from '$design/components/DataTable.svelte';
	import LayerBadges from '$design/components/LayerBadges.svelte';
	import Badge from '$design/components/Badge.svelte';
	import Callout from '$design/components/Callout.svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	const r = $derived(data.release);
	const base = $derived(`/${r.orgSlug}/${r.projectSlug}/${r.datasetSlug}/${r.slug}`);
</script>

<svelte:head><title>{r.slug} · Huron</title></svelte:head>

<Breadcrumbs
	crumbs={[
		{ label: 'Browse', href: '/browse' },
		{ label: r.orgSlug, href: `/${r.orgSlug}` },
		{ label: r.projectSlug, href: `/${r.orgSlug}/${r.projectSlug}` },
		{ label: r.datasetSlug, href: `/${r.orgSlug}/${r.projectSlug}/${r.datasetSlug}` },
		{ label: r.slug, href: base }
	]}
/>

<div class="title">
	<h1>{r.slug}</h1>
	{#if r.sealed}<Badge tone="ok">sealed</Badge>{:else}<Badge tone="warn">unsealed</Badge>{/if}
</div>
<LayerBadges layers={r.layers} />

<h2>Revisions</h2>
<DataTable
	caption="Newest first. A revision is a full logical copy — corrections never mutate history."
>
	{#snippet head()}
		<tr><th>Rev</th><th>Reason</th><th>Created</th><th>Files</th><th></th></tr>
	{/snippet}
	{#each data.revisions as rev}
		<tr>
			<td class="mono">{rev.number}</td>
			<td>{rev.reason}</td>
			<td class="mono">{rev.createdAt.slice(0, 10)}</td>
			<td>{rev.fileCount}</td>
			<td><a href="{base}/{rev.number}">Manifest →</a></td>
		</tr>
	{/each}
</DataTable>

<h2>Upload a corrected revision</h2>
<Callout>
	Corrections are a client operation, not a browser upload — the UI explains and hands off:
	<pre><code>huron revision create {base.slice(1)} --reason "…"</code></pre>
	Downstream impact (new Bronze → Silver region replace → stale products) renders here once the pipelines
	exist.
</Callout>

<style>
	.title {
		display: flex;
		gap: 0.7rem;
		align-items: baseline;
		flex-wrap: wrap;
	}
</style>
