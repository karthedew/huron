<script lang="ts">
	import type { FileRecord } from '$api/types';
	import { countLabel, formatBytes, formatTimestamp, timestampAttribute } from '$lib/format';
	import CopyText from './CopyText.svelte';
	import ScrollRegion from './ScrollRegion.svelte';

	interface Props {
		/** The table's name, e.g. "Files of ACE MAG level 2, 2024". */
		label: string;
		files: readonly FileRecord[];
	}

	let { label, files }: Props = $props();

	/** How much of a SHA-256 tells files apart at a glance; the whole value is a click away. */
	const SHORT_HASH = 12;
</script>

<!--
	The path column is never narrower than a typical path (`data/ace_mag_l2_2024-01.cdf`) needs;
	on a phone the region scrolls instead. The cells are padded a little less than the schema
	table's, so that beside the explorer at 1024px the table fits even with a size such as
	`123.4 MB`.
-->
<ScrollRegion {label}>
	<table class="w-full border-collapse text-left text-sm">
		<caption class="sr-only">{label}</caption>
		<thead class="text-xs text-app-muted">
			<tr class="border-b border-app-line">
				<th scope="col" class="px-2.5 py-2 font-semibold">Path</th>
				<th scope="col" class="px-2.5 py-2 text-right font-semibold">Size</th>
				<th scope="col" class="px-2.5 py-2 font-semibold">SHA-256</th>
				<th scope="col" class="px-2.5 py-2 font-semibold">Recorded</th>
			</tr>
		</thead>
		<tbody>
			{#each files as file (file.rel_path)}
				{@const short = file.sha256.slice(0, SHORT_HASH)}
				<tr class="border-b border-app-line align-top last:border-b-0">
					<th scope="row" class="mono min-w-56 px-2.5 py-2 text-xs font-normal wrap-anywhere"
						>{file.rel_path}</th
					>
					<td class="px-2.5 py-2 text-right whitespace-nowrap tabular-nums">
						<data value={file.size} title={countLabel(file.size, 'byte')}
							>{formatBytes(file.size)}</data
						>
					</td>
					<td class="px-2.5 py-2">
						<details>
							<!-- Its name starts with what it shows, and says which file the hash is of. -->
							<summary
								aria-label="{short}…, SHA-256 of {file.rel_path}"
								class="w-fit cursor-pointer text-sm whitespace-nowrap"
								><code>{short}…</code></summary
							>
							<!-- The whole value takes the column's width and never widens it, so no column moves. -->
							<div class="mt-1.5 w-0 min-w-full text-sm">
								<CopyText label="SHA-256 of {file.rel_path}" value={file.sha256} />
							</div>
						</details>
					</td>
					<td class="px-2.5 py-2 text-xs">
						<time class="whitespace-nowrap" datetime={timestampAttribute(file.recorded_at)}
							>{formatTimestamp(file.recorded_at)}</time
						>
						<span class="block wrap-anywhere text-app-muted">by {file.recorded_by}</span>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
</ScrollRegion>
