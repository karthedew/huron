/** Browser-safe contracts for the authenticated Raw bridge. */
export interface RawTarget {
	organization: string;
	catalog: string;
	namespace: string[];
	name: string;
}
export interface RawManifestFile {
	path: string;
	size: number;
	sha256: string;
	media_type: string;
}
export interface RawRevisionMetadata {
	title: string;
	creators: string[];
	description?: string;
	tags?: string[];
	source?: Record<string, unknown>;
}
export interface RawIngestFile {
	file_id: string;
	path: string;
	size: number;
	expected_sha256: string;
	action: string;
	part_count: number;
	state: string;
	completed_parts: number[];
}
export interface RawRegistration {
	state: 'pending' | 'registered';
	dataset_id: string;
	revision_id: string;
	error?: string;
}
export interface RawIngestSession {
	id: string;
	dataset_id: string;
	revision_id: string;
	revision_number: number;
	state: string;
	etag: number;
	expires_at: string;
	created_by: string;
	manifest_sha256: string;
	part_bytes: number;
	files: RawIngestFile[];
	registration: RawRegistration | null;
}
export interface RawRevision {
	id: string;
	dataset_id: string;
	number: number;
	manifest_sha256: string;
	metadata_sha256: string;
	file_count: number;
	total_bytes: number;
	committed_by: string;
	committed_at: string;
}
export interface RawCommitReceipt extends RawRevision {
	registration: RawRegistration;
}
export interface RawRevisionPage {
	revisions: RawRevision[];
	next_before: number | null;
}
export interface RawRevisionManifest {
	schema: string;
	hash_algorithm: string;
	files: RawManifestFile[];
}
export interface RawTargetBranch {
	catalog: string;
	namespace: string[];
	folders: string[][];
	datasets: { name: string; datasetId: string | null }[];
	nextNamespacePageToken: string | null;
	nextDatasetPageToken: string | null;
}
export type RawInspection =
	| {
			state: 'managed';
			datasetId: string;
			revisions: RawRevisionPage;
			selectedRevision: RawRevision | null;
			manifest: RawRevisionManifest | null;
			error: string | null;
	  }
	| { state: 'unmanaged' };

/** A confirmed pre-forward rejection can release a browser draft safely. */
export interface RawErrorResponse {
	message: string;
	uploadNotStarted?: boolean;
}
