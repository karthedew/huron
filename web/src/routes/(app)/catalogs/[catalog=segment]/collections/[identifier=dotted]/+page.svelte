<script lang="ts">
	import { resolve } from '$app/paths';
	import Badge from '$design/components/Badge.svelte';
	import { statePresentation } from '$lib/collection-state';
	import CopyText from '$design/components/CopyText.svelte';
	import MetadataView from '$design/components/MetadataView.svelte';
	import { identifierInCatalog } from '$lib/explorer';
	import { countLabel, formatCount, formatTimestamp, timestampAttribute } from '$lib/format';
	import { displayName } from '$lib/names';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const collection = $derived(data.collection);
	const catalog = $derived(data.catalog);
	const shown = $derived(
		statePresentation(collection.state, { overrideIncompatible: collection.overrideIncompatible })
	);
	const draft = $derived(collection.state === 'draft');
	const params = $derived({
		catalog: collection.catalog,
		identifier: identifierInCatalog(collection.identifier)
	});
	const metadataFile = $derived(
		resolve(
			'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/metadata.json',
			params
		)
	);
	/**
	 * What it takes to make the collection valid again. A schema override that no longer fits
	 * the catalog's schema is its only problem then: the metadata cannot be checked before it is
	 * fixed or removed.
	 */
	const problemsNote = $derived.by(() => {
		if (collection.overrideIncompatible) {
			return draft
				? 'The draft can be activated once its schema override is fixed or removed and its metadata is valid.'
				: 'The collection is active again once its schema override is fixed or removed and its metadata is valid.';
		}
		return draft
			? 'The draft can be activated once its metadata is fixed.'
			: 'Once its metadata is fixed, the collection is active again.';
	});
</script>

<svelte:head>
	<title>{pageTitle(collection.title ?? collection.identifier, displayName(catalog))}</title>
</svelte:head>

