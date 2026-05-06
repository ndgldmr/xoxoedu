import {create} from "zustand";

import {
  type LoginResponseData,
  loginWithPassword,
  logoutSession,
} from "../api/auth";
import {fetchCurrentUser, refreshAccessToken, type AuthUser} from "../../../lib/api/client";
import {clearAccessToken} from "../../../lib/auth/tokens";

export type AuthStatus = "idle" | "loading" | "authenticated" | "anonymous";

interface AuthState {
  readonly status: AuthStatus;
  readonly user: AuthUser | null;
  readonly bootstrap: () => Promise<void>;
  readonly login: (email: string, password: string) => Promise<void>;
  readonly logout: () => Promise<void>;
  readonly markAnonymous: () => void;
  readonly setUser: (user: AuthUser) => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  status: "idle",
  user: null,

  markAnonymous: () => {
    clearAccessToken();
    set({status: "anonymous", user: null});
  },

  setUser: (user: AuthUser) => {
    set({status: "authenticated", user});
  },

  bootstrap: async () => {
    if (get().status === "loading") {
      return;
    }

    set({status: "loading"});

    try {
      const accessToken = await refreshAccessToken();
      if (!accessToken) {
        set({status: "anonymous", user: null});
        return;
      }

      const user = await fetchCurrentUser();
      set({status: "authenticated", user});
    } catch {
      clearAccessToken();
      set({status: "anonymous", user: null});
    }
  },

  login: async (email: string, password: string) => {
    try {
      const data: LoginResponseData = await loginWithPassword(email, password);
      // loginWithPassword already called setAccessToken; update store state.
      set({status: "authenticated", user: data.user});
    } catch (err) {
      set({status: "anonymous", user: null});
      throw err;
    }
  },

  logout: async () => {
    // logoutSession calls clearAccessToken unconditionally.
    await logoutSession();
    set({status: "anonymous", user: null});
  },
}));
