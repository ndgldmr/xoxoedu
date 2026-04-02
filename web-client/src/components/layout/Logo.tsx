import Image from "next/image";
import { cn } from "@/lib/utils";

// Intrinsic pixel dimensions for each logo file (required by next/image)
const LOGO_META = {
  default: { src: "/logo/logo-1.png", w: 252, h: 356 },
  dark:    { src: "/logo/logo-2.png", w: 481, h: 220 },
};

interface LogoProps {
  /** "default" uses logo-1.png; "dark" uses logo-2.png */
  variant?: "default" | "dark";
  /** Rendered height in px — width scales automatically to preserve aspect ratio */
  height?: number;
  className?: string;
}

export function Logo({ variant = "default", height = 40, className }: LogoProps) {
  const { src, w, h } = LOGO_META[variant];
  return (
    <Image
      src={src}
      alt="XOXO Education"
      width={w}
      height={h}
      style={{ height, width: "auto" }}
      className={cn("object-contain", className)}
      priority
    />
  );
}