{#snippet time(iso: string)}
	<time datetime={timestampAttribute(iso)}>{formatTimestamp(iso)}</time>
{/snippet}

<div class="mb-5">
	<Badge tone={shown.tone}>{shown.label}</Badge>
	{#if shown.explanation}<p class="mt-2 mb-0 text-sm wrap-anywhere text-app-muted">
			{shown.explanation}
		</p>{/if}
	{#if collection.description}<p
			class="mt-3 mb-0 max-w-3xl text-sm leading-6 whitespace-pre-line wrap-anywhere"
		>
			{collection.description}
		</p>{/if}
</div>

{#if data.problems.rows.length > 0}
	<section
		aria-labelledby="collection-problems"
		class="mb-5 rounded-md border border-app-warn-line bg-app-warn px-4 py-3"
	>
		<h2 id="collection-problems" class="m-0 border-0 p-0 text-sm font-semibold">
			{countLabel(data.problems.rows.length + data.problems.more, 'problem')}
			{collection.overrideIncompatible ? 'with the schema override' : 'in the metadata'}
		</h2>
		<p class="mt-1 mb-2 text-sm">{problemsNote}</p>
		<ul class="m-0 grid list-disc gap-1 pl-5 text-sm">
			<!-- In the API's order; two problems may read alike. -->
			{#each data.problems.rows as problem}
				<li class="wrap-anywhere">
					{#if problem.field !== null}<span class="font-semibold">{problem.field}</span
						>:{' '}{/if}{problem.message}
				</li>
			{/each}
			{#if data.problems.more > 0}
				<li class="list-none">and {countLabel(data.problems.more, 'more problem')}</li>
			{/if}
		</ul>
	</section>
{/if}

<div class="@container">
	<div class="grid items-start gap-6 @3xl:grid-cols-2">
		<section aria-labelledby="collection-summary" class="min-w-0">
			<div
				class="flex flex-wrap items-baseline justify-between gap-2 border-b border-app-line pb-2"
			>
				<h2 id="collection-summary" class="m-0 border-0 p-0 text-sm font-semibold">At a glance</h2>
				<a
					href={resolve(
						'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/metadata',
						params
					)}
					class="text-sm underline underline-offset-2">View all metadata</a
				>
			</div>
			{#if data.metadata.fields.length > 0}
				<MetadataView catalog={collection.catalog} view={data.metadata} />
			{:else}
				<p class="mt-3 mb-0 text-sm text-app-muted">
					Explore the Metadata tab for this collection's recorded details.
				</p>
			{/if}
			{#if data.metadata.shortened}
				<p class="mt-3 mb-0 text-xs text-app-muted">
					This is a preview. The Metadata tab has more detail.
				</p>
			{/if}
			{#if collection.shortened}
				<p class="mt-3 mb-0 text-sm text-app-muted">
					This metadata is too long to show in full here.
					{#if !draft}<a
							href={metadataFile}
							data-sveltekit-reload
							class="underline underline-offset-2">metadata.json</a
						> holds all of it.{/if}
				</p>
			{/if}
		</section>

		<div class="min-w-0">
			<section aria-labelledby="collection-access">
				<h2 id="collection-access" class="m-0 border-b border-app-line pb-2 text-sm font-semibold">
					Use this collection
				</h2>
				<dl class="m-0 text-sm">
					<div class="min-w-0 py-3">
						<dt class="text-xs font-medium text-app-muted">Share path</dt>
						<dd class="m-0 min-w-0">
							{#if collection.sharePath !== null}<CopyText
									label="share path"
									value={collection.sharePath}
								/>{:else}<span class="text-app-muted">No directory yet</span>{/if}
						</dd>
					</div>
					{#if !draft}
						<div class="flex flex-wrap items-baseline gap-3 pb-3">
							<dt class="text-xs font-medium text-app-muted">Files</dt>
							<dd class="m-0">
								<a
									href={resolve(
										'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/files',
										params
									)}
									class="underline underline-offset-2">{countLabel(collection.fileCount, 'file')}</a
								>
							</dd>
						</div>
					{/if}
				</dl>
			</section>
		</div>
	</div>
</div>

<details class="mt-6 border-t border-app-line pt-4">
	<summary class="w-fit cursor-pointer text-sm font-semibold">Record details</summary>
	<p class="mt-3 mb-0 text-sm">Record revision {formatCount(collection.revision)}</p>
	<p class="mt-0.5 mb-0 text-xs text-app-muted">
		It goes up with every change to the record, commits included; it is not a version of the data.
	</p>
	<dl class="mt-4 mb-0 grid gap-x-6 gap-y-4 text-sm sm:grid-cols-2">
		<div class="min-w-0">
			<dt class="text-xs font-medium text-app-muted">Created</dt>
			<dd class="m-0 wrap-anywhere">
				{@render time(collection.createdAt)} by {collection.createdBy}
			</dd>
		</div>
		<div class="min-w-0">
			<dt class="text-xs font-medium text-app-muted">Updated</dt>
			<dd class="m-0">{@render time(collection.updatedAt)}</dd>
		</div>
		<div class="min-w-0">
			<dt class="text-xs font-medium text-app-muted">Activated</dt>
			<dd class="m-0">
				{#if collection.activatedAt !== null}{@render time(collection.activatedAt)}{:else}<span
						class="text-app-muted">Not yet</span
					>{/if}
			</dd>
		</div>
		<div class="min-w-0">
			<dt class="text-xs font-medium text-app-muted">Schema</dt>
			<dd class="m-0 wrap-anywhere">
				<a
					href={resolve(
						'/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]/schema',
						params
					)}
					class="mono underline underline-offset-2"
					>{collection.schema.name} v{collection.schema.version}</a
				>{#if collection.hasOverride}{' '}with an override{/if}
			</dd>
		</div>
		<div class="min-w-0">
			<dt class="text-xs font-medium text-app-muted">ID</dt>
			<dd class="m-0"><CopyText label="collection id" value={collection.id} /></dd>
		</div>
		{#if !draft}<div>
				<dt class="text-xs font-medium text-app-muted">Metadata file</dt>
				<dd class="m-0">
					<a href={metadataFile} data-sveltekit-reload class="mono underline underline-offset-2"
						>metadata.json</a
					>
				</dd>
			</div>{/if}
	</dl>
</details>
