import type {JSX} from "react";

import {Card, CardDescription, CardTitle} from "../components/ui/card";

export function AdminHomePage(): JSX.Element {
  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <p className="text-sm font-medium uppercase tracking-[0.2em] text-muted-foreground">Admin foundation</p>
        <h1 className="text-4xl font-semibold leading-tight tracking-tight text-foreground">Operational shell placeholder</h1>
        <p className="max-w-2xl text-base text-muted-foreground">
          WC-00 creates the route boundary, shell frame, and shared providers. Admin feature density lands in later
          sprints.
        </p>
      </header>
      <div className="grid gap-4 md:grid-cols-2">
        <Card className="bg-background/85 p-6 shadow-sm backdrop-blur-sm">
          <CardTitle>Stable namespace</CardTitle>
          <CardDescription>`/admin/*` is locked now so later operational slices do not need route churn.</CardDescription>
        </Card>
        <Card className="bg-background/85 p-6 shadow-sm backdrop-blur-sm">
          <CardTitle>Auth boundary</CardTitle>
          <CardDescription>Admin access is checked at the route boundary before admin screens render.</CardDescription>
        </Card>
      </div>
    </div>
  );
}
