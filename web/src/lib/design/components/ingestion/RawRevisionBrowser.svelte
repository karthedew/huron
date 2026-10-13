<script lang="ts">
	import { resolve } from '$app/paths';
	import { Download, FileText } from '@lucide/svelte';
	import { rawFileDownloadUrl } from '$api/client';
	import type { RawInspection, RawTarget } from '$api/types';
	import { formatBytes } from '$lib/ingestion/files';
	let {
		inspection,
		target,
		history = false,
		href
	}: {
		inspection: Extract<RawInspection, { state: 'managed' }>;
		target: RawTarget;
		history?: boolean;
		href: (changes: Record<string, string | null>) => '/browse' | `/browse?${string}`;
	} = $props();
	let search = $state('');
	const revision = $derived(inspection.selectedRevision);
	const files = $derived(
		inspection.manifest?.files.filter((file) =>
			file.path.toLowerCase().includes(search.toLowerCase())
		) ?? []
	);
</script>

{#if inspection.error}<p
		role="alert"
		class="rounded-md border border-app-line p-4 text-sm text-app-danger"
	>
		{inspection.error}
	</p>
{:else if history}
	<h2 class="m-0 border-0 p-0 text-sm font-semibold">Revision history</h2>
	<p class="mt-2 text-xs leading-5 text-app-muted">
		Each committed revision is an independent, immutable submission.
	</p>
	<ul class="mt-4 divide-y divide-app-line rounded border border-app-line">
		{#each inspection.revisions.revisions as entry (entry.id)}<li class="p-4">
				<a
					href={resolve(href({ revision: entry.id, tab: 'files' }))}
					class="text-sm font-semibold text-brand-strong underline">Revision {entry.number}</a
				>
				<p class="mt-2 text-xs text-app-muted">
					{entry.file_count} files · {formatBytes(entry.total_bytes)} ·
					<time datetime={entry.committed_at}>{entry.committed_at}</time>
				</p>
				<p class="mt-2 break-all font-mono text-[10px] text-app-muted">{entry.id}</p>
			</li>{:else}<li class="p-4 text-xs text-app-muted">
				No committed revisions are available.
			</li>{/each}
	</ul>
	{#if inspection.revisions.next_before !== null}<a
			href={resolve(
				href({
					tab: 'history',
					revision: null,
					rawBefore: String(inspection.revisions.next_before)
				})
			)}
			class="mt-4 inline-flex text-xs text-brand-strong underline">Older revisions</a
		>{/if}
{:else if revision}
	<div class="flex flex-wrap items-start justify-between gap-3">
		<div>
			<h2 class="m-0 border-0 p-0 text-sm font-semibold">Revision {revision.number} files</h2>
			<p class="mt-2 text-xs text-app-muted">
				{revision.file_count} files · {formatBytes(revision.total_bytes)}
			</p>
		</div>
		<a href={resolve(href({ tab: 'history' }))} class="text-xs text-brand-strong underline"
			>Revision history</a
		>
	</div>
	<p class="mt-3 break-all font-mono text-[10px] text-app-muted">
		Manifest SHA-256: {revision.manifest_sha256}
	</p>
	<label class="mt-5 grid gap-2 text-xs font-medium"
		>Find revision files<input
			type="search"
			bind:value={search}
			placeholder="Filter by relative path"
			class="w-full min-w-0 rounded border border-app-line bg-app-bg px-3 py-2 font-normal"
		/></label
	>
	<ul
		class="mt-4 divide-y divide-app-line rounded border border-app-line"
		aria-label="Revision files"
	>
		{#each files as file (file.path)}<li class="flex min-w-0 items-start gap-3 p-3">
				<FileText size={16} class="mt-0.5 shrink-0 text-app-muted" />
				<div class="min-w-0 flex-1">
					<p class="break-all font-mono text-xs">{file.path}</p>
					<p class="mt-1 text-[11px] text-app-muted">
						{formatBytes(file.size)} · {file.media_type}
					</p>
					<details class="mt-2 text-[10px] text-app-muted">
						<summary>SHA-256</summary>
						<p class="mt-1 break-all font-mono">{file.sha256}</p>
					</details>
				</div>
				<a
					href={resolve(rawFileDownloadUrl(target, revision.id, file.path))}
					download
					aria-label={`Download ${file.path}`}
					class="shrink-0 rounded p-1 text-brand-strong hover:bg-app-hover"
					><Download size={16} /></a
				>
			</li>{:else}<li class="p-4 text-xs text-app-muted">No files match this search.</li>{/each}
	</ul>
{:else}<p class="text-sm text-app-muted">No committed revisions are available.</p>{/if}
