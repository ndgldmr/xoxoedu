/* eslint-disable react-refresh/only-export-components */
import type {JSX} from "react";
import {useState} from "react";
import type {RouteObject} from "react-router-dom";
import {
  Link,
  NavLink,
  Navigate,
  Outlet,
  createBrowserRouter,
  createMemoryRouter,
  useLocation,
  useNavigate,
} from "react-router-dom";

import {buttonVariants} from "../components/ui/button";
import {AdminHomePage} from "../pages/AdminHomePage";
import {DashboardPage} from "../pages/DashboardPage";
import {ForgotPasswordPage} from "../pages/ForgotPasswordPage";
import {NotFoundPage} from "../pages/NotFoundPage";
import {PlaceholderPage} from "../pages/PlaceholderPage";
import {ResetPasswordPage} from "../pages/ResetPasswordPage";
import {SignInPage} from "../pages/SignInPage";
import {SignUpPage} from "../pages/SignUpPage";
import {UnauthorizedPage} from "../pages/UnauthorizedPage";
import {VerifyEmailPage} from "../pages/VerifyEmailPage";
import {PageShell} from "../components/layout/PageShell";
import {useAuthStore} from "../features/auth/store/useAuthStore";
import {
  getDefaultAuthenticatedPath,
  isStudentProfileIncomplete,
} from "../features/auth/utils/routing";
import {cn} from "../lib/utils";

function LoadingRoute(): JSX.Element {
  return (
    <PageShell centered width="reading">
      <div className="space-y-2 text-center">
        <p className="text-sm font-medium uppercase tracking-[0.2em] text-muted-foreground">Bootstrapping</p>
        <p className="text-3xl font-semibold tracking-tight text-foreground">Loading session context</p>
      </div>
    </PageShell>
  );
}

function buildLoginRedirectTarget(location: ReturnType<typeof useLocation>): string {
  return `${location.pathname}${location.search}${location.hash}`;
}

function ProtectedRoute(): JSX.Element {
  const location = useLocation();
  const status = useAuthStore((state) => state.status);
  const user = useAuthStore((state) => state.user);

  if (status === "idle" || status === "loading") {
    return <LoadingRoute />;
  }

  if (status === "anonymous") {
    return <Navigate replace to={`/sign-in?next=${encodeURIComponent(buildLoginRedirectTarget(location))}`} />;
  }

  if (isStudentProfileIncomplete(user)) {
    return <Navigate replace to="/sign-up" />;
  }

  return <Outlet />;
}

function AppEntryRoute(): JSX.Element {
  const status = useAuthStore((state) => state.status);
  const user = useAuthStore((state) => state.user);

  if (status === "idle" || status === "loading") {
    return <LoadingRoute />;
  }

  if (status === "anonymous") {
    return <Navigate replace to="/sign-in" />;
  }

  return <Navigate replace to={getDefaultAuthenticatedPath(user)} />;
}

function AdminRoute(): JSX.Element {
  const location = useLocation();
  const status = useAuthStore((state) => state.status);
  const user = useAuthStore((state) => state.user);

  if (status === "idle" || status === "loading") {
    return <LoadingRoute />;
  }

  if (status === "anonymous") {
    return <Navigate replace to={`/sign-in?next=${encodeURIComponent(buildLoginRedirectTarget(location))}`} />;
  }

  if (user?.role !== "admin") {
    return <Navigate replace to="/unauthorized" />;
  }

  return <Outlet />;
}

function StudentShell(): JSX.Element {
  return (
    <PageShell className="bg-background" contentClassName="flex flex-col gap-8 py-8" width="full">
      <header className="flex flex-col gap-5 rounded-xl border border-border/70 bg-background/85 p-6 shadow-sm backdrop-blur-sm md:flex-row md:items-center md:justify-between">
        <div className="space-y-1">
          <p className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">Student shell</p>
          <h1 className="text-3xl font-semibold tracking-tight text-foreground">Dashboard-first foundation</h1>
        </div>
        <nav className="flex flex-wrap gap-2">
          <NavLink className={({isActive}) => navLinkClassName(isActive)} to="/dashboard">
            Dashboard
          </NavLink>
          <NavLink className={({isActive}) => navLinkClassName(isActive)} to="/me/account">
            Account
          </NavLink>
          <NavLink className={({isActive}) => navLinkClassName(isActive)} to="/me/calendar">
            Calendar
          </NavLink>
          <LogoutButton />
        </nav>
      </header>
      <Outlet />
    </PageShell>
  );
}

