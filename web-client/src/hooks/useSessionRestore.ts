"use client";

import { useEffect } from "react";
import { useAuthStore, type AuthUser } from "@/stores/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * On mount, attempts a silent token refresh using the httpOnly refresh cookie.
 * If successful, hydrates the in-memory auth store without requiring a login redirect.
 * Call this once in the root layout.
 */
export function useSessionRestore() {
  const setAuth = useAuthStore((s) => s.setAuth);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
      .then(async (res) => {
        if (!res.ok) return;
        const data = (await res.json()) as { access_token: string; user: AuthUser };
        setAuth(data.access_token, data.user);
      })
      .catch(() => {
        // No valid refresh cookie — user is unauthenticated, do nothing
      });
  }, [setAuth]);
}
