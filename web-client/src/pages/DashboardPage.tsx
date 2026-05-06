import type {JSX} from "react";

import {ArrowRight, ShieldCheck, Workflow} from "lucide-react";
import {Link} from "react-router-dom";

import {buttonVariants} from "../components/ui/button";
import {Card, CardDescription, CardTitle} from "../components/ui/card";
import {cn} from "../lib/utils";

export function DashboardPage(): JSX.Element {
  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <p className="text-sm font-medium uppercase tracking-[0.2em] text-muted-foreground">Student foundation</p>
        <h1 className="text-4xl font-semibold leading-tight tracking-tight text-foreground">Dashboard-first route contract</h1>
        <p className="max-w-2xl text-base leading-7 text-muted-foreground">
          This placeholder locks the student home at <code>/dashboard</code> and reserves <code>/me/*</code> for
          account-adjacent surfaces while the onboarding and learning flows are built out.
        </p>
      </header>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="bg-background/85 p-6 shadow-sm backdrop-blur-sm">
          <Workflow className="size-5 text-primary" />
          <CardTitle className="mt-4">Progression-ready</CardTitle>
          <CardDescription>The student shell is aligned to guided progression rather than catalog-first browsing.</CardDescription>
        </Card>
        <Card className="bg-background/85 p-6 shadow-sm backdrop-blur-sm">
          <ShieldCheck className="size-5 text-primary" />
          <CardTitle className="mt-4">Backend-owned truth</CardTitle>
          <CardDescription>Auth, program state, and access gating stay server-driven from day one.</CardDescription>
        </Card>
        <Card className="bg-background/85 p-6 shadow-sm backdrop-blur-sm">
          <ArrowRight className="size-5 text-primary" />
          <CardTitle className="mt-4">Route stability</CardTitle>
          <CardDescription>Later sprints can add real screens without renaming the top-level student namespace.</CardDescription>
        </Card>
      </div>

      <div className="flex flex-wrap gap-3">
        <Link className={buttonVariants({variant: "primary"})} to="/me/calendar">
          Calendar placeholder
        </Link>
        <Link className={cn(buttonVariants({variant: "outline"}))} to="/courses/example-program/learn">
          Learning shell placeholder
        </Link>
      </div>
    </div>
  );
}
