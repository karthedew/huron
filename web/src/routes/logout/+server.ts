import { redirect, type RequestHandler } from '@sveltejs/kit';
import { clearPreviewSession } from '$lib/server/auth';

export const POST: RequestHandler = ({ cookies }) => {
	clearPreviewSession(cookies);
	redirect(303, '/login?status=signed-out');
};
