import * as React from "react";
import {cva, type VariantProps} from "class-variance-authority";

import {cn} from "../../lib/utils";

const badgeVariants = cva(
  "inline-flex items-center justify-center rounded-[26px] border px-2 py-0.5 text-xs font-medium w-fit whitespace-nowrap shrink-0 [&>svg]:size-3 gap-1 [&>svg]:pointer-events-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] transition-[color,box-shadow]",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "text-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

export function Badge({className, variant, ...props}: BadgeProps): React.JSX.Element {
  return <div className={cn(badgeVariants({variant}), className)} {...props} />;
}
