import type {JSX} from "react";
import {useEffect, useState} from "react";
import {Link, useParams} from "react-router-dom";
import {AlertCircle, CheckCircle2} from "lucide-react";

import {PageShell} from "../components/layout/PageShell";
import {verifyEmail} from "../features/auth/api/auth";
import {Card} from "../components/ui/card";

type PageState = "loading" | "success" | "error";

export function VerifyEmailPage(): JSX.Element {
  const {token = ""} = useParams<{token: string}>();
  const [pageState, setPageState] = useState<PageState>("loading");

  useEffect(() => {
    let cancelled = false;

    verifyEmail(token)
      .then(() => {
        if (!cancelled) setPageState("success");
      })
      .catch(() => {
        if (!cancelled) setPageState("error");
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  if (pageState === "loading") {
    return (
      <PageShell centered width="reading">
        <div className="space-y-2 text-center">
          <p className="text-sm font-medium uppercase tracking-[0.2em] text-muted-foreground">Verifying</p>
          <p className="text-3xl font-semibold tracking-tight text-foreground">Confirming your email…</p>
        </div>
      </PageShell>
    );
  }

  if (pageState === "success") {
    return (
      <PageShell centered className="bg-muted/30" contentClassName="py-10" width="narrow">
        <Card className="w-full p-8 text-center">
          <div className="flex justify-center">
            <CheckCircle2 className="size-10 text-foreground" strokeWidth={1.5} />
          </div>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight text-foreground">Email verified</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Your email has been confirmed. You can now sign in.
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

  return (
    <PageShell centered className="bg-muted/30" contentClassName="py-10" width="narrow">
      <Card className="w-full p-8 text-center">
        <div className="flex justify-center">
          <AlertCircle className="size-10 text-destructive" strokeWidth={1.5} />
        </div>
        <h1 className="mt-4 text-2xl font-semibold tracking-tight text-foreground">Verification failed</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          This link is invalid or has already been used.
        </p>
        <Link
          className="mt-6 inline-block text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          to="/sign-in"
          aria-label="Back to sign in"
        >
          Back to sign in
        </Link>
      </Card>
    </PageShell>
  );
}
