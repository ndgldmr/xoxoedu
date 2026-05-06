import createClient, {type Middleware} from "openapi-fetch";

import {clearAccessToken, getAccessToken, setAccessToken} from "../auth/tokens";
import type {paths} from "./schema";

type ApiEnvelope<TPayload> = {
  readonly data: TPayload;
};

export interface AuthUser {
  readonly avatar_url: string | null;
  readonly display_name: string | null;
  readonly date_of_birth: string | null;
  readonly email: string;
  readonly email_verified: boolean;
  readonly gender: string | null;
  readonly gender_self_describe: string | null;
  readonly id: string;
  readonly profile_complete: boolean;
  readonly role: string;
  readonly social_links: {
    readonly instagram?: string | null;
    readonly linkedin?: string | null;
    readonly tiktok?: string | null;
    readonly website?: string | null;
  } | null;
  readonly country: string | null;
  readonly username: string;
}

// The backend currently exposes ``/users/me`` as a generic JSON object in the
// generated OpenAPI output, so WC-00 keeps a narrow local bootstrap shape here.
type CurrentUserResponse = ApiEnvelope<AuthUser>;

let authFailureHandler: (() => void) | null = null;

export function setAuthFailureHandler(handler: (() => void) | null): void {
  authFailureHandler = handler;
}

export async function refreshAccessToken(): Promise<string | null> {
  const refreshResponse = await fetch("/api/v1/auth/refresh", {
    method: "POST",
    credentials: "include",
  });

  if (!refreshResponse.ok) {
    clearAccessToken();
    authFailureHandler?.();
    return null;
  }

  const json = (await refreshResponse.json()) as ApiEnvelope<{
    readonly access_token: string;
  }>;
  setAccessToken(json.data.access_token);
  return json.data.access_token;
}

export const authMiddleware: Middleware = {
  async onRequest({request}) {
    const token = getAccessToken();
    if (token) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }
    return request;
  },

  async onResponse({request, response}) {
    if (response.status !== 401 || request.headers.has("x-retried")) {
      return response;
    }

    const refreshedToken = await refreshAccessToken();
    if (!refreshedToken) {
      return response;
    }

    const retriedRequest = new Request(request, {
      headers: new Headers(request.headers),
    });
    retriedRequest.headers.set("Authorization", `Bearer ${refreshedToken}`);
    retriedRequest.headers.set("x-retried", "1");
    return fetch(retriedRequest);
  },
};

export const apiClient = createClient<paths>({
  baseUrl: "/",
  credentials: "include",
});

apiClient.use(authMiddleware);

export async function fetchCurrentUser(): Promise<AuthUser> {
  const response = await apiClient.GET("/api/v1/users/me");
  if (response.error || !response.data) {
    throw new Error("Failed to load the current user.");
  }

  return (response.data as CurrentUserResponse).data;
}
