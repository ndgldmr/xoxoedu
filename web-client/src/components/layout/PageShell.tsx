import type {ElementType, JSX, ReactNode} from "react";

import {cn} from "../../lib/utils";

export type PageShellWidth = "full" | "content" | "reading" | "narrow";

const PAGE_SHELL_WIDTH_CLASS_NAMES: Record<PageShellWidth, string> = {
  content: "mx-auto w-full max-w-[var(--page-shell-content-max)]",
  full: "w-full",
  narrow: "mx-auto w-full max-w-[var(--page-shell-narrow-max)]",
  reading: "mx-auto w-full max-w-[var(--page-shell-reading-max)]",
};

interface PageShellProps {
  readonly as?: ElementType;
  readonly centered?: boolean;
  readonly children: ReactNode;
  readonly className?: string;
  readonly contentClassName?: string;
  readonly fillViewport?: boolean;
  readonly width?: PageShellWidth;
}

/**
 * Shared route-level shell with consistent gutters and explicit width variants.
 */
export function PageShell({
  as,
  centered = false,
  children,
  className,
  contentClassName,
  fillViewport = true,
  width = "full",
}: PageShellProps): JSX.Element {
  const Component = as ?? "main";

  return (
    <Component className={cn(fillViewport && "min-h-screen", className)}>
      <div
        className={cn(
          getPageShellContentClassName(width),
          fillViewport && centered && "min-h-screen",
          centered && "flex items-center justify-center",
          contentClassName,
        )}
      >
        {children}
      </div>
    </Component>
  );
}

export function getPageShellContentClassName(width: PageShellWidth = "full"): string {
  return cn("px-[var(--page-gutter)]", PAGE_SHELL_WIDTH_CLASS_NAMES[width]);
}
