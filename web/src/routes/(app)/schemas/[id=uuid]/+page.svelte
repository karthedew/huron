<script lang="ts">
	import { resolve } from '$app/paths';
	import { ChevronLeft, FileJson } from '@lucide/svelte';
	import SchemaTable from '$design/components/SchemaTable.svelte';
	import { formatTimestamp, timestampAttribute } from '$lib/format';
	import { displayName } from '$lib/names';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const source = $derived(
		data.entry.organizationId === null
			? 'Platform'
			: data.schemaOrganization === null
				? 'Organization'
				: displayName(data.schemaOrganization)
	);
	const unknownOwner = $derived(
		data.entry.organizationId !== null && data.schemaOrganization === null
	);
	const back = $derived(
		unknownOwner
			? resolve('/(app)/orgs')
			: `${resolve('/(app)/schemas')}?organization=${encodeURIComponent(data.schemaOrganization?.name ?? '')}`
	);
	const parentScope = $derived(
		data.parentSchema?.organizationId !== null &&
			data.parentSchema?.organizationId === data.entry.organizationId &&
			data.schemaOrganization !== null
			? `?organization=${encodeURIComponent(data.schemaOrganization.name)}`
			: ''
	);
</script>

<svelte:head
	><title>{pageTitle(`${data.entry.name} v${data.entry.version}`, 'Schemas')}</title></svelte:head
>

<a href={back} class="mb-5 inline-flex items-center gap-1 text-sm"
	><ChevronLeft size={16} aria-hidden="true" />{unknownOwner
		? 'Choose organization'
		: 'Back to schemas'}</a
>
<header class="mb-6 border-b border-app-line pb-5">
	<div class="flex min-w-0 items-start gap-2">
		<FileJson size={24} class="mt-1 shrink-0 text-app-muted" aria-hidden="true" />
		<h1 class="min-w-0 wrap-anywhere">
			{data.entry.name} <span class="text-app-muted">v{data.entry.version}</span>
		</h1>
	</div>
	<dl class="mt-4 mb-0 grid gap-4 text-sm sm:grid-cols-3">
		<div>
			<dt class="mb-1 text-xs text-app-muted">Source</dt>
			<dd class="m-0 wrap-anywhere">{source}</dd>
		</div>
		<div>
			<dt class="mb-1 text-xs text-app-muted">Extends</dt>
			<dd class="m-0 wrap-anywhere">
				{#if data.parentSchema}<a
						href={`${resolve('/(app)/schemas/[id=uuid]', { id: data.parentSchema.id })}${parentScope}`}
						>{data.parentSchema.name} v{data.parentSchema.version}</a
					>{:else}Base schema{/if}
			</dd>
		</div>
		<div>
			<dt class="mb-1 text-xs text-app-muted">Published</dt>
			<dd class="m-0 wrap-anywhere">
				<time datetime={timestampAttribute(data.entry.createdAt)}
					>{formatTimestamp(data.entry.createdAt)}</time
				><span class="mt-1 block text-xs text-app-muted">by {data.entry.createdBy}</span>
			</dd>
		</div>
	</dl>
</header>

<section aria-labelledby="resolved-heading">
	<h2 id="resolved-heading" class="m-0 mb-2 border-0 p-0 text-base font-semibold">
		Resolved schema
	</h2>
	<p class="mt-0 mb-4 text-sm text-app-muted">
		The metadata fields and constraints of this version, with the schemas it extends folded in.
	</p>
	<SchemaTable label="Resolved schema fields" schema={data.resolvedSchema} />
</section>
<details class="mt-8 border-t border-app-line pt-5">
	<summary class="w-fit cursor-pointer text-sm font-semibold">Authored schema</summary>
	<p class="mt-3 mb-4 text-sm text-app-muted">
		The document published for this version, before inheritance is applied.
	</p>
	<SchemaTable label="Authored schema fields" schema={data.authoredSchema} />
</details>
