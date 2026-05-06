import {afterEach, describe, expect, it, vi} from "vitest";

import {
  authMiddleware,
  refreshAccessToken,
  setAuthFailureHandler,
} from "../../lib/api/client";
import {clearAccessToken, getAccessToken, setAccessToken} from "../../lib/auth/tokens";

describe("auth middleware", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    setAuthFailureHandler(null);
    clearAccessToken();
  });

  it("injects the in-memory access token onto outgoing requests", async () => {
    setAccessToken("token-123");
    const request = new Request("http://localhost/api/v1/users/me");

    const updatedRequest = await authMiddleware.onRequest?.({request} as never);

    expect(updatedRequest?.headers.get("Authorization")).toBe("Bearer token-123");
  });

  it("stores a refreshed access token when silent refresh succeeds", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({data: {access_token: "fresh-token"}}), {
          status: 200,
          headers: {"Content-Type": "application/json"},
        }),
      ),
    );

    const token = await refreshAccessToken();

    expect(token).toBe("fresh-token");
    expect(getAccessToken()).toBe("fresh-token");
  });

  it("clears auth state when silent refresh fails", async () => {
    const handleFailure = vi.fn();
    setAuthFailureHandler(handleFailure);
    setAccessToken("stale-token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, {status: 401})));

    const token = await refreshAccessToken();

    expect(token).toBeNull();
    expect(getAccessToken()).toBeNull();
    expect(handleFailure).toHaveBeenCalledTimes(1);
  });
});
