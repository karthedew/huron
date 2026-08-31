<script lang="ts">
	import {
		ArrowLeft,
		ArrowRight,
		Building2,
		Braces,
		Check,
		CheckCircle2,
		ChevronRight,
		CircleDot,
		CloudUpload,
		Database,
		File,
		FileArchive,
		Info,
		Layers3,
		LoaderCircle,
		ShieldCheck,
		UploadCloud,
		X
	} from '@lucide/svelte';
	import { selectedOrganization } from '$lib/stores/workspace';
	import type { IngestJob } from '$api/types';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	let step = $state(1);
	let layer = $state<'raw' | 'bronze'>('raw');
	let project = $state('');
	let dataset = $state('');
	let newDatasetSlug = $state('');
	let release = $state('run-0003');
	let files = $state<string[]>([]);
	let fileInput = $state<HTMLInputElement>();
	let submitted = $state(false);
	let submissionId = $state('');
	let rawRevision = $state('run-0002-rev-1');
	let revisionReason = $state('Initial ingest for the August sweep');
	let classification = $state('unclassified');
	let ownerGroup = $state('Science Data Team');
	let tags = $state('mcnp, sweep, august-2026');
	let notes = $state('');

	const steps = [
		{ number: 1, label: 'Destination' },
		{ number: 2, label: 'Source' },
		{ number: 3, label: 'Metadata' },
		{ number: 4, label: 'Review' }
	];
	const currentOrg = $derived(
		data.organizations.find((organization) => organization.slug === $selectedOrganization) ??
			data.organizations[0]
	);
	const orgProjects = $derived(
		data.projects.filter((candidate) => candidate.orgSlug === currentOrg?.slug)
	);
	const selectedProject = $derived(
		orgProjects.find((candidate) => candidate.slug === project) ?? orgProjects[0]
	);
	const projectDatasets = $derived(
		data.datasets.filter(
			(candidate) =>
				candidate.orgSlug === currentOrg?.slug && candidate.projectSlug === selectedProject?.slug
		)
	);
	const selectedDataset = $derived(projectDatasets.find((candidate) => candidate.slug === dataset));
	const destinationDatasetSlug = $derived(
		dataset === 'new' ? newDatasetSlug.trim() : (selectedDataset?.slug ?? '')
	);
	const destinationDatasetName = $derived(
		dataset === 'new'
			? newDatasetSlug.trim() || 'New dataset'
			: (selectedDataset?.name ?? 'No dataset')
	);
	const releaseIsValid = $derived(/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(release));
	const datasetSlugIsValid = $derived(
		dataset !== 'new' || /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(newDatasetSlug.trim())
	);
	const canContinue = $derived(
		step === 1
			? Boolean(selectedProject && destinationDatasetSlug && datasetSlugIsValid && releaseIsValid)
			: step === 2
				? layer === 'bronze' || files.length > 0
				: step === 3
					? Boolean(revisionReason.trim() && classification && ownerGroup)
					: true
	);
	const validationMessage = $derived(
		step === 1
			? !selectedProject
				? 'Select an organization with a visible project.'
				: !destinationDatasetSlug || !datasetSlugIsValid
					? 'Choose a dataset or enter a URL-safe dataset identifier.'
					: !releaseIsValid
						? 'Enter a lowercase, URL-safe release identifier.'
						: ''
			: step === 2 && layer === 'raw' && files.length === 0
				? 'Add at least one source file or use the sample manifest.'
				: step === 3 && !revisionReason.trim()
					? 'Describe why this revision is being created.'
					: ''
	);

	$effect(() => {
		const nextProject = orgProjects.some((candidate) => candidate.slug === project)
			? project
			: (orgProjects[0]?.slug ?? '');
		if (project !== nextProject) {
			project = nextProject;
			dataset = '';
		}
	});

	$effect(() => {
		if (
			!dataset ||
			(dataset !== 'new' && !projectDatasets.some((candidate) => candidate.slug === dataset))
		) {
			dataset = projectDatasets[0]?.slug ?? (selectedProject ? 'new' : '');
		}
	});

	function readFiles(list: FileList | null) {
		if (!list) return;
		files = [...new Set([...files, ...Array.from(list).map((file) => file.name)])];
	}

	function handleDrop(event: DragEvent) {
		event.preventDefault();
		readFiles(event.dataTransfer?.files ?? null);
	}

	function next() {
		if (!canContinue) return;
		step = Math.min(4, step + 1);
	}

	function submit() {
		if (submissionId) return;
		const id = `ING-${Date.now().toString().slice(-8)}`;
		const job: IngestJob = {
			id,
			organization: currentOrg?.name ?? 'Unknown organization',
			project: selectedProject?.name ?? project,
			dataset: destinationDatasetName,
			release,
			layer,
			status: 'queued',
			createdAt: new Date().toISOString()
		};
		const existing = JSON.parse(
			sessionStorage.getItem('huron-preview-ingest-jobs') ?? '[]'
		) as IngestJob[];
		sessionStorage.setItem('huron-preview-ingest-jobs', JSON.stringify([job, ...existing]));
		submissionId = id;
		submitted = true;
	}
