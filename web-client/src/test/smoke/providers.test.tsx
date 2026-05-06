import {render, screen, waitFor} from "@testing-library/react";
import {afterEach, describe, expect, it, vi} from "vitest";

import {AppProviders} from "../../app/AppProviders";
import {useAuthStore} from "../../features/auth/store/useAuthStore";
import * as apiClient from "../../lib/api/client";
import {createTestRouter} from "../../routes/router";

describe("provider bootstrap", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    useAuthStore.setState({status: "anonymous", user: null});
  });

  it("boots an existing session into a protected route without redirecting to login", async () => {
    vi.spyOn(apiClient, "refreshAccessToken").mockResolvedValue("fresh-token");
    vi.spyOn(apiClient, "fetchCurrentUser").mockResolvedValue({
      id: "u1",
      email: "student@example.com",
      username: "student",
      display_name: "Student User",
      avatar_url: null,
      date_of_birth: "2000-01-02",
      country: "BR",
      gender: "female",
      gender_self_describe: null,
      role: "student",
      email_verified: true,
      profile_complete: true,
      social_links: null,
    });

    useAuthStore.setState({status: "idle", user: null});
    const router = createTestRouter(["/dashboard"]);

    render(<AppProviders router={router} />);

    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
    expect(await screen.findByText(/dashboard-first route contract/i)).toBeInTheDocument();
    expect(screen.queryByText(/welcome back to xoxo education/i)).not.toBeInTheDocument();
  });
});
