import type {JSX} from "react";

import {Card, CardDescription, CardTitle} from "../components/ui/card";

interface PlaceholderPageProps {
  readonly description: string;
  readonly eyebrow: string;
  readonly title: string;
}

export function PlaceholderPage({description, eyebrow, title}: PlaceholderPageProps): JSX.Element {
  return (
    <Card className="w-full bg-background/85 p-6 shadow-sm backdrop-blur-sm">
      <p className="text-sm font-medium uppercase tracking-[0.2em] text-muted-foreground">{eyebrow}</p>
      <CardTitle className="mt-4">{title}</CardTitle>
      <CardDescription className="max-w-2xl leading-7">{description}</CardDescription>
    </Card>
  );
}
