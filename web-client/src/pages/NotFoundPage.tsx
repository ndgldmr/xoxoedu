import type {JSX, ReactNode} from "react";

import {Link} from "react-router-dom";

import {PageShell} from "../components/layout/PageShell";
import {buttonVariants} from "../components/ui/button";
import {Card, CardDescription, CardTitle} from "../components/ui/card";

interface NotFoundPageProps {
  readonly footer?: ReactNode;
}

export function NotFoundPage({footer}: NotFoundPageProps): JSX.Element {
  return (
    <PageShell centered width="reading">
      <Card className="w-full p-6">
        <p className="text-sm font-medium uppercase tracking-[0.2em] text-muted-foreground">404</p>
        <CardTitle className="mt-4">Route not found</CardTitle>
        <CardDescription>
          This path is not part of the current web-client route contract.
        </CardDescription>
        {footer ?? (
          <Link className={buttonVariants({variant: "default"}) + " mt-6 w-fit"} to="/sign-in">
            Sign in
          </Link>
        )}
      </Card>
    </PageShell>
  );
}
