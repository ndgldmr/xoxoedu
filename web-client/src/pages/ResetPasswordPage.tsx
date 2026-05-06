import type {JSX} from "react";
import {useState} from "react";
import {Link, useParams} from "react-router-dom";
import {useForm} from "react-hook-form";
import {zodResolver} from "@hookform/resolvers/zod";
import {AlertCircle, CheckCircle2, Eye, EyeOff} from "lucide-react";

import {PageShell} from "../components/layout/PageShell";
import {resetPassword} from "../features/auth/api/auth";
import {type ResetPasswordFormValues, resetPasswordSchema} from "../features/auth/schemas/authSchemas";
import {Button} from "../components/ui/button";
import {Input} from "../components/ui/input";
import {Label} from "../components/ui/label";
import {Card} from "../components/ui/card";

type PageState = "idle" | "success" | "error";

export function ResetPasswordPage(): JSX.Element {
  const {token = ""} = useParams<{token: string}>();
  const [pageState, setPageState] = useState<PageState>("idle");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const {
    register,
    handleSubmit,
    formState: {errors, isSubmitting},
  } = useForm<ResetPasswordFormValues>({
    resolver: zodResolver(resetPasswordSchema),
  });

  const onSubmit = async (values: ResetPasswordFormValues): Promise<void> => {
    try {
      await resetPassword(token, values.password);
      setPageState("success");
    } catch {
      setPageState("error");
    }
  };

  if (pageState === "success") {
    return (
      <PageShell centered className="bg-background" contentClassName="py-10" width="narrow">
        <Card className="w-full p-8 text-center">
          <div className="flex justify-center">
            <CheckCircle2 className="size-10 text-foreground" strokeWidth={1.5} />
          </div>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight text-foreground">Password updated</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Your password has been changed. You can now sign in with your new password.
          </p>
          <Link
            className="mt-6 inline-block text-sm font-medium text-foreground underline-offset-4 hover:underline"
            to="/sign-in"
          >
            Sign in
          </Link>
        </Card>
      </PageShell>
    );
  }

  if (pageState === "error") {
    return (
      <PageShell centered className="bg-background" contentClassName="py-10" width="narrow">
        <Card className="w-full p-8 text-center">
          <div className="flex justify-center">
            <AlertCircle className="size-10 text-destructive" strokeWidth={1.5} />
          </div>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight text-foreground">Link expired</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            This reset link is invalid or has expired. Request a new one.
          </p>
          <Link
            className="mt-6 inline-block text-sm font-medium text-foreground underline-offset-4 hover:underline"
            to="/forgot-password"
          >
            Request a new link
          </Link>
        </Card>
      </PageShell>
    );
  }

  return (
    <PageShell centered className="bg-background" contentClassName="py-10" width="narrow">
      <Card className="w-full p-8">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Set a new password</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">Choose a strong password of at least 8 characters.</p>

        <form className="mt-6 space-y-4" noValidate onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-2.5">
            <Label htmlFor="password">New password</Label>
            <div className="relative">
              <Input
                autoComplete="new-password"
                autoFocus
                className="pr-9"
                id="password"
                type={showPassword ? "text" : "password"}
                {...register("password")}
                aria-invalid={errors.password ? "true" : undefined}
              />
              <button
                aria-label={showPassword ? "Hide password" : "Show password"}
                className="absolute right-2 top-1/2 -translate-y-1/2 flex size-8 items-center justify-center text-muted-foreground hover:text-foreground"
                onClick={() => setShowPassword((v) => !v)}
                type="button"
              >
                {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
            {errors.password && (
              <p className="text-xs text-destructive" role="alert">
                {errors.password.message}
              </p>
            )}
          </div>

          <div className="space-y-2.5">
            <Label htmlFor="confirmPassword">Confirm password</Label>
            <div className="relative">
              <Input
                autoComplete="new-password"
                className="pr-9"
                id="confirmPassword"
                type={showConfirm ? "text" : "password"}
                {...register("confirmPassword")}
                aria-invalid={errors.confirmPassword ? "true" : undefined}
              />
              <button
                aria-label={showConfirm ? "Hide password" : "Show password"}
                className="absolute right-2 top-1/2 -translate-y-1/2 flex size-8 items-center justify-center text-muted-foreground hover:text-foreground"
                onClick={() => setShowConfirm((v) => !v)}
                type="button"
              >
                {showConfirm ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
            {errors.confirmPassword && (
              <p className="text-xs text-destructive" role="alert">
                {errors.confirmPassword.message}
              </p>
            )}
          </div>

          <Button className="w-full" disabled={isSubmitting} type="submit">
            {isSubmitting ? "Updating…" : "Set password"}
          </Button>
        </form>
      </Card>
    </PageShell>
  );
}
