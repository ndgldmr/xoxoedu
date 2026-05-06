import * as React from "react";

import {cn} from "../../lib/utils";

export type LabelProps = React.LabelHTMLAttributes<HTMLLabelElement>;

export function Label({className, ...props}: LabelProps): React.JSX.Element {
  return (
    <label
      className={cn(
        "block text-sm leading-none font-medium peer-disabled:cursor-not-allowed peer-disabled:opacity-70",
        className,
      )}
      {...props}
    />
  );
}
