<script lang="ts">
	import { resolve } from '$app/paths';
	import { activityName, type ActivityRow, type ActivityTarget } from '$lib/activity';
	import { identifierInCatalog } from '$lib/explorer';
	import { formatTimestamp, timestampAttribute } from '$lib/format';

	interface Props {
		/** The list's name, e.g. "Catalog activity". */
		label: string;
		/** The catalog the entries belong to; namespaces are linked within it. */
		catalog: string;
		rows: readonly ActivityRow[];
	}

	let { label, catalog, rows }: Props = $props();

	function href(target: ActivityTarget): string {
		switch (target.kind) {
			case 'namespace':
				return resolve('/(app)/catalogs/[catalog=segment]/namespaces/[path=dotted]', {
					catalog,
					path: target.path
				});
			case 'collection':
				return resolve('/(app)/catalogs/[catalog=segment]/collections/[identifier=dotted]', {
					catalog: target.identifier.slice(0, target.identifier.indexOf('.')),
					identifier: identifierInCatalog(target.identifier)
				});
			case 'collection-id':
				return resolve('/(app)/collections/[id=uuid]', { id: target.id });
		}
	}
</script>

<!-- A log: with room, the time stands in its own column beside what happened. -->
<ol class="@container m-0 list-none p-0" aria-label={label}>
	{#each rows as row (row.key)}
		<li
			class="grid min-w-0 gap-x-4 gap-y-0.5 border-b border-app-line py-2.5 first:pt-0 last:border-b-0 @2xl:grid-cols-log"
		>
			<time class="text-xs text-app-muted @2xl:pt-0.5" datetime={timestampAttribute(row.at)}
				>{formatTimestamp(row.at)}</time
			>
			<div class="min-w-0">
				<!-- The summary continues the label: "Assigned schema space-weather v1 (was …)". -->
				<p class="m-0 text-sm wrap-anywhere">
					<span class="font-semibold">{row.label}</span>{#if row.summary}{' '}<span
							>{row.summary}</span
						>{/if}
				</p>
				<p class="mt-0.5 mb-0 flex flex-wrap items-center gap-x-1.5 text-xs text-app-muted">
					{#if row.target}
						<a href={href(row.target)} class="mono min-w-0 font-semibold break-all"
							>{row.target.text}</a
						><span aria-hidden="true">·</span>
					{/if}
					<span class="min-w-0 wrap-anywhere">{row.actor}</span>
				</p>
				<details class="mt-1">
					<!-- Every entry has one: its name says whose details they are. -->
					<summary
						aria-label="Details: {activityName(row)}"
						class="w-fit cursor-pointer text-xs font-semibold text-app-muted hover:text-app-fg"
						>Details</summary
					>
					<!-- Wrapped rather than scrolled: the details never need a scroll region of their own. -->
					<pre class="mt-1.5 mb-0 overflow-visible text-xs whitespace-pre-wrap wrap-anywhere"><code
							>{row.detail}</code
						></pre>
				</details>
			</div>
		</li>
	{/each}
</ol>
