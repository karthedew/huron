<script lang="ts">
	import { resolve } from '$app/paths';
	import CliHint from '$design/components/CliHint.svelte';
	import CopyText from '$design/components/CopyText.svelte';
	import MetadataView from '$design/components/MetadataView.svelte';
	import { catalogCapabilities } from '$lib/capabilities';
	import { collectionHints } from '$lib/cli';
	import { identifierInCatalog } from '$lib/explorer';
	import { countLabel, formatCount, formatTimestamp, timestampAttribute } from '$lib/format';
	import { displayName } from '$lib/names';
	import { pageTitle } from '$lib/title';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const collection = $derived(data.collection);
	const catalog = $derived(data.catalog);
	const draft = $derived(collection.state === 'draft');
	const can = $derived(catalogCapabilities(data.roles, catalog, data.organizations));
	const params = $derived({
		catalog: collection.catalog,
		identifier: identifierInCatalog(collection.identifier)
	});
	const hints = $derived(
		collectionHints({ ...collection, hasProblems: data.problems.rows.length > 0 }, can.contribute)
	);
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

{#if data.problems.rows.length > 0}
	<section
		aria-labelledby="collection-problems"
		class="mb-8 rounded-card border border-app-warn-line bg-app-warn px-4 py-3.5"
	>
		<h2 id="collection-problems" class="m-0 border-0 p-0 text-base font-semibold">
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

<!-- With room, the details stand beside the metadata. -->
<div class="@container">
	<div class="grid gap-x-8 gap-y-8 @3xl:grid-cols-details">
		<section aria-labelledby="collection-metadata" class="min-w-0">
			<h2 id="collection-metadata" class="m-0 mb-3 border-0 p-0 text-base font-semibold">
				Metadata
			</h2>
			{#if !data.schemaResolved}
				<p class="mt-0 mb-3 text-sm text-app-muted">
					Its schema override no longer fits the catalog's schema, so the fields show by their keys.
				</p>
			{/if}
			<MetadataView catalog={collection.catalog} view={data.metadata} />
			<!-- The head shortens a long title or description, which the list leaves to it. -->
			{#if data.metadata.shortened || collection.shortened}
				<p class="mt-4 mb-0 text-sm text-app-muted">
					This metadata is too long to show in full here.
					{#if !draft}
						<!-- An endpoint, not a page: the browser loads it itself. -->
						<a href={metadataFile} data-sveltekit-reload class="underline underline-offset-2"
							>metadata.json</a
						> holds all of it.
					{/if}
				</p>
			{/if}
		</section>

		<!-- Below the metadata it has the width for two columns of details; beside it, one. -->
		<aside aria-labelledby="collection-details" class="@container min-w-0">
			<h2 id="collection-details" class="m-0 mb-3 border-0 p-0 text-base font-semibold">Details</h2>
			<dl class="m-0 grid gap-x-8 gap-y-3 text-sm @lg:grid-cols-2">
				<div class="min-w-0 @lg:col-span-2">
					<dt class="text-xs font-semibold text-app-muted">Share path</dt>
					<dd class="m-0 min-w-0">
						{#if collection.sharePath !== null}
							<CopyText label="share path" value={collection.sharePath} />
						{:else}
							<span class="text-app-muted">No directory yet</span>
						{/if}
					</dd>
				</div>
				{#if !draft}
					<div>
						<dt class="text-xs font-semibold text-app-muted">Files</dt>
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
				<div>
					<dt class="text-xs font-semibold text-app-muted">Created</dt>
					<dd class="m-0 wrap-anywhere">
						{@render time(collection.createdAt)} by {collection.createdBy}
					</dd>
				</div>
				<div>
					<dt class="text-xs font-semibold text-app-muted">Updated</dt>
					<dd class="m-0">{@render time(collection.updatedAt)}</dd>
				</div>
				<div>
					<dt class="text-xs font-semibold text-app-muted">Activated</dt>
					<dd class="m-0">
						{#if collection.activatedAt !== null}
							{@render time(collection.activatedAt)}
						{:else}
							<span class="text-app-muted">Not yet</span>
						{/if}
					</dd>
				</div>
				<div>
					<dt class="text-xs font-semibold text-app-muted">Schema</dt>
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
				{#if !draft}
					<div>
						<dt class="text-xs font-semibold text-app-muted">Metadata file</dt>
						<dd class="m-0">
							<!-- An endpoint, not a page: the browser loads it itself. -->
							<a href={metadataFile} data-sveltekit-reload class="mono underline underline-offset-2"
								>metadata.json</a
							>
						</dd>
					</div>
				{/if}
			</dl>
			<details class="mt-4">
				<summary class="w-fit cursor-pointer text-sm font-semibold">Technical details</summary>
				<p class="mt-2 mb-0 text-sm">Record revision {formatCount(collection.revision)}</p>
				<p class="mt-0.5 mb-0 text-xs text-app-muted">
					It goes up with every change to the record, commits included; it is not a version of the
					data.
				</p>
				<dl class="mt-3 mb-0 text-sm">
					<dt class="text-xs font-semibold text-app-muted">ID</dt>
					<dd class="m-0 min-w-0"><CopyText label="collection id" value={collection.id} /></dd>
				</dl>
			</details>
		</aside>
	</div>
</div>

<section aria-labelledby="collection-cli" class="mt-10">
	<h2 id="collection-cli" class="m-0 mb-3 border-0 p-0 text-base font-semibold">With the CLI</h2>
	<div class="grid max-w-3xl gap-4">
		{#each hints as hint (hint.title)}
			<CliHint title={hint.title} command={hint.command} />
		{/each}
	</div>
</section>
