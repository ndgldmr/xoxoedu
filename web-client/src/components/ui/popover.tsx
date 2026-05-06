import * as React from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";

import {cn} from "../../lib/utils";

export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export const PopoverAnchor = PopoverPrimitive.Anchor;

export const PopoverContent = React.forwardRef<
  React.ElementRef<typeof PopoverPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
>(function PopoverContent({className, align = "center", sideOffset = 8, ...props}, ref) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        align={align}
        className={cn(
          "z-50 w-72 rounded-lg border border-border bg-background p-4 text-foreground shadow-lg outline-none data-[state=open]:animate-in data-[state=closed]:animate-out",
          className,
        )}
        ref={ref}
        sideOffset={sideOffset}
        {...props}
      />
    </PopoverPrimitive.Portal>
  );
});
