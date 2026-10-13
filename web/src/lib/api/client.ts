/**
 * THE SEAM. The whole app codes against this module and nothing else.
 *
 * Legacy scientific views read from `fixtures.ts`. Raw ingestion uses the authenticated
 * same-origin API below. Live Raw data never falls back to fixtures.
 * See ./README.md.
 */

import * as fixtures from './fixtures';
import { NotFound } from './types';
import type {
	ApiKey,
	Dataset,
	IngestJob,
	ManifestEntry,
	Organization,
	OrganizationMember,
	Page,
	PermissionGrant,
	Project,
	Release,
	Revision,
	SearchResults,
	WhoAmI
} from './types';

/** Every list endpoint is keyset-paginated; fixtures return a single full page. */
const onePage = <T>(items: T[]): Page<T> => ({ items, nextCursor: null, prevCursor: null });

export async function listOrganizations(): Promise<Page<Organization>> {
	return onePage(fixtures.organizations);
}

export async function getOrganization(orgSlug: string): Promise<Organization> {
	const org = fixtures.organizations.find((o) => o.slug === orgSlug);
	if (!org) throw new NotFound(`organization ${orgSlug}`);
	return org;
}

export async function listProjects(orgSlug: string): Promise<Page<Project>> {
	return onePage(fixtures.projects.filter((p) => p.orgSlug === orgSlug));
}

export async function getProject(orgSlug: string, projectSlug: string): Promise<Project> {
	const project = fixtures.projects.find((p) => p.orgSlug === orgSlug && p.slug === projectSlug);
	if (!project) throw new NotFound(`project ${orgSlug}/${projectSlug}`);
	return project;
}

export async function listDatasets(orgSlug: string, projectSlug: string): Promise<Page<Dataset>> {
	return onePage(
		fixtures.datasets.filter((d) => d.orgSlug === orgSlug && d.projectSlug === projectSlug)
	);
}

export async function listIngestJobs(): Promise<Page<IngestJob>> {
	return onePage(fixtures.ingestJobs);
}

export async function getDataset(
	orgSlug: string,
	projectSlug: string,
	datasetSlug: string
): Promise<Dataset> {
	const dataset = fixtures.datasets.find(
		(d) => d.orgSlug === orgSlug && d.projectSlug === projectSlug && d.slug === datasetSlug
	);
	if (!dataset) throw new NotFound(`dataset ${orgSlug}/${projectSlug}/${datasetSlug}`);
	return dataset;
}

export async function listReleases(
	orgSlug: string,
	projectSlug: string,
	datasetSlug: string
): Promise<Page<Release>> {
	return onePage(
		fixtures.releases.filter(
			(r) => r.orgSlug === orgSlug && r.projectSlug === projectSlug && r.datasetSlug === datasetSlug
		)
	);
}

export async function getRelease(
	orgSlug: string,
	projectSlug: string,
	datasetSlug: string,
	releaseSlug: string
): Promise<Release> {
	const release = fixtures.releases.find(
		(r) =>
			r.orgSlug === orgSlug &&
			r.projectSlug === projectSlug &&
			r.datasetSlug === datasetSlug &&
			r.slug === releaseSlug
	);
	if (!release) throw new NotFound(`release ${releaseSlug}`);
	return release;
}

export async function listRevisions(releaseSlug: string): Promise<Page<Revision>> {
	return onePage(fixtures.revisions[releaseSlug] ?? []);
}

export async function getRevision(releaseSlug: string, number: number): Promise<Revision> {
	const revision = (fixtures.revisions[releaseSlug] ?? []).find((r) => r.number === number);
	if (!revision) throw new NotFound(`revision ${number}`);
	return revision;
}

export async function getManifest(
	releaseSlug: string,
	revisionNumber: number
): Promise<Page<ManifestEntry>> {
	await getRevision(releaseSlug, revisionNumber);
	return onePage(fixtures.manifest);
}

export async function search(query: string): Promise<SearchResults> {
	if (!query.trim()) {
		return { ...fixtures.searchResults, hits: [], facets: {} };
	}
	return fixtures.searchResults;
}

export async function listApiKeys(): Promise<Page<ApiKey>> {
	return onePage(fixtures.apiKeys);
}

export async function getWhoAmI(): Promise<WhoAmI> {
	return fixtures.whoami;
}

export async function listOrganizationMembers(_orgSlug: string): Promise<Page<OrganizationMember>> {
	return onePage(fixtures.organizationMembers);
}

export async function listOrganizationPermissions(
	_orgSlug: string
): Promise<Page<PermissionGrant>> {
	return onePage(fixtures.organizationPermissions);
}

export async function listProjectPermissions(
	_orgSlug: string,
	_projectSlug: string
): Promise<Page<PermissionGrant>> {
	return onePage(fixtures.projectPermissions);
}

export { NotFound };

export {
	RawApiError,
	browseRawTargets,
	beginRawUpload,
	getRawUpload,
	uploadRawPart,
	completeRawFile,
	operateRawUpload,
	commitRawUpload,
	registerRawUpload,
	listRawRevisions,
	rawFileDownloadUrl
} from './raw-ingestion-client';
