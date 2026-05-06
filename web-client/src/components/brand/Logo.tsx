import type {JSX} from "react";

import {cn} from "../../lib/utils";

interface LogoProps {
  readonly className?: string;
  readonly height?: number;
}

export function Logo({className, height = 32}: LogoProps): JSX.Element {
  return (
    <img
      alt="XOXO Education"
      className={cn("select-none", className)}
      height={height}
      src="/logo/logo-2.png"
      style={{height, width: "auto"}}
    />
  );
}
