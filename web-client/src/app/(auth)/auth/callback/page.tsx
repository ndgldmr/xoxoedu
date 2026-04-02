"use client";

import { Suspense } from "react";
import { useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/stores/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Google OAuth callback handler.
 * The backend redirects here after the user consents.
 * We forward the code + state to the backend token exchange endpoint,
 * then store the resulting access token and redirect to the app.
 */
function OAuthCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setAuth = useAuthStore((s) => s.setAuth);
  const called = useRef(false);

  useEffect(() => {
    if (called.current) return;
    called.current = true;

    const code = searchParams.get("code");
    const state = searchParams.get("state");
    const error = searchParams.get("error");

    if (error || !code) {
      router.replace(`/login?error=${encodeURIComponent(error ?? "oauth_failed")}`);
      return;
    }

    const params = new URLSearchParams();
    params.set("code", code);
    if (state) params.set("state", state);

    fetch(`${API_URL}/api/v1/auth/google/callback?${params.toString()}`, {
      credentials: "include",
    })
      .then(async (res) => {
        if (!res.ok) throw new Error("OAuth exchange failed");
        const data = (await res.json()) as {
          access_token: string;
          user: import("@/stores/auth").AuthUser;
        };
        setAuth(data.access_token, data.user);
        router.replace("/courses");
      })
      .catch(() => {
        router.replace("/login?error=oauth_failed");
      });
  }, [searchParams, router, setAuth]);

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-8 text-center">
      <p className="text-sm text-gray-500">Completing sign-in…</p>
    </div>
  );
}

export default function OAuthCallbackPage() {
  return (
    <Suspense>
      <OAuthCallbackContent />
    </Suspense>
  );
}
