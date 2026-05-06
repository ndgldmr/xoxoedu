import type {AuthUser} from "../../../lib/api/client";

export function isStudentProfileIncomplete(user: AuthUser | null): boolean {
  return Boolean(user && user.role === "student" && !user.profile_complete);
}

export function getDefaultAuthenticatedPath(user: Pick<AuthUser, "profile_complete" | "role"> | null): string {
  if (!user) {
    return "/dashboard";
  }

  if (user.role === "admin") {
    return "/admin";
  }

  if (!user.profile_complete) {
    return "/sign-up";
  }

  return "/dashboard";
}

export function resolvePostLoginTarget(
  nextPath: string | null,
  user: Pick<AuthUser, "profile_complete" | "role"> | null,
): string {
  const fallback = getDefaultAuthenticatedPath(user);

  if (user?.role === "student" && !user.profile_complete) {
    return fallback;
  }

  if (!nextPath || !nextPath.startsWith("/") || nextPath.startsWith("//")) {
    return fallback;
  }

  try {
    const url = new URL(nextPath, window.location.origin);
    if (url.origin !== window.location.origin) {
      return fallback;
    }

    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return fallback;
  }
}
