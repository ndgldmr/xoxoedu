import type {JSX} from "react";
import {useState} from "react";
import {Link} from "react-router-dom";
import {useForm} from "react-hook-form";
import {zodResolver} from "@hookform/resolvers/zod";
import {CheckCircle2} from "lucide-react";
import {toast} from "sonner";

import {PageShell} from "../components/layout/PageShell";
import {forgotPassword} from "../features/auth/api/auth";
import {type ForgotPasswordFormValues, forgotPasswordSchema} from "../features/auth/schemas/authSchemas";
import {Button} from "../components/ui/button";
import {Input} from "../components/ui/input";
import {Label} from "../components/ui/label";
import {Card} from "../components/ui/card";

export function ForgotPasswordPage(): JSX.Element {
  const [viewState, setViewState] = useState<"idle" | "submitted">("idle");
  const [submittedEmail, setSubmittedEmail] = useState("");

  const {
    register,
    handleSubmit,
    formState: {errors, isSubmitting},
  } = useForm<ForgotPasswordFormValues>({
    resolver: zodResolver(forgotPasswordSchema),
  });

  const onSubmit = async (values: ForgotPasswordFormValues): Promise<void> => {
    try {
      await forgotPassword(values.email);
      setSubmittedEmail(values.email);
      setViewState("submitted");
    } catch {
      toast.error("Something went wrong. Please try again.");
    }
  };

  if (viewState === "submitted") {
    return (
      <PageShell centered className="bg-background" contentClassName="py-10" width="narrow">
        <Card className="w-full p-8 text-center">
          <div className="flex justify-center">
            <CheckCircle2 className="size-10 text-foreground" strokeWidth={1.5} />
          </div>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight text-foreground">Check your email</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            If <span className="font-medium text-foreground">{submittedEmail}</span> is registered, you will receive a
            reset link shortly.
          </p>
          <Link
            className="mt-6 inline-block text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
            to="/sign-in"
          >
            Back to sign in
          </Link>
        </Card>
      </PageShell>
    );
  }

  return (
    <PageShell centered className="bg-background" contentClassName="py-10" width="narrow">
      <Card className="w-full p-8">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Reset your password</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Enter your email and we&apos;ll send a reset link.
        </p>

        <form className="mt-6 space-y-4" noValidate onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-2.5">
            <Label htmlFor="email">Email</Label>
            <Input
              autoComplete="email"
              autoFocus
              id="email"
              placeholder="you@example.com"
              type="email"
              {...register("email")}
              aria-invalid={errors.email ? "true" : undefined}
            />
            {errors.email && (
              <p className="text-xs text-destructive" role="alert">
                {errors.email.message}
              </p>
            )}
          </div>

          <Button className="w-full" disabled={isSubmitting} type="submit">
            {isSubmitting ? "Sending…" : "Send reset link"}
          </Button>
        </form>

        <Link
          className="mt-6 inline-block text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          to="/sign-in"
        >
          Back to sign in
        </Link>
      </Card>
    </PageShell>
  );
}
