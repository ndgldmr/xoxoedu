import type {JSX} from "react";

import {Link} from "react-router-dom";

import {PageShell} from "../components/layout/PageShell";
import {buttonVariants} from "../components/ui/button";
import {Card, CardDescription, CardTitle} from "../components/ui/card";
import {cn} from "../lib/utils";

export function UnauthorizedPage(): JSX.Element {
  return (
    <PageShell centered width="reading">
      <Card className="w-full bg-background/90 p-6 shadow-sm backdrop-blur-sm">
        <p className="text-sm font-medium uppercase tracking-[0.2em] text-muted-foreground">Access boundary</p>
        <CardTitle className="mt-4">Admin access required</CardTitle>
        <CardDescription>
          WC-00 proves that admin routes reject non-admin users before the operational shell renders.
        </CardDescription>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link className={buttonVariants({variant: "primary"})} to="/dashboard">
            Student dashboard
          </Link>
          <Link className={cn(buttonVariants({variant: "outline"}))} to="/sign-in">
            Switch account
          </Link>
        </div>
      </Card>
    </PageShell>
  );
}
