import * as React from "react";

import {cn} from "../../lib/utils";

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  function Card({className, ...props}, ref) {
    return (
      <div
        className={cn("rounded-xl border bg-card text-card-foreground shadow-[var(--shadow-subtle-2)]", className)}
        ref={ref}
        {...props}
      />
    );
  },
);

export const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  function CardHeader({className, ...props}, ref) {
    return <div className={cn("grid auto-rows-min grid-rows-[auto_auto] items-start gap-1.5 p-6", className)} ref={ref} {...props} />;
  },
);

export const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  function CardFooter({className, ...props}, ref) {
    return <div className={cn("flex items-center p-6 pt-0", className)} ref={ref} {...props} />;
  },
);

export const CardAction = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  function CardAction({className, ...props}, ref) {
    return <div className={cn("col-start-2 row-span-2 row-start-1 self-start justify-self-end", className)} ref={ref} {...props} />;
  },
);

export const CardTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  function CardTitle({className, ...props}, ref) {
    return <h2 className={cn("leading-none font-semibold tracking-tight", className)} ref={ref} {...props} />;
  },
);

export const CardDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(function CardDescription({className, ...props}, ref) {
  return <p className={cn("text-sm text-muted-foreground", className)} ref={ref} {...props} />;
});
