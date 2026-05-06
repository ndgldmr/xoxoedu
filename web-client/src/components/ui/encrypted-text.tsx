import {useEffect, useRef, useState} from "react";
import type {JSX} from "react";

import {cn} from "../../lib/utils";

const DEFAULT_CHARSET =
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*()_+-={}[];:,.<>/?";

function randomChar(charset: string): string {
  return charset[Math.floor(Math.random() * charset.length)];
}

export interface EncryptedTextProps {
  readonly text: string;
  readonly className?: string;
  readonly encryptedClassName?: string;
  readonly revealedClassName?: string;
  /** Delay in ms between each character reveal. Default: 50. */
  readonly revealDelayMs?: number;
  /** Character set used for the gibberish effect. */
  readonly charset?: string;
  /** How fast unrevealed characters flip to new random chars. Default: 50. */
  readonly flipDelayMs?: number;
}

interface CharState {
  readonly char: string;
  readonly revealed: boolean;
}

/**
 * Animates text from scrambled random characters to the real string,
 * revealing one character at a time from left to right.
 *
 * Wrap in aria-hidden when used as decorative placeholder text — screen
 * readers should receive the real value through the input's aria-label.
 */
export function EncryptedText({
  text,
  className,
  encryptedClassName,
  revealedClassName,
  revealDelayMs = 50,
  charset = DEFAULT_CHARSET,
  flipDelayMs = 50,
}: EncryptedTextProps): JSX.Element {
  const [chars, setChars] = useState<CharState[]>(() =>
    text.split("").map(() => ({char: randomChar(charset), revealed: false})),
  );

  // Keep a ref so interval callbacks can read the latest revealed index
  // without needing to be recreated on every tick.
  const revealIndexRef = useRef(0);

  useEffect(() => {
    // Reset on text change (e.g. if the component is reused with different text).
    revealIndexRef.current = 0;
    setChars(text.split("").map(() => ({char: randomChar(charset), revealed: false})));

    // Flip interval: scramble unrevealed characters continuously.
    const flipId = setInterval(() => {
      setChars((prev) =>
        prev.map((c) => (c.revealed ? c : {char: randomChar(charset), revealed: false})),
      );
    }, flipDelayMs);

    // Reveal interval: mark one character at a time as revealed.
    const revealId = setInterval(() => {
      const idx = revealIndexRef.current;
      if (idx >= text.length) {
        clearInterval(flipId);
        clearInterval(revealId);
        return;
      }
      setChars((prev) =>
        prev.map((c, i) => (i === idx ? {char: text[i], revealed: true} : c)),
      );
      revealIndexRef.current = idx + 1;
    }, revealDelayMs);

    return () => {
      clearInterval(flipId);
      clearInterval(revealId);
    };
  }, [text, charset, flipDelayMs, revealDelayMs]);

  return (
    <span aria-hidden="true" className={cn("text-sm", className)}>
      {chars.map(({char, revealed}, i) => (
        <span className={revealed ? revealedClassName : encryptedClassName} key={i}>
          {char}
        </span>
      ))}
    </span>
  );
}
