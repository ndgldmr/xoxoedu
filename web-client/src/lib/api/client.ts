import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./types";
import { useAuthStore } from "@/stores/auth";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const apiClient = createClient<paths>({
  baseUrl: BASE_URL,
  credentials: "include", // send httpOnly refresh-token cookie automatically
});

// Inject access token on every outgoing request
const authMiddleware: Middleware = {
  onRequest({ request }) {
    const token = useAuthStore.getState().accessToken;
    if (token) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }
    return request;
  },
};

// Silent token refresh on 401: retry once with a new access token.
// A shared promise prevents concurrent refreshes (mutex pattern).
let refreshingPromise: Promise<string | null> | null = null;

async function silentRefresh(): Promise<string | null> {
  if (refreshingPromise) return refreshingPromise;

  refreshingPromise = (async () => {
    try {
      const res = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) return null;
      const data = (await res.json()) as { access_token: string; user: import("@/stores/auth").AuthUser };
      useAuthStore.getState().setAuth(data.access_token, data.user);
      return data.access_token;
    } catch {
      return null;
    } finally {
      refreshingPromise = null;
    }
  })();

  return refreshingPromise;
}

const refreshMiddleware: Middleware = {
  async onResponse({ response, request }) {
    if (response.status !== 401) return response;

    const newToken = await silentRefresh();
    if (!newToken) {
      useAuthStore.getState().clearAuth();
      // Redirect to login only in browser context
      if (typeof window !== "undefined") {
        window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
      }
      return response;
    }

    // Retry the original request with the refreshed token
    const retried = new Request(request, {
      headers: { ...Object.fromEntries(request.headers), Authorization: `Bearer ${newToken}` },
    });
    return fetch(retried);
  },
};

apiClient.use(authMiddleware);
apiClient.use(refreshMiddleware);
