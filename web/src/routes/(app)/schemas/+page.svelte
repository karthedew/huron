<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { FileJson } from '@lucide/svelte';
	import PageExpiredNotice from '$design/components/PageExpiredNotice.svelte';
	import Pager from '$design/components/Pager.svelte';
	import ScrollRegion from '$design/components/ScrollRegion.svelte';
	import { formatTimestamp, timestampAttribute } from '$lib/format';
	import { displayName } from '$lib/names';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const scope = $derived(
		data.schemaOrganization === null ? 'Platform' : displayName(data.schemaOrganization)
	);
	const selected = $derived(data.schemaOrganization?.name ?? '');
	const firstPage = $derived(!page.url.searchParams.get('cursor'));
	const parents = $derived(
		new Map(data.schemas.map((entry) => [entry.id, `${entry.name} v${entry.version}`]))
	);
</script>

<svelte:head><title>{pageTitle('Schemas', scope)}</title></svelte:head>

<header class="mb-6 border-b border-app-line pb-5">
	<h1 class="flex items-center gap-2">
		<FileJson size={24} class="shrink-0 text-app-muted" aria-hidden="true" />Schemas
	</h1>
	<p class="mt-2 mb-0 text-sm text-app-muted">
		Browse published metadata schemas and their versions.
	</p>
</header>

<form method="GET" action={resolve('/(app)/schemas')} class="mb-6 flex flex-wrap items-end gap-3">
	<label class="grid min-w-0 max-w-full gap-1.5 text-sm font-semibold">
		Schema source
		<select
			name="organization"
			value={selected}
			class="min-h-10 max-w-full rounded-md border border-app-line-strong bg-app-card px-3 py-2 text-app-fg"
		>
			<option value="">Platform</option>
			{#each data.organizationChoices as organization (organization.id)}
				<option value={organization.name}>{displayName(organization)}</option>
			{/each}
		</select>
	</label>
	<button
		type="submit"
		class="min-h-10 rounded-md border border-transparent bg-brand px-4 py-2 text-sm font-semibold text-brand-ink hover:brightness-95"
		>Browse schemas</button
	>
</form>
{#if data.moreOrganizations}<p class="mb-4 text-sm text-app-muted">
		The source list shows the first 500 organizations you can see.
	</p>{/if}

<h2 class="m-0 mb-2 border-0 p-0 text-base font-semibold wrap-anywhere">{scope} schemas</h2>
<p class="mt-0 mb-4 text-sm text-app-muted">
	{data.schemaOrganization === null
		? 'Platform schemas are available to every organization.'
		: 'Versions published by this organization. Inherited platform schemas are listed under Platform.'}
</p>
<PageExpiredNotice />

{#if data.schemas.length > 0}
	<ScrollRegion label="Published schema versions">
		<table class="w-full min-w-2xl border-collapse text-left text-sm">
			<caption class="sr-only">Published schema versions</caption>
			<thead class="text-xs text-app-muted"
				><tr class="border-b border-app-line">
					<th scope="col" class="px-4 py-3 font-semibold">Schema</th><th
						scope="col"
						class="px-4 py-3 font-semibold">Version</th
					><th scope="col" class="px-4 py-3 font-semibold">Extends</th><th
						scope="col"
						class="px-4 py-3 font-semibold">Published</th
					>
				</tr></thead
			>
			<tbody>
				{#each data.schemas as entry (entry.id)}
					<tr class="border-b border-app-line align-top last:border-0">
						<th scope="row" class="px-4 py-3 font-semibold wrap-anywhere"
							><a
								href={`${resolve('/(app)/schemas/[id=uuid]', { id: entry.id })}${selected === '' ? '' : `?organization=${encodeURIComponent(selected)}`}`}
								>{entry.name}</a
							></th
						>
						<td class="mono px-4 py-3">v{entry.version}</td>
						<td class="px-4 py-3 wrap-anywhere"
							>{#if entry.extendsId}<a
									href={resolve('/(app)/schemas/[id=uuid]', { id: entry.extendsId })}
									>{parents.get(entry.extendsId) ?? 'View parent schema'}</a
								>{:else}<span class="text-app-muted">Base schema</span>{/if}</td
						>
						<td class="px-4 py-3 wrap-anywhere"
							><time datetime={timestampAttribute(entry.createdAt)}
								>{formatTimestamp(entry.createdAt)}</time
							><span class="mt-1 block text-xs text-app-muted">by {entry.createdBy}</span></td
						>
					</tr>
				{/each}
			</tbody>
		</table>
	</ScrollRegion>
{:else}
	<p class="rounded-card border border-app-line bg-app-card p-5 text-sm text-app-muted">
		{firstPage
			? 'No schema versions have been published here.'
			: 'No schema versions on this page.'}
	</p>
{/if}
<Pager label="Schema pages" next={data.nextCursor} />
