import { caseFold } from 'unicode-case-folding';
export interface UploadSource {
	id: string;
	path: string;
	file: File;
}

/** Directory paths survive intact; the Raw envelope owns its payload prefix. */
export function sourcePath(file: Pick<File, 'name' | 'webkitRelativePath'>): string {
	return `payload/${file.webkitRelativePath || file.name}`.normalize('NFC');
}
export function sourceError(files: { path: string; file: Pick<File, 'size'> }[]): string {
	if (!files.length) return 'Add at least one file or directory.';
	if (files.length > 10000) return 'A revision can contain at most 10,000 files.';
	const paths = new Set<string>();
	const folded = new Set<string>();
	for (const entry of files) {
		if (
			new TextEncoder().encode(entry.path).length > 1024 ||
			!entry.path.startsWith('payload/') ||
			/[\x00-\x1f\x7f\\]/.test(entry.path) ||
			entry.path.split('/').some((part) => !part || part === '.' || part === '..')
		)
			return `Invalid source path: ${entry.path}`;
		if (folded.has(caseFold(entry.path.normalize('NFC'))))
			return `Duplicate source path: ${entry.path}. Remove or rename one of these files.`;
		paths.add(entry.path);
		folded.add(caseFold(entry.path.normalize('NFC')));
	}
	for (const path of paths) {
		const parts = path.split('/');
		for (let index = 1; index < parts.length; index++) {
			const prefix = parts.slice(0, index).join('/');
			if (folded.has(caseFold(prefix.normalize('NFC'))))
				return `A file and directory share the path ${prefix}.`;
		}
	}
	return '';
}
export function datasetNameError(value: string): string {
	return !value.trim() ||
		value.length > 255 ||
		/[\x00-\x1f\x7f/\\]/.test(value) ||
		['.', '..'].includes(value)
		? 'Enter a dataset name without slashes or control characters.'
		: '';
}
export function formatBytes(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
	if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
	return `${(bytes / 1024 ** 3).toFixed(2)} GiB`;
}