function AdminShell(): JSX.Element {
  return (
    <PageShell
      className="bg-background"
      contentClassName="grid min-h-screen gap-8 py-8 lg:grid-cols-[240px_minmax(0,1fr)]"
      width="full"
    >
      <aside className="rounded-xl border border-border/70 bg-background/85 p-5 shadow-sm backdrop-blur-sm">
        <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">Admin</p>
        <nav className="mt-6 flex flex-col gap-2">
          <NavLink className={({isActive}) => navLinkClassName(isActive)} to="/admin">
            Dashboard
          </NavLink>
        </nav>
        <div className="mt-auto pt-6">
          <LogoutButton />
        </div>
      </aside>
      <section className="py-1">
        <Outlet />
      </section>
    </PageShell>
  );
}

function AppNotFoundNavigation(): JSX.Element {
  const status = useAuthStore((state) => state.status);
  const user = useAuthStore((state) => state.user);

  return (
    <div className="mt-6 flex flex-wrap items-center gap-3">
      <a
        className={cn(buttonVariants({variant: "outline"}))}
        href="https://www.xoxoeducation.com/"
      >
        Main website
      </a>
      <Link
        className={cn(buttonVariants({variant: "default"}))}
        to={status === "authenticated" ? getDefaultAuthenticatedPath(user) : "/sign-in"}
      >
        {status === "authenticated" ? "Back to app" : "Sign in"}
      </Link>
    </div>
  );
}

function navLinkClassName(isActive: boolean): string {
  return cn(
    "inline-flex items-center rounded-md px-3 py-2 text-sm font-medium transition-colors",
    isActive
      ? "bg-primary text-primary-foreground shadow-xs"
      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
  );
}

function LogoutButton(): JSX.Element {
  const navigate = useNavigate();
  const logout = useAuthStore((state) => state.logout);
  const [pending, setPending] = useState(false);

  const handleLogout = async (): Promise<void> => {
    setPending(true);
    await logout();
    navigate("/sign-in", {replace: true});
  };

  return (
    <button
      className="inline-flex items-center rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-50"
      disabled={pending}
      onClick={() => void handleLogout()}
      type="button"
    >
      {pending ? "Signing out…" : "Sign out"}
    </button>
  );
}

export const appRoutes: RouteObject[] = [
  {
    path: "/",
    element: <AppEntryRoute />,
  },
  {
    path: "/sign-in",
    element: <SignInPage />,
  },
  {
    path: "/sign-up",
    element: <SignUpPage />,
  },
  {
    path: "/verify-email/:token",
    element: <VerifyEmailPage />,
  },
  {
    path: "/forgot-password",
    element: <ForgotPasswordPage />,
  },
  {
    path: "/reset-password/:token",
    element: <ResetPasswordPage />,
  },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <StudentShell />,
        children: [
          {
            path: "/dashboard",
            element: <DashboardPage />,
          },
          {
            path: "/me/account",
            element: (
              <PlaceholderPage
                description="Account settings will be implemented on top of the locked `/me/*` namespace."
                eyebrow="Student route"
                title="Account placeholder"
              />
            ),
          },
          {
            path: "/me/calendar",
            element: (
              <PlaceholderPage
                description="Calendar visibility is already assigned to `/me/calendar`, even though its feature work ships later."
                eyebrow="Student route"
                title="Calendar placeholder"
              />
            ),
          },
        ],
      },
      {
        path: "/courses/:slug/learn",
        element: (
          <PlaceholderPage
            description="The learning-shell namespace is reserved now so unlock-aware lesson work can extend it later."
            eyebrow="Student route"
            title="Learning shell placeholder"
          />
        ),
      },
      {
        path: "/courses/:slug/learn/:lessonId",
        element: (
          <PlaceholderPage
            description="Lesson-level navigation is intentionally part of the base route contract."
            eyebrow="Student route"
            title="Lesson placeholder"
          />
        ),
      },
    ],
  },
  {
    element: <AdminRoute />,
    children: [
      {
        element: <AdminShell />,
        children: [
          {
            path: "/admin",
            element: <AdminHomePage />,
          },
        ],
      },
    ],
  },
  {
    path: "/unauthorized",
    element: <UnauthorizedPage />,
  },
  {
    path: "*",
    element: <NotFoundPage footer={<AppNotFoundNavigation />} />,
  },
];

export const browserRouter = createBrowserRouter(appRoutes);

export function createTestRouter(initialEntries: string[]): ReturnType<typeof createMemoryRouter> {
  return createMemoryRouter(appRoutes, {initialEntries});
}
