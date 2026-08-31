<script lang="ts">
	import {
		CheckCircle2,
		ChevronRight,
		CircleDot,
		Clock3,
		Database,
		LoaderCircle,
		RefreshCw,
		UploadCloud
	} from '@lucide/svelte';
	import { onMount } from 'svelte';
	import type { IngestJob } from '$api/types';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	let localJobs = $state<IngestJob[]>([]);
	let statusFilter = $state<'all' | IngestJob['status']>('all');

	onMount(() => {
		localJobs = JSON.parse(
			sessionStorage.getItem('huron-preview-ingest-jobs') ?? '[]'
		) as IngestJob[];
	});

	const jobs = $derived([...localJobs, ...data.jobs]);
	const visibleJobs = $derived(
		statusFilter === 'all' ? jobs : jobs.filter((job) => job.status === statusFilter)
	);
	const activeCount = $derived(
		jobs.filter((job) => job.status === 'queued' || job.status === 'running').length
	);

	const statusLabel = (status: IngestJob['status']) =>
		({ queued: 'Queued', running: 'Running', succeeded: 'Succeeded', failed: 'Failed' })[status];
	const statusIcon = (status: IngestJob['status']) =>
		({ queued: Clock3, running: LoaderCircle, succeeded: CheckCircle2, failed: CircleDot })[status];
</script>

<svelte:head><title>Jobs & queue · Huron</title></svelte:head>

<div class="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
	<div>
		<div
			class="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.11em] text-app-muted"
		>
			<RefreshCw size={14} /> Pipeline activity
		</div>
		<h1>Jobs & queue</h1>
		<p class="mt-2 text-sm text-app-muted">
			Track raw uploads, bronze materializations, and their immutable destinations.
		</p>
	</div>
	<a
		href="/ingestion"
		class="inline-flex h-9 items-center gap-2 rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29]"
		><UploadCloud size={15} /> New ingest</a
	>
</div>

<div class="mb-4 grid gap-3 sm:grid-cols-3">
	<div class="rounded-lg border border-app-line bg-app-card p-4 shadow-[var(--shadow-sm)]">
		<p class="text-xs font-medium text-app-muted">Active jobs</p>
		<p class="mt-1 text-2xl font-semibold tabular-nums">{activeCount}</p>
	</div>
	<div class="rounded-lg border border-app-line bg-app-card p-4 shadow-[var(--shadow-sm)]">
		<p class="text-xs font-medium text-app-muted">Recent jobs</p>
		<p class="mt-1 text-2xl font-semibold tabular-nums">{jobs.length}</p>
	</div>
	<div class="rounded-lg border border-app-line bg-app-card p-4 shadow-[var(--shadow-sm)]">
		<p class="text-xs font-medium text-app-muted">Queue health</p>
		<p class="mt-1 flex items-center gap-2 text-sm font-semibold text-app-success">
			<CheckCircle2 size={16} /> Accepting work
		</p>
	</div>
</div>

<section
	class="overflow-hidden rounded-lg border border-app-line bg-app-card shadow-[var(--shadow-sm)]"
>
	<div
		class="flex flex-col gap-3 border-b border-app-line bg-app-bg px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
	>
		<div>
			<h2 class="m-0 border-0 p-0 text-sm font-semibold">Ingest activity</h2>
			<p class="mt-0.5 text-xs text-app-muted">Newest jobs appear first.</p>
		</div>
		<label class="flex items-center gap-2 text-xs font-medium text-app-muted">
			Status
			<select
				bind:value={statusFilter}
				aria-label="Filter jobs by status"
				class="h-8 rounded-md border border-app-line bg-app-card px-2 text-xs text-app-fg"
			>
				<option value="all">All jobs</option>
				<option value="queued">Queued</option>
				<option value="running">Running</option>
				<option value="succeeded">Succeeded</option>
				<option value="failed">Failed</option>
			</select>
		</label>
	</div>

	<div class="divide-y divide-app-line">
		{#each visibleJobs as job}
			{@const StatusIcon = statusIcon(job.status)}
			<div
				class="grid gap-3 px-4 py-3 sm:grid-cols-[130px_minmax(0,1fr)_130px_120px_20px] sm:items-center"
			>
				<div>
					<p class="font-mono text-xs font-semibold text-app-fg">{job.id}</p>
					<p class="mt-1 text-[10px] text-app-muted">
						{new Date(job.createdAt).toLocaleString([], {
							dateStyle: 'medium',
							timeStyle: 'short'
						})}
					</p>
				</div>
				<div class="min-w-0">
					<p class="truncate text-sm font-semibold">{job.dataset} · {job.release}</p>
					<p class="mt-0.5 truncate text-xs text-app-muted">
						{job.organization} / {job.project}
					</p>
				</div>
				<div class="flex items-center gap-2 text-xs font-semibold capitalize">
					<Database size={14} class="text-brand-strong" />
					{job.layer}
				</div>
				<div
					aria-label={`Status: ${statusLabel(job.status)}`}
					class="inline-flex w-fit items-center gap-1.5 rounded-full border border-app-line px-2 py-1 text-xs font-semibold"
					class:text-app-success={job.status === 'succeeded'}
					class:text-brand-strong={job.status === 'queued' || job.status === 'running'}
					class:text-app-danger={job.status === 'failed'}
				>
					<StatusIcon size={13} class={job.status === 'running' ? 'animate-spin' : ''} />
					{statusLabel(job.status)}
				</div>
				<ChevronRight size={15} class="hidden text-app-muted sm:block" />
			</div>
		{/each}
		{#if visibleJobs.length === 0}
			<div class="px-5 py-14 text-center">
				<Database size={24} class="mx-auto text-app-muted" />
				<p class="mt-3 text-sm font-semibold">No jobs match this status</p>
				<p class="mt-1 text-xs text-app-muted">Choose another status or begin a new ingest.</p>
			</div>
		{/if}
	</div>
</section>
