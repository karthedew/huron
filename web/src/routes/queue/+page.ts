import { listIngestJobs } from '$api/client';
import type { PageLoad } from './$types';

export const load: PageLoad = async () => ({ jobs: (await listIngestJobs()).items });
