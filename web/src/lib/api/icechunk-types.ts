export interface IcechunkReference {
	name: string;
	snapshotId: string;
}

export interface IcechunkSnapshot {
	id: string;
	parentId: string | null;
	writtenAt: string;
	message: string;
	metadata: Record<string, unknown>;
}

export interface IcechunkArraySchema {
	path: string;
	dtype: string;
	shape: number[];
	dimensions: (string | null)[];
	chunks: number[];
	attributes: Record<string, unknown>;
}

/** Authorized metadata projection; storage credentials and chunk values never enter this DTO. */
export interface IcechunkInspection {
	state: 'available' | 'unavailable';
	message: string | null;
	storage: 'FILE' | 'remote' | 'unknown';
	selectedBranch: string | null;
	branches: IcechunkReference[];
	tags: IcechunkReference[];
	snapshot: IcechunkSnapshot | null;
	groups: { path: string; attributes: Record<string, unknown> }[];
	arrays: IcechunkArraySchema[];
	history: IcechunkSnapshot[];
	historyNextSnapshotId: string | null;
	provenance: {
		importReceipt: Record<string, unknown> | null;
		source: Record<string, unknown>;
	} | null;
	lineage: { state: 'unavailable'; message: string };
	truncated: boolean;
	redacted: boolean;
	limits: { references: number; history: number; schema: number };
}
