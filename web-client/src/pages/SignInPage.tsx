import type {JSX} from "react";
import {useEffect, useState} from "react";
import {zodResolver} from "@hookform/resolvers/zod";
import {Eye, EyeOff} from "lucide-react";
import {Link, useNavigate, useSearchParams} from "react-router-dom";
import {useForm} from "react-hook-form";

import {Logo} from "../components/brand/Logo";
import {PageShell} from "../components/layout/PageShell";
import {Button} from "../components/ui/button";
import {Input} from "../components/ui/input";
import {Label} from "../components/ui/label";
import {GoogleOAuthButton} from "../features/auth/components/GoogleOAuthButton";
import {type LoginFormValues, loginSchema} from "../features/auth/schemas/authSchemas";
import {useAuthStore} from "../features/auth/store/useAuthStore";
import {resolvePostLoginTarget} from "../features/auth/utils/routing";
import {cn} from "../lib/utils";

const MARKETING_SITE_URL = "https://www.xoxoeducation.com/";

function LoadingAuthPage(): JSX.Element {
  return (
    <div className="space-y-2 text-center">
      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-muted-foreground">Preparing</p>
      <p className="text-2xl font-semibold tracking-tight text-foreground">Loading session context…</p>
    </div>
  );
}

function LoginPanel(): JSX.Element {
  const login = useAuthStore((state) => state.login);
  const [serverError, setServerError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const {
    handleSubmit,
    register,
    formState: {errors, isSubmitting},
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
  });

  const onSubmit = async (values: LoginFormValues): Promise<void> => {
    setServerError(null);
    try {
      await login(values.email, values.password);
    } catch (err) {
      setServerError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-center gap-6 text-center">
        <a className="inline-flex items-center justify-center" href={MARKETING_SITE_URL}>
          <Logo height={44} />
        </a>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">Sign into XOXO Education</h1>
      </div>

      <form className="space-y-4" noValidate onSubmit={handleSubmit(onSubmit)}>
        <div className="space-y-2.5">
          <Label htmlFor="login-email">Email</Label>
          <Input
            {...register("email")}
            aria-invalid={errors.email?.message ? "true" : undefined}
            autoComplete="email"
            autoFocus
            className={cn("border-border bg-background shadow-none", errors.email?.message && "border-destructive")}
            id="login-email"
            placeholder="Email"
            type="email"
          />
          {errors.email?.message && (
            <p className="text-xs text-destructive" role="alert">
              {errors.email.message}
            </p>
          )}
        </div>

        <div className="space-y-2.5">
          <div className="relative">
            <Label htmlFor="login-password">Password</Label>
            <Link
              className="absolute right-0 top-0 text-sm leading-none text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
              to="/forgot-password"
            >
              Forgot your password?
            </Link>
          </div>
          <div className="relative">
            <Input
              {...register("password")}
              aria-invalid={errors.password?.message ? "true" : undefined}
              autoComplete="current-password"
              className={cn(
                "border-border bg-background pr-10 shadow-none",
                errors.password?.message && "border-destructive",
              )}
              id="login-password"
              placeholder="Password"
              type={showPassword ? "text" : "password"}
            />
            <div className="absolute right-3 top-1/2 -translate-y-1/2">
              <button
                aria-label={showPassword ? "Hide password" : "Show password"}
                className="flex size-8 items-center justify-center text-muted-foreground hover:text-foreground"
                onClick={() => setShowPassword((current) => !current)}
                type="button"
              >
                {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
          </div>
          {errors.password?.message && (
            <p className="text-xs text-destructive" role="alert">
              {errors.password.message}
            </p>
          )}
        </div>

        {serverError && (
          <p className="text-sm text-destructive" role="alert">
            {serverError}
          </p>
        )}

        <div className="grid gap-3 pt-1 sm:grid-cols-2">
          <GoogleOAuthButton />
          <Button className="w-full" disabled={isSubmitting} type="submit">
            {isSubmitting ? "Signing in…" : "Sign in"}
          </Button>
        </div>
      </form>

      <p className="text-center text-sm text-muted-foreground">
        Don't have an account?{" "}
        <Link className="text-foreground underline-offset-4 hover:underline" to="/sign-up">
          Sign up
        </Link>
        .
      </p>
    </div>
  );
}

export function SignInPage(): JSX.Element {
  const navigate = useNavigate();
  const status = useAuthStore((state) => state.status);
  const user = useAuthStore((state) => state.user);
  const [searchParams] = useSearchParams();
  const nextPath = searchParams.get("next");

  useEffect(() => {
    if (status === "authenticated" && user) {
      navigate(resolvePostLoginTarget(nextPath, user), {replace: true});
    }
  }, [navigate, nextPath, status, user]);

  return (
    <PageShell centered className="bg-background text-foreground" contentClassName="py-8" width="reading">
      <div className="w-full">
        {(status === "idle" || status === "loading") && <LoadingAuthPage />}
        {status === "anonymous" && <LoginPanel />}
        {status === "authenticated" && user && <LoadingAuthPage />}
      </div>
    </PageShell>
  );
}
