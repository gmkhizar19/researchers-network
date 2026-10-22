/**
 * Fetch wrapper for the FastAPI backend.
 *
 * The base URL is configurable (`.env.local` -> VITE_API_BASE) so the same build
 * can talk to a local or deployed API. Errors carry the API's own detail text,
 * which is what the UI shows instead of a generic "something went wrong".
 */

export const API_BASE = (
  import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");

export async function getJSON(path) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`);
  } catch {
    throw new Error(
      `Cannot reach the API at ${API_BASE}. Start it with "uvicorn backend.main:app".`,
    );
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) {
        detail = body.detail;
      }
    } catch {
      // The error body was not JSON; keep the status line.
    }
    throw new Error(detail);
  }

  return response.json();
}
