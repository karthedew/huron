<script lang="ts">
	import {
		ArrowLeft,
		ArrowRight,
		Check,
		CheckCircle2,
		FileText,
		UploadCloud,
		X,
		FolderOpen
	} from '@lucide/svelte';
	import { tick, untrack } from 'svelte';
	import { beforeNavigate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import type { PolarisCatalog, HuronOrganizationSummary, RawTargetBranch } from '$api/types';
	import {
		sourcePath,
		sourceError,
		datasetNameError,
		formatBytes,
		type UploadSource
	} from '$lib/ingestion/files';
	import {
		submitRawUpload,
		discardRawUpload,
		canReleaseRejectedDraft,
		type UploadDraft,
		type UploadProgress
	} from '$lib/ingestion/upload';
	import IngestDestinationPicker from './IngestDestinationPicker.svelte';
	let {
		data
	}: {
		data: {
			catalogs: PolarisCatalog[];
			organization: HuronOrganizationSummary | null;
			selectedCatalog: string;
			initialBranch: RawTargetBranch | null;
			initialDataset: string;
			initialDatasetId: string | null;
			ingestError: string | null;
		};
	} = $props();
	let step = $state(1);
	let destinationBusy = $state(false);
	let currentBranch = $state.raw(untrack(() => data.initialBranch));
	let catalog = $state(untrack(() => data.initialBranch?.catalog ?? data.selectedCatalog));
	let namespace = $state.raw(untrack(() => data.initialBranch?.namespace ?? []));
	let name = $state(untrack(() => data.initialDataset));
	let expectedDatasetId = $state(untrack(() => data.initialDatasetId));
	const existing = $derived(expectedDatasetId !== null);
	let files = $state.raw<UploadSource[]>([]);
	let title = $state('');
	let creators = $state('');
	let description = $state('');
	let tags = $state('');
	let source = $state('');
	let search = $state('');
	let draft = $state.raw<UploadDraft | null>(null);
	let busy = $state(false);
	let failure = $state('');
	let progress = $state<UploadProgress>({ phase: '', bytes: 0, total: 0, path: '' });
	let stepHeading = $state<HTMLHeadingElement>();
	let completion = $state<HTMLDivElement>();
	const steps = ['Destination', 'Source', 'Metadata', 'Review'];
	const total = $derived(files.reduce((sum, entry) => sum + entry.file.size, 0));
	const destinationError = $derived(
		!data.catalogs.some((entry) => entry.name === catalog)
			? 'Choose a catalog in this organization.'
			: !namespace.length
				? 'Open an existing namespace for this upload.'
				: !existing && currentBranch?.datasets.some((dataset) => dataset.name === name)
					? 'This dataset already exists. Select it in the explorer to add a revision.'
					: datasetNameError(name)
	);
	const fileError = $derived(sourceError(files));
	const metadataError = $derived(
		!title.trim()
			? 'Enter a title for this revision.'
			: !creators.split('\n').some((value) => value.trim())
				? 'Add at least one creator.'
				: ''
	);
	const validation = $derived(
		step === 1
			? destinationBusy
				? 'Loading the destination…'
				: destinationError
			: step === 2
				? fileError
				: step === 3
					? metadataError
					: ''
	);
	const registered = $derived(draft?.receipt?.registration.state === 'registered');
	const pending = $derived(draft?.receipt?.registration.state === 'pending');
	const locked = $derived(draft !== null);
	const terminal = $derived(
		Boolean(draft?.session && ['FAILED', 'ABORTED'].includes(draft.session.state))
	);
	const canDiscard = $derived(
		!draft?.receipt &&
			(!draft?.session ||
				['UPLOADING', 'VERIFYING', 'FAILED', 'ABORTED'].includes(draft.session.state))
	);
	const browseQuery = $derived(
		new URLSearchParams({
			organization: data.organization?.slug ?? '',
			catalog,
			namespace: JSON.stringify(namespace),
			table: name,
			format: 'raw',
			tab: 'files',
			...(draft?.receipt ? { revision: draft.receipt.id } : {})
		})
	);
	beforeNavigate(({ cancel }) => {
		if (
			locked &&
			!registered &&
			!terminal &&
			!window.confirm('Leave this upload? Keep this page open to retry the same submission.')
		)
			cancel();
	});
	function beforeUnload(event: BeforeUnloadEvent) {
		if (locked && !registered && !terminal) {
			event.preventDefault();
			event.returnValue = '';
		}
	}
	function select(branch: RawTargetBranch, dataset: string) {
		if (locked) return;
		currentBranch = branch;
		catalog = branch.catalog;
		namespace = branch.namespace;
		name = dataset;
		expectedDatasetId = branch.datasets.find((entry) => entry.name === dataset)?.datasetId ?? null;
		failure = '';
	}
	function chooseFiles(event: Event) {
		if (event.currentTarget instanceof HTMLInputElement) {
			files = [
				...files,
				...Array.from(event.currentTarget.files ?? []).map((file) => ({
					id: crypto.randomUUID(),
					file,
					path: sourcePath(file)
				}))
			];
			event.currentTarget.value = '';
		}
	}
	async function move(next: number) {
		if (next > step && validation) return;
		step = next;
		await tick();
		stepHeading?.focus();
	}
	async function upload() {
		if (destinationError || fileError || metadataError || data.ingestError || busy) return;
		failure = '';
		busy = true;
		if (!draft)
			draft = {
				key: crypto.randomUUID(),
				beginUncertain: false,
				expectedDatasetId,
				target: { catalog, namespace: [...namespace], name },
				metadata: {
					title: title.trim(),
					creators: creators
						.split('\n')
						.map((value) => value.trim())
						.filter(Boolean),
					...(description.trim() ? { description: description.trim() } : {}),
					...(tags.trim()
						? {
								tags: [
									...new Set(
										tags
											.split(',')
											.map((value) => value.trim())
											.filter(Boolean)
									)
								]
							}
						: {}),
					...(source.trim() ? { source: { description: source.trim() } } : {})
				},
				sources: [...files],
				manifest: null,
				session: null,
				receipt: null
			};
		const current = draft;
		try {
			await submitRawUpload(
				current,
				(value) => (progress = value),
				() => (draft = { ...current })
			);
			draft = { ...current };
			await tick();
			completion?.focus();
		} catch (error) {
			failure =
				error instanceof Error ? error.message : 'Upload failed. Retry the same submission.';
			if (canReleaseRejectedDraft(current, error)) {
				draft = null;
				progress = { phase: '', bytes: 0, total: 0, path: '' };
			} else draft = { ...current };
		} finally {
			busy = false;
		}
	}
	async function discard() {
		if (!draft || busy) return;
		busy = true;
		failure = '';
		try {
			const current = draft;
			await discardRawUpload(current, () => (draft = { ...current }));
			draft = null;
			progress = { phase: '', bytes: 0, total: 0, path: '' };
		} catch (error) {
			failure = error instanceof Error ? error.message : 'Unable to abandon this upload.';
		} finally {
			busy = false;
		}
	}
</script>

<svelte:window onbeforeunload={beforeUnload} />
<div class="mx-auto grid w-full max-w-6xl gap-6">
	<header>
		<p
			class="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-brand-strong"
		>
			<UploadCloud size={14} />Raw data
		</p>
		<h1>Ingest a dataset</h1>
		<p class="mt-2 text-sm leading-6 text-app-muted">
			Upload files or a directory as a complete, immutable Raw revision.
		</p>
	</header>
	{#if data.ingestError}<p
			role="alert"
			class="rounded-md border border-app-line bg-app-card p-4 text-sm text-app-danger"
		>
			{data.ingestError}
		</p>{/if}
	<ol
		class="grid grid-cols-4 overflow-hidden rounded-lg border border-app-line bg-app-card"
		aria-label="Ingestion progress"
	>
		{#each steps as label, index (label)}<li
				aria-current={step === index + 1 ? 'step' : undefined}
				class={[
					'flex min-w-0 items-center gap-2 border-r border-app-line px-2 py-3 last:border-0 sm:px-4',
					step === index + 1 ? 'bg-brand-soft' : ''
				]}
			>
				<span
					class={[
						'grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold',
						step >= index + 1 ? 'bg-brand text-[#062d29]' : 'border border-app-line text-app-muted'
					]}
					>{#if step > index + 1}<Check size={13} />{:else}{index + 1}{/if}</span
				><span class="truncate text-[10px] font-semibold sm:text-xs">{label}</span>
			</li>{/each}
	</ol>
	<div class="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_280px]">
		<section
			class="min-w-0 rounded-lg border border-app-line bg-app-card shadow-[var(--shadow-sm)]"
			aria-labelledby="ingest-step-heading"
		>
			<div class="border-b border-app-line p-5 sm:p-6">
				<h2
					bind:this={stepHeading}
					id="ingest-step-heading"
					tabindex="-1"
					class="m-0 scroll-mt-20 border-0 p-0 text-lg font-semibold"
				>
					{step === 1
						? 'Choose the destination'
						: step === 2
							? 'Add source files'
							: step === 3
								? 'Describe this revision'
								: 'Review the submission'}
				</h2>
				<p class="mt-2 text-sm text-app-muted">
					{step === 1
						? 'Browse catalogs in your organization and choose a namespace.'
						: step === 2
							? 'Each revision contains all files selected here. Directory paths are preserved.'
							: step === 3
								? 'Record the scientific context for this submission.'
								: 'Files are hashed, uploaded, verified and committed before the dataset is registered in Polaris.'}
				</p>
			</div>
			<div class="grid min-w-0 gap-5 p-5 sm:p-6">
				{#if step === 1}
					<p class="text-sm text-app-muted">
						Organization: <strong class="text-app-fg"
							>{data.organization?.name ?? 'No organization selected'}</strong
						>
					</p>
					<IngestDestinationPicker
						catalogs={data.catalogs}
						initialBranch={currentBranch}
						onloading={(loading) => (destinationBusy = loading)}
						onchange={select}
					/>
					<p class="break-all text-xs text-app-muted">
						Destination: {catalog || 'Choose a catalog'} / {namespace.join(' / ') ||
							'Choose a namespace'}
					</p>
					<div class="flex flex-wrap items-center gap-3 text-xs">
						<span
							>{existing
								? 'Add a revision to an existing Raw dataset'
								: 'Create a new Raw dataset'}</span
						>{#if existing}<button
								type="button"
								class="text-brand-strong underline"
								onclick={() => {
									expectedDatasetId = null;
									name = '';
								}}>New dataset in this namespace</button
							>{/if}
					</div>
					<label class="field"
						>Dataset name<input
							bind:value={name}
							aria-label="Dataset name"
							readonly={existing}
							autocomplete="off"
							placeholder="mission-observations"
						/><span class="field-help"
							>Choose an existing managed dataset in the explorer, or enter a name for a new
							dataset.</span
						></label
					>
					<p
						class="rounded-md border border-app-line bg-app-bg p-4 text-xs leading-5 text-app-muted"
					>
						A new revision contains exactly this submission’s complete files. Files from earlier
						revisions are not carried forward.
					</p>
				{:else if step === 2}
					<div class="grid gap-4 sm:grid-cols-2">
						<label class="field"
							><span class="flex items-center gap-2"><FileText size={15} />Add files</span><input
								type="file"
								multiple
								onchange={chooseFiles}
							/></label
						><label class="field"
							><span class="flex items-center gap-2"><FolderOpen size={15} />Add directory</span
							><input type="file" multiple webkitdirectory onchange={chooseFiles} /></label
						>
					</div>
					<label class="field"
						>Find selected files<input
							type="search"
							bind:value={search}
							placeholder="Search relative paths"
						/></label
					>
					<ul
						class="max-h-80 overflow-auto rounded-md border border-app-line"
						aria-label="Selected files"
					>
						{#each files.filter((entry) => entry.path
								.toLowerCase()
								.includes(search.toLowerCase())) as entry (entry.id)}<li
								class="flex min-w-0 items-start gap-3 border-b border-app-line px-3 py-3 last:border-0"
							>
								<FileText size={15} class="mt-0.5 shrink-0 text-app-muted" />
								<div class="min-w-0 flex-1">
									<p class="break-all font-mono text-xs">{entry.path}</p>
									<p class="mt-1 text-[11px] text-app-muted">{formatBytes(entry.file.size)}</p>
								</div>
								<button
									type="button"
									aria-label={`Remove ${entry.path}`}
									onclick={() => (files = files.filter((file) => file.id !== entry.id))}
									class="shrink-0 rounded p-1 text-app-muted hover:bg-app-hover"
									><X size={15} /></button
								>
							</li>{:else}<li class="p-4 text-xs text-app-muted">
								{files.length ? 'No files match this search.' : 'No source files selected.'}
							</li>{/each}
					</ul>
					<p class="text-xs text-app-muted">
						{files.length} files · {formatBytes(total)}. Empty directories are not included.
					</p>
				{:else if step === 3}
					<label class="field"
						>Revision title<input
							bind:value={title}
							required
							placeholder="ACE solar wind observations — October 2026"
						/></label
					>
					<label class="field"
						>Creators<textarea
							bind:value={creators}
							aria-label="Creators"
							required
							rows="3"
							placeholder="One creator per line"
						></textarea><span class="field-help"
							>People or organizations responsible for these data. Your authenticated account
							records who committed the revision.</span
						></label
					>
					<label class="field"
						>Description<textarea
							bind:value={description}
							rows="4"
							placeholder="Why this revision exists and how the source data were collected"
						></textarea></label
					>
					<label class="field"
						>Tags<input bind:value={tags} placeholder="solar-wind, observations" /><span
							class="field-help">Separate tags with commas.</span
						></label
					>
					<label class="field"
						>Source context<textarea
							bind:value={source}
							rows="2"
							placeholder="Original archive, acquisition URL or instrument"
						></textarea></label
					>
				{:else}
					<dl class="grid gap-4 text-sm">
						<div>
							<dt class="text-xs text-app-muted">Dataset</dt>
							<dd class="mt-1 break-all font-mono text-xs">
								{catalog} / {namespace.join(' / ')} / {name}
							</dd>
						</div>
						<div>
							<dt class="text-xs text-app-muted">Revision title</dt>
							<dd class="mt-1 break-words">{title}</dd>
						</div>
						<div>
							<dt class="text-xs text-app-muted">Creators</dt>
							<dd class="mt-1 whitespace-pre-line break-words">{creators}</dd>
						</div>
						<div>
							<dt class="text-xs text-app-muted">Complete submission</dt>
							<dd class="mt-1">{files.length} files · {formatBytes(total)}</dd>
						</div>
						{#if description}<div>
								<dt class="text-xs text-app-muted">Description</dt>
								<dd class="mt-1 whitespace-pre-line break-words">{description}</dd>
							</div>{/if}
					</dl>
					<p class="text-xs leading-5 text-app-muted">
						Keep this page open while uploading. If a request fails, retry here to resume the same
						submission. File contents are never stored in browser local storage.
					</p>
					{#if progress.phase}<div
							role="status"
							aria-live="polite"
							class="rounded-md border border-app-line bg-app-bg p-4"
						>
							<p class="text-sm font-medium">{progress.phase}</p>
							{#if progress.phase === 'Calculating checksums' || progress.phase === 'Transferring files'}<progress
									aria-label={progress.phase}
									max={Math.max(progress.total, 1)}
									value={progress.bytes}
									class="mt-3 w-full accent-brand"
								></progress>
								<p class="mt-1 text-xs text-app-muted">
									{formatBytes(progress.bytes)} / {formatBytes(progress.total)}
								</p>{/if}{#if progress.path}<p
									class="mt-2 break-all font-mono text-[11px] text-app-muted"
								>
									{progress.path}
								</p>{/if}{#if draft?.session}<p class="mt-2 break-all text-[11px] text-app-muted">
									Upload {draft.session.id}
								</p>{/if}
						</div>{/if}
					{#if registered}<div
							bind:this={completion}
							tabindex="-1"
							role="status"
							class="rounded-md border border-brand-strong bg-brand-soft p-4"
						>
							<p class="flex items-center gap-2 text-sm font-semibold text-brand-strong">
								<CheckCircle2 size={18} />Revision {draft?.receipt?.number} committed and registered
							</p>
							<p class="mt-2 text-xs leading-5">
								The immutable files are readable and the Raw dataset is registered in Polaris.
							</p>
							<a
								href={resolve(`/browse?${browseQuery}`)}
								class="mt-3 inline-flex text-sm font-medium text-brand-strong underline"
								>Browse uploaded files</a
							>
						</div>{:else if pending}<div
							bind:this={completion}
							tabindex="-1"
							role="status"
							class="rounded-md border border-app-line bg-app-bg p-4 text-sm"
						>
							<p class="font-semibold">Revision committed; Polaris registration pending</p>
							<p class="mt-2 text-xs leading-5">
								{draft?.receipt?.registration.error ??
									'Retry registration to make this committed revision available in Browse. Files will not be uploaded again.'}
							</p>
						</div>{/if}
				{/if}
				{#if validation}<p class="text-xs leading-5 text-app-muted">{validation}</p>{/if}
				{#if failure}<p
						role="alert"
						class="rounded-md border border-app-line p-3 text-sm text-app-danger"
					>
						{failure}
					</p>{/if}
			</div>
			<footer
				class="flex flex-wrap items-center justify-between gap-3 border-t border-app-line px-5 py-4 sm:px-6"
			>
				<button
					type="button"
					onclick={() => move(step - 1)}
					disabled={step === 1 || locked}
					class="button-secondary"><ArrowLeft size={15} />Back</button
				>{#if step < 4}<button
						type="button"
						onclick={() => move(step + 1)}
						disabled={Boolean(validation) || Boolean(data.ingestError)}
						class="button-primary">Continue<ArrowRight size={15} /></button
					>{:else if !registered}<div class="flex flex-wrap gap-2">
						{#if locked && !busy && canDiscard}<button
								type="button"
								onclick={discard}
								class="button-secondary"
								>{terminal ? 'Edit a new submission' : 'Abandon upload and edit'}</button
							>{/if}<button
							type="button"
							onclick={upload}
							disabled={busy ||
								terminal ||
								Boolean(destinationError || fileError || metadataError || data.ingestError)}
							class="button-primary"
							><UploadCloud size={15} />{busy
								? 'Uploading…'
								: pending
									? 'Retry registration'
									: locked
										? 'Retry upload'
										: 'Upload and commit'}</button
						>
					</div>{/if}
			</footer>
		</section>
		<aside class="min-w-0 rounded-lg border border-app-line bg-app-card p-5">
			<h2 class="m-0 border-0 p-0 text-sm font-semibold">Submission</h2>
			<dl class="mt-4 grid gap-4 text-xs">
				<div>
					<dt class="text-app-muted">Organization</dt>
					<dd class="mt-1 break-all">{data.organization?.name ?? 'None selected'}</dd>
				</div>
				<div>
					<dt class="text-app-muted">Catalog</dt>
					<dd class="mt-1 break-all">{catalog || 'Not selected'}</dd>
				</div>
				<div>
					<dt class="text-app-muted">Namespace</dt>
					<dd class="mt-1 break-all">{namespace.join(' / ') || 'Not selected'}</dd>
				</div>
				<div>
					<dt class="text-app-muted">Dataset</dt>
					<dd class="mt-1 break-all">{name || 'Not named'}</dd>
				</div>
				<div>
					<dt class="text-app-muted">Files</dt>
					<dd class="mt-1">{files.length} · {formatBytes(total)}</dd>
				</div>
				<div>
					<dt class="text-app-muted">Storage model</dt>
					<dd class="mt-1">Raw · independent immutable revisions</dd>
				</div>
			</dl>
		</aside>
	</div>
</div>

<style>
	.field {
		display: flex;
		min-width: 0;
		flex-direction: column;
		gap: 0.5rem;
		font-size: 0.75rem;
		font-weight: 600;
	}
	.field input,
	.field textarea {
		min-width: 0;
		width: 100%;
		border: 1px solid var(--line);
		border-radius: 0.375rem;
		background: var(--bg);
		padding: 0.65rem 0.75rem;
		color: var(--fg);
		font: inherit;
		font-weight: 400;
	}
	.field input:focus,
	.field textarea:focus {
		outline: 2px solid var(--brand);
		outline-offset: 2px;
	}
	.field-help {
		font-size: 0.7rem;
		font-weight: 400;
		line-height: 1.5;
		color: var(--muted);
	}
	.button-primary,
	.button-secondary {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
		border-radius: 0.375rem;
		padding: 0.65rem 0.85rem;
		font-size: 0.75rem;
		font-weight: 600;
	}
	.button-primary {
		background: var(--brand);
		color: #062d29;
	}
	.button-secondary {
		border: 1px solid var(--line);
		color: var(--fg);
	}
	button:disabled {
		cursor: not-allowed;
		opacity: 0.45;
	}
	button:focus-visible,
	a:focus-visible {
		outline: 2px solid var(--brand);
		outline-offset: 3px;
	}
</style>