</script>

<svelte:head><title>Ingestion · Huron</title></svelte:head>

<div class="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
	<div>
		<div
			class="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.11em] text-app-muted"
		>
			<UploadCloud size={14} /> Data ingestion
		</div>
		<h1>Ingest a dataset</h1>
		<p class="mt-2 max-w-2xl text-sm text-app-muted">
			Create an immutable raw revision or materialize a governed bronze snapshot.
		</p>
	</div>
	<a
		href="/queue"
		class="inline-flex items-center gap-1.5 text-sm font-medium text-app-muted hover:text-brand-strong"
		>View ingest activity <ChevronRight size={15} /></a
	>
</div>

{#if submitted}
	<div
		class="mb-5 flex items-start gap-3 rounded-lg border border-[var(--note-line)] bg-[var(--note-bg)] p-4"
		role="status"
	>
		<CheckCircle2 size={20} class="mt-0.5 shrink-0 text-app-success" />
		<div class="flex-1">
			<p class="font-semibold">Ingest queued · {submissionId}</p>
			<p class="mt-1 text-sm text-app-muted">
				The preview job is available in ingest activity. The production API will replace this local
				queue when the ingest-session endpoint is available.
			</p>
			<a href="/queue" class="mt-2 inline-flex text-sm font-semibold text-brand-strong"
				>Open ingest activity →</a
			>
		</div>
		<button type="button" onclick={() => (submitted = false)} aria-label="Dismiss"
			><X size={17} class="text-app-muted" /></button
		>
	</div>
{/if}

<ol
	class="mb-6 grid grid-cols-4 overflow-hidden rounded-lg border border-app-line bg-app-card"
	aria-label="Ingestion progress"
>
	{#each steps as item}
		<li
			class="relative flex items-center gap-2 border-r border-app-line px-3 py-3 last:border-0"
			class:bg-brand-soft={step === item.number}
		>
			<span
				class="grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold"
				class:bg-brand={step >= item.number}
				class:text-[#062d29]={step >= item.number}
				class:border={step < item.number}
				class:border-app-line={step < item.number}
				class:text-app-muted={step < item.number}
			>
				{#if step > item.number}<Check size={13} strokeWidth={3} />{:else}{item.number}{/if}
			</span>
			<span
				class="hidden text-xs font-semibold sm:block"
				class:text-brand-strong={step === item.number}
				class:text-app-muted={step !== item.number}>{item.label}</span
			>
		</li>
	{/each}
</ol>

<div class="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
	<section class="rounded-lg border border-app-line bg-app-card shadow-[var(--shadow-sm)]">
		{#if step === 1}
			<div class="border-b border-app-line p-5 sm:p-6">
				<h2 class="m-0 border-0 p-0 text-lg font-semibold">Choose the destination</h2>
				<p class="mt-1 text-sm text-app-muted">
					Select the catalog location and the layer this ingest will write.
				</p>
			</div>
			<div class="grid gap-5 p-5 sm:p-6">
				<div
					class="flex items-center gap-2 rounded-md border border-app-line bg-app-bg px-3 py-2 text-xs text-app-muted"
				>
					<Building2 size={15} class="text-brand-strong" />
					<span>Organization</span>
					<strong class="text-app-fg">{currentOrg?.name ?? 'No organization selected'}</strong>
				</div>
				<div class="grid gap-4 sm:grid-cols-2">
					<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
						>Project
						<select
							bind:value={project}
							onchange={() => (dataset = '')}
							disabled={orgProjects.length === 0}
							class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg outline-none focus:border-brand-strong"
						>
							{#each orgProjects as option}<option value={option.slug}>{option.name}</option>{/each}
							{#if orgProjects.length === 0}<option value="">No visible projects</option>{/if}
						</select>
					</label>
					<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
						>Dataset
						<select
							bind:value={dataset}
							disabled={!selectedProject}
							class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg outline-none focus:border-brand-strong"
						>
							{#each projectDatasets as option}<option value={option.slug}>{option.name}</option
								>{/each}
							<option value="new">+ Create new dataset</option>
						</select>
					</label>
				</div>
				{#if dataset === 'new'}
					<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
						>New dataset identifier
						<input
							bind:value={newDatasetSlug}
							aria-invalid={!datasetSlugIsValid}
							placeholder="new-dataset"
							class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg outline-none focus:border-brand-strong aria-invalid:border-app-danger"
						/>
						<span class="font-normal">Lowercase letters, numbers, and hyphens.</span>
					</label>
				{/if}
				<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
					>Release identifier
					<input
						bind:value={release}
						aria-invalid={!releaseIsValid}
						class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg outline-none focus:border-brand-strong aria-invalid:border-app-danger"
					/>
					<span class="font-normal"
						>Immutable, URL-safe identifier. Display titles can change later.</span
					>
				</label>

				<fieldset>
					<legend class="mb-2 text-xs font-semibold text-app-muted">Target layer</legend>
					<div class="grid gap-3 sm:grid-cols-2">
						<label
							class="relative flex cursor-pointer gap-3 rounded-lg border p-4 transition"
							class:border-brand-strong={layer === 'raw'}
							class:bg-brand-soft={layer === 'raw'}
							class:border-app-line={layer !== 'raw'}
						>
							<input type="radio" bind:group={layer} value="raw" class="sr-only" />
							<span
								class="grid size-9 shrink-0 place-items-center rounded-md bg-app-card text-[var(--raw)]"
								><FileArchive size={18} /></span
							>
							<span
								><span class="block text-sm font-semibold">Raw</span><span
									class="mt-1 block text-xs leading-5 text-app-muted"
									>Upload source artifacts as an immutable, checksum-verified revision.</span
								></span
							>
							{#if layer === 'raw'}<CircleDot
									size={16}
									class="absolute right-3 top-3 text-brand-strong"
								/>{/if}
						</label>
						<label
							class="relative flex cursor-pointer gap-3 rounded-lg border p-4 transition"
							class:border-brand-strong={layer === 'bronze'}
							class:bg-brand-soft={layer === 'bronze'}
							class:border-app-line={layer !== 'bronze'}
						>
							<input type="radio" bind:group={layer} value="bronze" class="sr-only" />
							<span
								class="grid size-9 shrink-0 place-items-center rounded-md bg-app-card text-[var(--bronze)]"
								><Layers3 size={18} /></span
							>
							<span
								><span class="block text-sm font-semibold">Bronze</span><span
									class="mt-1 block text-xs leading-5 text-app-muted"
									>Materialize canonical Zarr from a committed raw revision.</span
								></span
							>
							{#if layer === 'bronze'}<CircleDot
									size={16}
									class="absolute right-3 top-3 text-brand-strong"
								/>{/if}
						</label>
					</div>
				</fieldset>
			</div>
		{:else if step === 2}
			<div class="border-b border-app-line p-5 sm:p-6">
				<h2 class="m-0 border-0 p-0 text-lg font-semibold">
					{layer === 'raw' ? 'Add source files' : 'Select the raw source'}
				</h2>
				<p class="mt-1 text-sm text-app-muted">
					{layer === 'raw'
						? 'Files are hashed in flight and uploaded directly into the revision prefix.'
						: 'Bronze jobs are pinned to a committed raw revision and a transform digest.'}
				</p>
			</div>
			<div class="p-5 sm:p-6">
				{#if layer === 'raw'}
					<input
						bind:this={fileInput}
						type="file"
						multiple
						class="sr-only"
						onchange={(event) => readFiles(event.currentTarget.files)}
					/>
					<div
						class="rounded-lg border-2 border-dashed border-app-line-strong bg-app-bg px-5 py-10 text-center"
						role="group"
						aria-label="File upload drop zone"
						ondragover={(event) => event.preventDefault()}
						ondrop={handleDrop}
					>
						<CloudUpload size={28} class="mx-auto text-brand-strong" />
						<p class="mt-3 font-semibold">Drop files here or choose from your computer</p>
						<p class="mt-1 text-xs text-app-muted">Up to 10,000 files · 10 GiB maximum per file</p>
						<div class="mt-4 flex justify-center gap-2">
							<button
								type="button"
								onclick={() => fileInput?.click()}
								class="rounded-md bg-[#26333b] px-3 py-2 text-xs font-semibold text-white dark:bg-brand dark:text-[#062d29]"
								>Choose files</button
							>
							<button
								type="button"
								onclick={() =>
									(files = ['inputs/sweep.inp', 'outputs/sweep.out', 'outputs/sweep.msht'])}
								class="rounded-md border border-app-line bg-app-card px-3 py-2 text-xs font-semibold text-app-muted"
								>Use sample manifest</button
							>
						</div>
					</div>
					{#if files.length}
						<div class="mt-4 overflow-hidden rounded-lg border border-app-line">
							{#each files as name, index}
								<div
									class="flex items-center gap-3 border-b border-app-line px-3 py-2.5 last:border-0"
								>
									<File size={15} class="text-app-muted" /><span
										class="min-w-0 flex-1 truncate text-sm">{name}</span
									><span class="text-xs text-app-muted">ready</span><button
										type="button"
										onclick={() => (files = files.filter((_, i) => i !== index))}
										aria-label={`Remove ${name}`}><X size={14} class="text-app-muted" /></button
									>
								</div>
							{/each}
						</div>
					{/if}
				{:else}
					<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
						>Raw revision
						<select
							bind:value={rawRevision}
							class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
							><option value="run-0002-rev-1">run-0002 · revision 1 · committed</option><option
								value="run-0001-rev-2">run-0001 · revision 2 · committed</option
							></select
						>
					</label>
					<div class="mt-4 grid gap-3 sm:grid-cols-2">
						<div class="rounded-lg border border-app-line p-4">
							<div class="flex items-center gap-2 text-sm font-semibold">
								<Braces size={16} class="text-brand-strong" /> Transform
							</div>
							<p class="mt-2 font-mono text-xs text-app-muted">mcnp-to-zarr@sha256:8f14…</p>
						</div>
						<div class="rounded-lg border border-app-line p-4">
							<div class="flex items-center gap-2 text-sm font-semibold">
								<ShieldCheck size={16} class="text-app-success" /> Contract
							</div>
							<p class="mt-2 text-xs text-app-muted">example-profile@1 · compatible</p>
						</div>
					</div>
				{/if}
			</div>
		{:else if step === 3}
			<div class="border-b border-app-line p-5 sm:p-6">
				<h2 class="m-0 border-0 p-0 text-lg font-semibold">Describe this revision</h2>
				<p class="mt-1 text-sm text-app-muted">
					Metadata travels with the data and remains readable outside the platform.
				</p>
			</div>
			<div class="grid gap-4 p-5 sm:grid-cols-2 sm:p-6">
				<label class="grid gap-1.5 text-xs font-semibold text-app-muted sm:col-span-2"
					>Revision reason<input
						bind:value={revisionReason}
						class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
					/></label
				>
				<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
					>Classification<select
						bind:value={classification}
						class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
						><option value="unclassified">Unclassified</option><option value="controlled"
							>Controlled</option
						></select
					></label
				>
				<label class="grid gap-1.5 text-xs font-semibold text-app-muted"
					>Owner group<select
						bind:value={ownerGroup}
						class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
						><option>Science Data Team</option><option>Modeling & Simulation</option></select
					></label
				>
				<label class="grid gap-1.5 text-xs font-semibold text-app-muted sm:col-span-2"
					>Tags<input
						bind:value={tags}
						class="h-10 rounded-md border border-app-line bg-app-bg px-3 text-sm font-normal text-app-fg"
					/></label
				>
				<label class="grid gap-1.5 text-xs font-semibold text-app-muted sm:col-span-2"
					>Notes<textarea
						bind:value={notes}
						rows="4"
						class="rounded-md border border-app-line bg-app-bg p-3 text-sm font-normal text-app-fg"
						placeholder="Optional context for collaborators"
					></textarea></label
				>
			</div>
		{:else}
			<div class="border-b border-app-line p-5 sm:p-6">
				<h2 class="m-0 border-0 p-0 text-lg font-semibold">Review and begin ingest</h2>
				<p class="mt-1 text-sm text-app-muted">
					Huron will reserve the next revision number and validate the manifest before commit.
				</p>
			</div>
			<div class="p-5 sm:p-6">
				<div class="grid gap-3 sm:grid-cols-3">
					<div class="rounded-lg border border-app-line bg-app-bg p-4">
						<p class="text-[10px] font-semibold uppercase tracking-wider text-app-muted">
							Destination
						</p>
						<p class="mt-2 text-sm font-semibold">
							{selectedProject?.name ?? project} / {destinationDatasetName}
						</p>
						<p class="mt-1 text-xs text-app-muted">{release}</p>
					</div>
					<div class="rounded-lg border border-app-line bg-app-bg p-4">
						<p class="text-[10px] font-semibold uppercase tracking-wider text-app-muted">Layer</p>
						<p class="mt-2 text-sm font-semibold capitalize">{layer}</p>
						<p class="mt-1 text-xs text-app-muted">
							{layer === 'raw' ? `${files.length} source files` : `From ${rawRevision}`}
						</p>
					</div>
					<div class="rounded-lg border border-app-line bg-app-bg p-4">
						<p class="text-[10px] font-semibold uppercase tracking-wider text-app-muted">
							Authorization
						</p>
						<p class="mt-2 flex items-center gap-1.5 text-sm font-semibold text-app-success">
							<Check size={15} /> data.write
						</p>
						<p class="mt-1 text-xs text-app-muted">Developer at project scope</p>
					</div>
				</div>
				<div class="mt-4 flex items-start gap-3 rounded-lg border border-app-line bg-app-bg p-4">
					<Info size={17} class="mt-0.5 shrink-0 text-brand-strong" />
					<p class="text-sm text-app-muted">
						An ingest session is exclusive to this dataset while open. The revision remains
						invisible until its payload and sidecars are durable and the COMMITTED marker is written
						last.
					</p>
				</div>
			</div>
		{/if}

		<div
			class="flex flex-wrap items-center justify-between gap-3 border-t border-app-line px-5 py-4 sm:px-6"
		>
			<button
				type="button"
				onclick={() => (step = Math.max(1, step - 1))}
				disabled={step === 1}
				class="inline-flex h-9 items-center gap-2 rounded-md border border-app-line px-3 text-sm font-semibold text-app-muted disabled:cursor-not-allowed disabled:opacity-40"
				><ArrowLeft size={15} /> Back</button
			>
			{#if step < 4}
				{#if validationMessage}<p
						class="order-3 w-full text-xs text-app-danger sm:order-none sm:w-auto"
					>
						{validationMessage}
					</p>{/if}
				<button
					type="button"
					onclick={next}
					disabled={!canContinue}
					class="inline-flex h-9 items-center gap-2 rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29] disabled:cursor-not-allowed disabled:opacity-40"
					>Continue <ArrowRight size={15} /></button
				>
			{:else}
				<button
					type="button"
					onclick={submit}
					disabled={Boolean(submissionId)}
					class="inline-flex h-9 items-center gap-2 rounded-md bg-brand px-3.5 text-sm font-semibold text-[#062d29] disabled:cursor-not-allowed disabled:opacity-55"
					>{#if submissionId}<Check size={15} /> Queued{:else}<LoaderCircle size={15} /> Begin ingest{/if}</button
				>
			{/if}
		</div>
	</section>

	<aside class="sticky top-24 rounded-lg border border-app-line bg-app-card p-4">
		<h2 class="m-0 border-0 p-0 text-sm font-semibold">Ingest summary</h2>
		<dl class="mt-4 grid gap-3 text-xs">
			<div class="flex justify-between gap-4">
				<dt class="text-app-muted">Organization</dt>
				<dd class="font-medium">{currentOrg?.name ?? '—'}</dd>
			</div>
			<div class="flex justify-between gap-4">
				<dt class="text-app-muted">Project</dt>
				<dd class="font-medium">{selectedProject?.name ?? '—'}</dd>
			</div>
			<div class="flex justify-between gap-4">
				<dt class="text-app-muted">Dataset</dt>
				<dd class="font-medium">{destinationDatasetName}</dd>
			</div>
			<div class="flex justify-between gap-4">
				<dt class="text-app-muted">Target layer</dt>
				<dd
					class="font-semibold capitalize"
					class:text-[var(--raw)]={layer === 'raw'}
					class:text-[var(--bronze)]={layer === 'bronze'}
				>
					{layer}
				</dd>
			</div>
		</dl>
		<div class="my-4 border-t border-app-line"></div>
		<div class="flex items-start gap-2">
			<Database size={15} class="mt-0.5 shrink-0 text-app-muted" />
			<p class="text-xs leading-5 text-app-muted">
				Writes are append-only. Corrections create a new revision; committed bytes are never
				replaced in place.
			</p>
		</div>
	</aside>
</div>
