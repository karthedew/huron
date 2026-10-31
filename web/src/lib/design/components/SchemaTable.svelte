<script lang="ts">
	import { countLabel } from '$lib/format';
	import type { SchemaView } from '$lib/schema-view';
	import Badge from './Badge.svelte';
	import ScrollRegion from './ScrollRegion.svelte';

	interface Props {
		/** The table's name, e.g. "Fields of the catalog's schema". */
		label: string;
		/** A resolved schema, as `schemaView` presents it. */
		schema: SchemaView;
	}

	let { label, schema }: Props = $props();
</script>

{#if schema.title || schema.description}
	<div class="mb-4 max-w-3xl">
		{#if schema.title}<p class="m-0 font-semibold wrap-anywhere">{schema.title}</p>{/if}
		{#if schema.description}
			<p class="mt-0.5 mb-0 text-sm wrap-anywhere text-app-muted">{schema.description}</p>
		{/if}
	</div>
{/if}

{#if schema.fields.length > 0}
	<ScrollRegion {label}>
		<table class="w-full min-w-2xl border-collapse text-left text-sm">
			<caption class="sr-only">{label}</caption>
			<thead class="text-xs text-app-muted">
				<tr class="border-b border-app-line">
					<th scope="col" class="px-3 py-2 font-semibold">Field</th>
					<th scope="col" class="px-3 py-2 font-semibold">Type</th>
					<th scope="col" class="px-3 py-2 font-semibold">Required</th>
					<th scope="col" class="px-3 py-2 font-semibold">Constraints</th>
					<th scope="col" class="px-3 py-2 font-semibold">Description</th>
				</tr>
			</thead>
			<tbody>
				<!-- In their order and not keyed: two long keys, shortened, may read alike. -->
				{#each schema.fields as field}
					<tr class="border-b border-app-line align-top last:border-b-0">
						<th
							scope="row"
							class={[
								'px-3 py-2 font-semibold wrap-anywhere',
								field.depth > 0 && 'font-medium text-app-muted'
							]}
						>
							{field.label}
							<span class="mono block text-xs font-normal whitespace-nowrap text-app-muted"
								>{field.key}</span
							>
						</th>
						<td class="mono px-3 py-2 text-xs wrap-anywhere">{field.type}</td>
						<td class="px-3 py-2">
							{#if field.required}<Badge tone="accent">Required</Badge>{:else}<span
									class="text-app-muted">Optional</span
								>{/if}
						</td>
						<td class="px-3 py-2 text-xs">
							{#if field.constraints.length > 0}
								<ul class="m-0 grid list-none gap-0.5 p-0">
									<!-- A fixed list of phrases that never reorders. -->
									{#each field.constraints as constraint}
										<li class="wrap-anywhere">{constraint}</li>
									{/each}
								</ul>
							{:else}<span class="text-app-muted">None</span>{/if}
						</td>
						<td class="px-3 py-2 wrap-anywhere text-app-muted">{field.description}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</ScrollRegion>
	{#if schema.moreFields > 0}
		<p class="mt-3 mb-0 text-sm text-app-muted">
			and {countLabel(schema.moreFields, 'more field')}: this schema is too long to show in full
			here.
		</p>
	{/if}
{:else}
	<p class="m-0 text-app-muted">This schema names no fields.</p>
{/if}

{#if schema.otherFields !== null}
	<p class="mt-3 mb-0 text-sm text-app-muted">
		{schema.otherFields
			? 'Metadata may hold other fields as well.'
			: 'Metadata may hold no other fields.'}
	</p>
{/if}

<details class="mt-4">
	<summary class="w-fit cursor-pointer text-sm font-semibold">Raw JSON</summary>
	{#if schema.jsonShortened}
		<p class="mt-2 mb-0 text-sm text-app-muted">
			The document is too long to show in full here; this is its beginning.
		</p>
	{/if}
	<pre class="mt-2 mb-0 overflow-visible text-xs whitespace-pre-wrap wrap-anywhere"><code
			>{schema.json}</code
		></pre>
</details>
