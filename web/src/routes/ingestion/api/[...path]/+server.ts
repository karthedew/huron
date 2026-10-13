import type { RequestHandler } from '@sveltejs/kit';
import { handleRawApi } from '$lib/server/raw-api';

export const GET: RequestHandler = handleRawApi;
export const POST: RequestHandler = handleRawApi;
export const PUT: RequestHandler = handleRawApi;
