import { describe, it, expect, beforeEach } from "vitest";
import { useAuthStore } from "./auth";

describe("useAuthStore", () => {
  beforeEach(() => {
    useAuthStore.getState().clearAuth();
  });

  it("starts with no auth state", () => {
    const { accessToken, user } = useAuthStore.getState();
    expect(accessToken).toBeNull();
    expect(user).toBeNull();
  });

  it("setAuth stores token and user", () => {
    const mockUser = {
      id: "u1",
      email: "test@example.com",
      display_name: "Test User",
      role: "student" as const,
      is_verified: true,
    };
    useAuthStore.getState().setAuth("tok123", mockUser);

    const { accessToken, user } = useAuthStore.getState();
    expect(accessToken).toBe("tok123");
    expect(user).toEqual(mockUser);
  });

  it("clearAuth resets to null", () => {
    useAuthStore.getState().setAuth("tok", {
      id: "u1",
      email: "a@b.com",
      display_name: null,
      role: "student",
      is_verified: true,
    });

    useAuthStore.getState().clearAuth();

    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(useAuthStore.getState().user).toBeNull();
  });
});
