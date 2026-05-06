import type {JSX} from "react";
import {useEffect, useMemo, useRef, useState} from "react";
import {Check, ChevronDown} from "lucide-react";

import {Button} from "../../../components/ui/button";
import {EncryptedText} from "../../../components/ui/encrypted-text";
import {cn} from "../../../lib/utils";

interface OptionDropdownFieldProps {
  readonly ariaLabel: string;
  readonly disabled?: boolean;
  readonly error?: string;
  readonly onChange: (value: string) => void;
  readonly options: ReadonlyArray<{
    readonly label: string;
    readonly value: string;
  }>;
  readonly placeholder: string;
  readonly value: string;
}

export function OptionDropdownField({
  ariaLabel,
  disabled = false,
  error,
  onChange,
  options,
  placeholder,
  value,
}: OptionDropdownFieldProps): JSX.Element {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const selectedOption = useMemo(
    () => options.find((option) => option.value === value) ?? null,
    [options, value],
  );

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handlePointerDown = (event: MouseEvent): void => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [isOpen]);

  return (
    <div className="space-y-1.5" ref={containerRef}>
      <Button
        aria-label={ariaLabel}
        aria-required="true"
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        className={cn(
          "w-full justify-between border border-input bg-background px-3 font-normal text-foreground shadow-none hover:bg-background",
          !selectedOption && "text-muted-foreground",
          error && "border-destructive",
        )}
        disabled={disabled}
        onClick={() => setIsOpen((current) => !current)}
        type="button"
        variant="outline"
      >
        <span className="truncate">
          {selectedOption ? (
            selectedOption.label
          ) : (
            <EncryptedText
              encryptedClassName="text-muted-foreground/40"
              revealedClassName="text-muted-foreground"
              text={placeholder}
            />
          )}
        </span>
        <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
      </Button>

      {isOpen && (
        <div className="relative z-20 rounded-lg border border-border bg-background p-2 shadow-lg">
          <div className="max-h-64 overflow-y-auto" role="listbox">
            {options.map((option) => {
              const selected = option.value === value;
              return (
                <button
                  className={cn(
                    "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent",
                    selected && "bg-accent",
                  )}
                  key={option.value}
                  onClick={() => {
                    onChange(option.value);
                    setIsOpen(false);
                  }}
                  type="button"
                >
                  <span>{option.label}</span>
                  {selected && <Check className="size-4 text-foreground" />}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
