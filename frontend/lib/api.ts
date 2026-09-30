const DEFAULT_API_URL = "https://gridsense-backend-k8pa.onrender.com";

// Set NEXT_PUBLIC_API_URL (e.g. http://localhost:8000) to point at another backend.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL).replace(/\/+$/, "");

// The free Render tier can take up to a minute to wake up.
const REQUEST_TIMEOUT_MS = 90_000;

export class ApiError extends Error {}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);
  signal?.addEventListener("abort", () => controller.abort(), { once: true });

  try {
    const response = await fetch(`${API_URL}${path}`, { signal: controller.signal });
    if (!response.ok) {
      throw new ApiError(`${path} returned HTTP ${response.status}`);
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (signal?.aborted) throw error; // caller cancelled on purpose
    if (timedOut) throw new ApiError(`${path} timed out`);
    throw new ApiError(`could not reach the API for ${path}`);
  } finally {
    clearTimeout(timer);
  }
}
