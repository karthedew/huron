<script lang="ts">
	import { countLabel, formatCount } from '$lib/format';
	import type { MetadataField, MetadataValue, MetadataView } from '$lib/metadata';
	import { emptySearch, withLabel, type LabelFilter } from '$lib/search';
	import { catalogSearchHref } from '$lib/search-links';
	import { CHIPS_MORE, PLAIN_CHIP } from '../chips';
	import Badge from './Badge.svelte';
	import LabelChips from './LabelChips.svelte';

	interface Props {
		/** The collection's catalog: label chips lead to its search. */
		catalog: string;
		/** The collection's metadata, as `metadataView` presents it. */
		view: MetadataView;
	}

	let { catalog, view }: Props = $props();

	/** The catalog's search for collections with one label. */
	function labelSearch(label: LabelFilter): string {
		return catalogSearchHref(catalog, withLabel(emptySearch(), label));
	}
</script>

{#snippet value(item: MetadataValue)}
	{#if item.kind === 'missing'}
		<Badge tone="warn">Missing</Badge>
	{:else if item.kind === 'none'}
		<span class="text-app-muted">None</span>
	{:else if item.kind === 'time'}
		<time datetime={item.datetime}>{item.text}</time>
	{:else if item.kind === 'email'}
		<a href={item.href} class="wrap-anywhere underline underline-offset-2">{item.text}</a>
	{:else if item.kind === 'link'}
		<a href={item.href} rel="noopener noreferrer" class="wrap-anywhere underline underline-offset-2"
			>{item.text}</a
		>
	{:else if item.kind === 'chips'}
		<ul class="m-0 flex list-none flex-wrap gap-1.5 p-0">
			<!-- The items of one value, in their order; the same text may come twice. -->
			{#each item.items as chip}
				<li class={PLAIN_CHIP}>{chip}</li>
			{/each}
			{#if item.more > 0}<li class={CHIPS_MORE}>and {formatCount(item.more)} more</li>{/if}
		</ul>
	{:else if item.kind === 'labels'}
		<LabelChips
			chips={item.items}
			more={item.more}
			href={labelSearch}
			action="search the catalog for this label"
		/>
	{:else if item.kind === 'list'}
		<ul class="m-0 grid list-none gap-1.5 p-0">
			<!-- The items of one value, in their order; two may be alike. -->
			{#each item.items as entry}
				<li class="min-w-0 border-l-2 border-app-line pl-2.5">
					{#if entry.kind === 'object'}
						{@render compact(entry.fields, entry.more)}
					{:else}
						{@render value(entry)}
					{/if}
				</li>
			{/each}
			{#if item.more > 0}<li class="text-xs text-app-muted">
					and {formatCount(item.more)} more
				</li>{/if}
		</ul>
	{:else if item.kind === 'object'}
		{@render nested(item.fields, item.more)}
	{:else if item.kind === 'number'}
		<span class="wrap-anywhere tabular-nums">{item.text}</span>
	{:else}
		<span class="whitespace-pre-line wrap-anywhere">{item.text}</span>
	{/if}
{/snippet}

<!-- An object among a list's items: its fields on as few lines as fit. -->
{#snippet compact(fields: readonly MetadataField[], more: number)}
	<dl class="m-0 flex flex-wrap gap-x-4 gap-y-0.5">
		<!-- In their order and not keyed: two long keys, shortened, may read alike. -->
		{#each fields as field}
			<div class="flex min-w-0 flex-wrap items-baseline gap-x-1.5">
				<dt class="min-w-0 text-xs font-semibold wrap-anywhere text-app-muted">{field.label}</dt>
				<dd class="m-0 min-w-0">{@render value(field.value)}</dd>
			</div>
		{/each}
	</dl>
	{#if more > 0}<p class="m-0 text-xs text-app-muted">and {countLabel(more, 'more field')}</p>{/if}
{/snippet}

<!--
	An object as a field's value: its fields under each other, set in by a line as list items
	are, so the fields of an object inside it read as a level of their own.
-->
{#snippet nested(fields: readonly MetadataField[], more: number)}
	<div class="min-w-0 border-l-2 border-app-line pl-2.5">
		<dl class="m-0 grid gap-1.5">
			<!-- In their order and not keyed: two long keys, shortened, may read alike. -->
			{#each fields as field}
				<div class="min-w-0">
					<dt class="text-xs font-semibold wrap-anywhere text-app-muted">{field.label}</dt>
					<dd class="m-0 min-w-0">{@render value(field.value)}</dd>
				</div>
			{/each}
		</dl>
		{#if more > 0}<p class="mt-1.5 mb-0 text-xs text-app-muted">
				and {countLabel(more, 'more field')}
			</p>{/if}
	</div>
{/snippet}

<!-- With room, the labels stand in a column of their own beside the values. -->
{#snippet fieldList(fields: readonly MetadataField[])}
	<dl class="@container m-0 grid">
		<!-- In their order and not keyed: two long keys, shortened, may read alike. -->
		{#each fields as field}
			<div
				class="grid min-w-0 gap-x-6 gap-y-1 border-b border-app-line py-2.5 text-sm first:pt-0 last:border-b-0 @lg:grid-cols-fields"
			>
				<dt class="font-semibold wrap-anywhere text-app-muted">{field.label}</dt>
				<dd class="m-0 min-w-0">{@render value(field.value)}</dd>
			</div>
		{/each}
	</dl>
{/snippet}

{#if view.fields.length > 0}
	{@render fieldList(view.fields)}
{:else if view.other.length === 0}
	<p class="m-0 text-sm text-app-muted">Nothing beyond the title and description.</p>
{/if}
{#if view.other.length > 0}
	<h3 class="mt-6 mb-0 text-sm font-semibold">Other fields</h3>
	<p class="mt-0.5 mb-3 text-xs text-app-muted">Fields the collection's schema does not name.</p>
	{@render fieldList(view.other)}
{/if}
{#if view.more > 0}
	<p class="mt-3 mb-0 text-sm text-app-muted">and {countLabel(view.more, 'more field')}</p>
{/if}
