import {apiClient} from "../../../lib/api/client";
import {clearAccessToken, getAccessToken, setAccessToken} from "../../../lib/auth/tokens";
import type {AuthUser} from "../../../lib/api/client";

interface ApiEnvelope<TPayload> {
  readonly data: TPayload;
}

interface ApiErrorPayload {
  readonly error?: {
    readonly code?: string;
    readonly message?: string;
  };
}

export interface SocialLinksInput {
  readonly instagram?: string;
  readonly linkedin?: string;
  readonly tiktok?: string;
  readonly website?: string;
}

export interface RegisterOptions {
  readonly avatar_constraints: {
    readonly accepted_mime_types: string[];
    readonly max_file_size_bytes: number;
  };
  readonly countries: Array<{
    readonly code: string;
    readonly name: string;
  }>;
  readonly genders: string[];
  readonly social_link_keys: string[];
}

export interface RegisterPayload {
  readonly avatar_url: string;
  readonly country: string;
  readonly date_of_birth: string;
  readonly display_name: string;
  readonly email: string;
  readonly gender: string;
  readonly password: string;
  readonly social_links?: SocialLinksInput;
  readonly username: string;
}

export interface ProfileCompletionPayload {
  readonly avatar_url: string;
  readonly country: string;
  readonly date_of_birth: string;
  readonly display_name: string;
  readonly gender: string;
  readonly social_links?: SocialLinksInput;
  readonly username: string;
}

export interface UsernameAvailability {
  readonly available: boolean;
  readonly username: string;
}

export interface AvatarUploadTarget {
  readonly public_url: string;
  readonly upload_url: string;
}

export class ApiError extends Error {
  readonly code: string | null;

  constructor(message: string, code: string | null = null) {
    super(message);
    this.code = code;
  }
}

/** Extracts a human-readable error string from an opaque API error object. */
function extractApiError(error: unknown, fallback: string): ApiError {
  if (error && typeof error === "object") {
    if ("detail" in error) {
      const detail = (error as {detail: unknown}).detail;
      if (typeof detail === "string") {
        return new ApiError(detail);
      }
    }

    const payload = error as ApiErrorPayload;
    if (payload.error?.message) {
      return new ApiError(payload.error.message, payload.error.code ?? null);
    }
  }

  return new ApiError(fallback);
}

async function fetchJson<TPayload>(
  input: RequestInfo | URL,
  init: RequestInit,
  fallbackMessage: string,
): Promise<TPayload> {
  const response = await fetch(input, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });

  const hasJsonBody = response.headers.get("content-type")?.includes("application/json");
  const payload = hasJsonBody ? ((await response.json()) as ApiEnvelope<TPayload> & ApiErrorPayload) : null;
  if (!response.ok) {
    throw extractApiError(payload, fallbackMessage);
  }

  if (!payload) {
    throw new ApiError(fallbackMessage);
  }

  return payload.data;
}

/** Shape returned inside the data envelope on successful login. */
export interface LoginResponseData {
  readonly access_token: string;
  readonly expires_in: number;
  readonly user: AuthUser;
}

/**
 * Authenticates with email and password.
 * Stores the returned access token in memory; the refresh token cookie is set
 * by the server via Set-Cookie.
 */
export async function loginWithPassword(email: string, password: string): Promise<LoginResponseData> {
  const response = await apiClient.POST("/api/v1/auth/login", {
    body: {email, password},
  });

  if (response.error || !response.data) {
    throw extractApiError(response.error, "Invalid email or password.");
  }

  const data = (response.data as unknown as ApiEnvelope<LoginResponseData>).data;
  setAccessToken(data.access_token);
  return data;
}

/**
 * Revokes the current session and clears the in-memory access token.
 * Clears the token unconditionally so the client never stays in a stale
 * authenticated state even if the network request fails.
 */
export async function logoutSession(): Promise<void> {
  try {
    await apiClient.POST("/api/v1/auth/logout", {});
  } finally {
    clearAccessToken();
  }
}

/**
 * Confirms an email address using the signed token from the verification email.
 */
export async function verifyEmail(token: string): Promise<void> {
  const response = await apiClient.GET("/api/v1/auth/verify-email/{token}", {
    params: {path: {token}},
  });

  if (response.error) {
    throw extractApiError(response.error, "This verification link is invalid or has expired.");
  }
}

/**
 * Dispatches a password-reset email for the given address.
 * Always resolves (server returns 202 regardless of whether the address is
 * registered) to prevent account enumeration.
 */
export async function forgotPassword(email: string): Promise<void> {
  await apiClient.POST("/api/v1/auth/forgot-password", {body: {email}});
}

/**
 * Applies a new password using the signed reset token from the recovery email.
 */
export async function resetPassword(token: string, password: string): Promise<void> {
  const response = await apiClient.POST("/api/v1/auth/reset-password/{token}", {
    params: {path: {token}},
    body: {password},
  });

  if (response.error) {
    throw extractApiError(response.error, "This reset link is invalid or has expired.");
  }
}

export async function resendVerificationEmail(email: string): Promise<void> {
  await fetchJson("/api/v1/auth/resend-verification", {
    method: "POST",
    body: JSON.stringify({email}),
  }, "The verification email could not be resent.");
}

export async function fetchRegisterOptions(): Promise<RegisterOptions> {
  return fetchJson<RegisterOptions>("/api/v1/auth/register-options", {
    method: "GET",
  }, "Registration options could not be loaded.");
}

export async function checkUsernameAvailability(username: string): Promise<UsernameAvailability> {
  const params = new URLSearchParams({username});
  return fetchJson<UsernameAvailability>(`/api/v1/auth/username-availability?${params.toString()}`, {
    method: "GET",
  }, "Username availability could not be checked.");
}

export async function requestAvatarUpload(file: File): Promise<AvatarUploadTarget> {
  return fetchJson<AvatarUploadTarget>("/api/v1/auth/avatar/upload-url", {
    method: "POST",
    body: JSON.stringify({
      file_name: file.name,
      mime_type: file.type,
      file_size: file.size,
    }),
  }, "Avatar upload could not be initiated.");
}

export async function uploadAvatar(file: File): Promise<string> {
  const target = await requestAvatarUpload(file);
  const uploadResponse = await fetch(target.upload_url, {
    method: "PUT",
    headers: {
      "Content-Type": file.type,
    },
    body: file,
  });

  if (!uploadResponse.ok) {
    throw new ApiError("Avatar upload failed. Please try again.");
  }

  return target.public_url;
}

export async function registerStudent(payload: RegisterPayload): Promise<AuthUser> {
  return fetchJson<AuthUser>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  }, "Registration failed. Please try again.");
}

export async function completeProfile(payload: ProfileCompletionPayload): Promise<AuthUser> {
  return fetchJson<AuthUser>("/api/v1/users/me", {
    method: "PATCH",
    body: JSON.stringify(payload),
    headers: {
      Authorization: `Bearer ${getAccessToken() ?? ""}`,
    },
  }, "Profile completion failed. Please try again.");
}
