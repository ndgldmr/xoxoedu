import {render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";

import {AppProviders} from "../../app/AppProviders";
import {useAuthStore} from "../../features/auth/store/useAuthStore";
import {createTestRouter} from "../../routes/router";

// ---------------------------------------------------------------------------
// Mock the auth API so tests never hit the network.
// ---------------------------------------------------------------------------

const mockLoginWithPassword = vi.fn();
const mockVerifyEmail = vi.fn();
const mockForgotPassword = vi.fn();
const mockResetPassword = vi.fn();
const mockLogoutSession = vi.fn();
const mockFetchRegisterOptions = vi.fn();
const mockCheckUsernameAvailability = vi.fn();
const mockRegisterStudent = vi.fn();
const mockCompleteProfile = vi.fn();
const mockResendVerificationEmail = vi.fn();
const mockUploadAvatar = vi.fn();

vi.mock("../../features/auth/api/auth", () => ({
  ApiError: class ApiError extends Error {
    readonly code: string | null;

    constructor(message: string, code: string | null = null) {
      super(message);
      this.code = code;
    }
  },
  checkUsernameAvailability: (...args: unknown[]) => mockCheckUsernameAvailability(...args),
  completeProfile: (...args: unknown[]) => mockCompleteProfile(...args),
  fetchRegisterOptions: (...args: unknown[]) => mockFetchRegisterOptions(...args),
  loginWithPassword: (...args: unknown[]) => mockLoginWithPassword(...args),
  verifyEmail: (...args: unknown[]) => mockVerifyEmail(...args),
  forgotPassword: (...args: unknown[]) => mockForgotPassword(...args),
  resetPassword: (...args: unknown[]) => mockResetPassword(...args),
  logoutSession: (...args: unknown[]) => mockLogoutSession(...args),
  registerStudent: (...args: unknown[]) => mockRegisterStudent(...args),
  resendVerificationEmail: (...args: unknown[]) => mockResendVerificationEmail(...args),
  uploadAvatar: (...args: unknown[]) => mockUploadAvatar(...args),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const fakeUser = {
  id: "u1",
  email: "test@example.com",
  username: "testuser",
  display_name: "Test User",
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

const adminUser = {
  ...fakeUser,
  id: "admin-1",
  email: "admin@example.com",
  role: "admin",
};

function renderAtRoute(path: string): ReturnType<typeof createTestRouter> {
  const router = createTestRouter([path]);
  render(<AppProviders bootstrap={false} router={router} />);
  return router;
}

beforeEach(() => {
  useAuthStore.setState({status: "anonymous", user: null});
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, {status: 401})));
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  useAuthStore.setState({status: "anonymous", user: null});
});

// ---------------------------------------------------------------------------
// Sign-in entry route
// ---------------------------------------------------------------------------

describe("auth entry routes", () => {
  it("renders the dedicated sign-in page", async () => {
    const router = renderAtRoute("/sign-in");
    expect(await screen.findByRole("heading", {name: /sign into xoxo education/i})).toBeInTheDocument();
    expect(screen.getByRole("link", {name: /continue with google/i})).toHaveAttribute("href", "/api/v1/auth/google");
    expect(screen.getByText(/^email$/i)).toBeInTheDocument();
    expect(screen.getByText(/^password$/i)).toBeInTheDocument();
    expect(screen.getByRole("link", {name: /forgot your password\?/i})).toHaveAttribute("href", "/forgot-password");
    expect(screen.getByRole("link", {name: /^sign up$/i})).toHaveAttribute("href", "/sign-up");
    expect(screen.queryByText(/use one focused sign-in route for student and admin access/i)).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sign-in");
  });
});

describe("SignInPage — form validation", () => {
  it("shows email required error when email is empty and form is submitted", async () => {
    renderAtRoute("/sign-in");
    await userEvent.click(await screen.findByRole("button", {name: /sign in/i}));
    expect(await screen.findByText(/email is required/i)).toBeInTheDocument();
  });

  it("shows password required error when password is empty and form is submitted", async () => {
    renderAtRoute("/sign-in");
    await userEvent.type(await screen.findByLabelText(/email/i), "a@b.com");
    await userEvent.click(screen.getByRole("button", {name: /sign in/i}));
    expect(await screen.findByText(/password is required/i)).toBeInTheDocument();
  });

  it("shows invalid email error for a malformed email", async () => {
    renderAtRoute("/sign-in");
    await userEvent.type(await screen.findByLabelText(/email/i), "notanemail");
    await userEvent.click(screen.getByRole("button", {name: /sign in/i}));
    expect(await screen.findByText(/enter a valid email address/i)).toBeInTheDocument();
  });
});

describe("SignInPage — submit success", () => {
  beforeEach(() => {
    mockLoginWithPassword.mockResolvedValue({
      access_token: "tok",
      expires_in: 900,
      user: fakeUser,
    });
  });

  it("calls loginWithPassword with form values on valid submit", async () => {
    renderAtRoute("/sign-in");
    await userEvent.type(await screen.findByLabelText(/email/i), "test@example.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "secret123");
    await userEvent.click(screen.getByRole("button", {name: /sign in/i}));
    await waitFor(() => expect(mockLoginWithPassword).toHaveBeenCalledWith("test@example.com", "secret123"));
  });

  it("navigates to /dashboard when no ?next param is present after successful login", async () => {
    const router = renderAtRoute("/sign-in");
    await userEvent.type(await screen.findByLabelText(/email/i), "test@example.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "secret123");
    await userEvent.click(screen.getByRole("button", {name: /sign in/i}));
    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
  });

  it("navigates admins to /admin when no ?next param is present after successful login", async () => {
    mockLoginWithPassword.mockResolvedValue({
      access_token: "tok",
      expires_in: 900,
      user: adminUser,
    });

    const router = renderAtRoute("/sign-in");
    await userEvent.type(await screen.findByLabelText(/email/i), "admin@example.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "secret123");
    await userEvent.click(screen.getByRole("button", {name: /sign in/i}));
    await waitFor(() => expect(router.state.location.pathname).toBe("/admin"));
  });

  it("navigates to the ?next path after successful login", async () => {
    const router = renderAtRoute("/sign-in?next=%2Fme%2Faccount");
    await userEvent.type(await screen.findByLabelText(/email/i), "test@example.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "secret123");
    await userEvent.click(screen.getByRole("button", {name: /sign in/i}));
    await waitFor(() => expect(router.state.location.pathname).toBe("/me/account"));
  });

  it("preserves query string and hash in the ?next path after successful login", async () => {
    const router = renderAtRoute("/sign-in?next=%2Fme%2Faccount%3Ftab%3Dsecurity%23password");
    await userEvent.type(await screen.findByLabelText(/email/i), "test@example.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "secret123");
    await userEvent.click(screen.getByRole("button", {name: /sign in/i}));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/me/account");
      expect(router.state.location.search).toBe("?tab=security");
      expect(router.state.location.hash).toBe("#password");
    });
  });

  it("ignores unsafe ?next targets and falls back to the role default", async () => {
    const router = renderAtRoute("/sign-in?next=https%3A%2F%2Fevil.example%2Fsteal");
    await userEvent.type(await screen.findByLabelText(/email/i), "test@example.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "secret123");
    await userEvent.click(screen.getByRole("button", {name: /sign in/i}));
    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
  });
});

describe("SignInPage — submit error", () => {
  it("displays a server error message when loginWithPassword rejects", async () => {
    mockLoginWithPassword.mockRejectedValue(new Error("Invalid email or password."));
    renderAtRoute("/sign-in");
    await userEvent.type(await screen.findByLabelText(/email/i), "bad@example.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "wrongpass");
    await userEvent.click(screen.getByRole("button", {name: /sign in/i}));
    expect(await screen.findByText(/invalid email or password/i)).toBeInTheDocument();
  });

  it("re-enables the submit button after a failed login attempt", async () => {
    mockLoginWithPassword.mockRejectedValue(new Error("Invalid email or password."));
    renderAtRoute("/sign-in");
    await userEvent.type(await screen.findByLabelText(/email/i), "bad@example.com");
    await userEvent.type(screen.getByLabelText(/^password$/i), "wrongpass");
    await userEvent.click(screen.getByRole("button", {name: /sign in/i}));
    await screen.findByText(/invalid email or password/i);
    const btn = screen.getByRole("button", {name: /sign in/i});
    expect(btn).not.toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// ForgotPasswordPage
// ---------------------------------------------------------------------------

describe("ForgotPasswordPage — form validation", () => {
  it("shows email required error on empty submit", async () => {
    renderAtRoute("/forgot-password");
    await userEvent.click(await screen.findByRole("button", {name: /send reset link/i}));
    expect(await screen.findByText(/email is required/i)).toBeInTheDocument();
  });

  it("shows invalid email error for a malformed address", async () => {
    renderAtRoute("/forgot-password");
    await userEvent.type(await screen.findByLabelText(/email/i), "notanemail");
    await userEvent.click(screen.getByRole("button", {name: /send reset link/i}));
    expect(await screen.findByText(/enter a valid email address/i)).toBeInTheDocument();
  });
});

describe("ForgotPasswordPage — submit success", () => {
  beforeEach(() => {
    mockForgotPassword.mockResolvedValue(undefined);
  });

  it("renders the success state after forgotPassword resolves", async () => {
    renderAtRoute("/forgot-password");
    await userEvent.type(await screen.findByLabelText(/email/i), "user@example.com");
    await userEvent.click(screen.getByRole("button", {name: /send reset link/i}));
    expect(await screen.findByText(/check your email/i)).toBeInTheDocument();
  });

  it("shows the submitted email address in the confirmation message", async () => {
    renderAtRoute("/forgot-password");
    await userEvent.type(await screen.findByLabelText(/email/i), "user@example.com");
    await userEvent.click(screen.getByRole("button", {name: /send reset link/i}));
    expect(await screen.findByText(/user@example\.com/i)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// ResetPasswordPage
// ---------------------------------------------------------------------------

describe("ResetPasswordPage — form validation", () => {
  it("shows password too short error for passwords under 8 characters", async () => {
    renderAtRoute("/reset-password/some-token");
    await userEvent.type(await screen.findByLabelText(/^new password$/i), "short");
    await userEvent.type(screen.getByLabelText(/confirm password/i), "short");
    await userEvent.click(screen.getByRole("button", {name: /set password/i}));
    // The error paragraph uses role="alert" — disambiguate from the subtitle copy.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/at least 8 characters/i);
  });

  it("shows confirm mismatch error when passwords differ", async () => {
    renderAtRoute("/reset-password/some-token");
    await userEvent.type(await screen.findByLabelText(/^new password$/i), "password123");
    await userEvent.type(screen.getByLabelText(/confirm password/i), "different123");
    await userEvent.click(screen.getByRole("button", {name: /set password/i}));
    expect(await screen.findByText(/passwords do not match/i)).toBeInTheDocument();
  });
});

describe("ResetPasswordPage — submit success", () => {
  it("renders the success state after resetPassword resolves", async () => {
    mockResetPassword.mockResolvedValue(undefined);
    renderAtRoute("/reset-password/valid-token");
    await userEvent.type(await screen.findByLabelText(/^new password$/i), "newpassword1");
    await userEvent.type(screen.getByLabelText(/confirm password/i), "newpassword1");
    await userEvent.click(screen.getByRole("button", {name: /set password/i}));
    expect(await screen.findByText(/password updated/i)).toBeInTheDocument();
  });
});

describe("ResetPasswordPage — expired token", () => {
  it("renders the error state when resetPassword rejects", async () => {
    mockResetPassword.mockRejectedValue(new Error("This reset link is invalid or has expired."));
    renderAtRoute("/reset-password/bad-token");
    await userEvent.type(await screen.findByLabelText(/^new password$/i), "newpassword1");
    await userEvent.type(screen.getByLabelText(/confirm password/i), "newpassword1");
    await userEvent.click(screen.getByRole("button", {name: /set password/i}));
    expect(await screen.findByText(/link expired/i)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// VerifyEmailPage
// ---------------------------------------------------------------------------

describe("VerifyEmailPage — loading", () => {
  it("renders a loading indicator immediately on mount", async () => {
    // Never settle to keep loading state visible.
    mockVerifyEmail.mockReturnValue(new Promise(() => {}));
    renderAtRoute("/verify-email/some-token");
    expect(await screen.findByText(/confirming your email/i)).toBeInTheDocument();
  });
});

describe("VerifyEmailPage — success", () => {
  it("renders the success state after verifyEmail resolves", async () => {
    mockVerifyEmail.mockResolvedValue(undefined);
    renderAtRoute("/verify-email/valid-token");
    expect(await screen.findByText(/email verified/i)).toBeInTheDocument();
  });
});

describe("VerifyEmailPage — error", () => {
  it("renders the error state when verifyEmail rejects", async () => {
    mockVerifyEmail.mockRejectedValue(new Error("expired"));
    renderAtRoute("/verify-email/bad-token");
    expect(await screen.findByText(/verification failed/i)).toBeInTheDocument();
  });

  it("provides a link back to /sign-in on error", async () => {
    mockVerifyEmail.mockRejectedValue(new Error("expired"));
    renderAtRoute("/verify-email/bad-token");
    await screen.findByText(/verification failed/i);
    const link = screen.getByRole("link", {name: /back to sign in/i});
    expect(link).toHaveAttribute("href", "/sign-in");
  });
});
