import {render, screen} from "@testing-library/react";
import {describe, expect, it} from "vitest";

import {AppProviders} from "../../app/AppProviders";
import {useAuthStore} from "../../features/auth/store/useAuthStore";
import {createTestRouter} from "../../routes/router";

const studentUser = {
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
};

describe("route shells", () => {
  it("redirects anonymous dashboard traffic to /sign-in", async () => {
    useAuthStore.setState({status: "anonymous", user: null});
    const router = createTestRouter(["/dashboard"]);

    render(<AppProviders bootstrap={false} router={router} />);

    expect(await screen.findByRole("heading", {name: /sign into xoxo education/i})).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(router.state.location.search).toContain("next=%2Fdashboard");
  });

  it("redirects anonymous admin traffic to /sign-in", async () => {
    useAuthStore.setState({status: "anonymous", user: null});
    const router = createTestRouter(["/admin"]);

    render(<AppProviders bootstrap={false} router={router} />);

    expect(await screen.findByRole("heading", {name: /sign into xoxo education/i})).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(router.state.location.search).toContain("next=%2Fadmin");
  });

  it("redirects authenticated non-admin users away from /admin", async () => {
    useAuthStore.setState({status: "authenticated", user: studentUser});
    const router = createTestRouter(["/admin"]);

    render(<AppProviders bootstrap={false} router={router} />);

    expect(await screen.findByText(/admin access required/i)).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/unauthorized");
  });
});
