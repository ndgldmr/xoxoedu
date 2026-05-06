import type {JSX} from "react";
import {useEffect, useMemo, useRef, useState} from "react";
import {Check, ChevronDown, Search} from "lucide-react";

import {Button} from "../../../components/ui/button";
import {EncryptedText} from "../../../components/ui/encrypted-text";
import {Input} from "../../../components/ui/input";
import {cn} from "../../../lib/utils";

interface CountryOption {
  readonly code: string;
  readonly name: string;
}

interface CountryDropdownProps {
  readonly disabled?: boolean;
  readonly error?: string;
  readonly onChange: (value: string) => void;
  readonly options: CountryOption[];
  readonly value: string;
}

function countryFlagEmoji(code: string): string {
  return String.fromCodePoint(...Array.from(code.toUpperCase()).map((char) => 127397 + char.charCodeAt(0)));
}

export function CountryDropdown({disabled = false, error, onChange, options, value}: CountryDropdownProps): JSX.Element {
  const [isOpen, setIsOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);

  const selectedOption = options.find((option) => option.code === value) ?? null;
  const filteredOptions = useMemo(() => {
    const normalizedSearch = searchValue.trim().toLowerCase();
    if (!normalizedSearch) {
      return options;
    }

    return options.filter((option) => {
      const haystack = `${option.name} ${option.code}`.toLowerCase();
      return haystack.includes(normalizedSearch);
    });
  }, [options, searchValue]);

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

  useEffect(() => {
    if (isOpen) {
      searchInputRef.current?.focus();
    } else {
      setSearchValue("");
    }
  }, [isOpen]);

  return (
    <div className="space-y-1.5" ref={containerRef}>
      <Button
        aria-label="Country"
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
        <span className="flex min-w-0 items-center gap-2">
          {selectedOption ? (
            <>
              <span aria-hidden="true" className="text-base">
                {countryFlagEmoji(selectedOption.code)}
              </span>
              <span className="truncate">{selectedOption.name}</span>
            </>
          ) : (
            <EncryptedText
              encryptedClassName="text-muted-foreground/40"
              revealedClassName="text-muted-foreground"
              text="Select your country"
            />
          )}
        </span>
        <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
      </Button>

      {isOpen && (
        <div className="relative z-20 rounded-lg border border-border bg-background p-2 shadow-lg">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label="Search countries"
              className="pl-9"
              onChange={(event) => setSearchValue(event.target.value)}
              placeholder="Search countries"
              ref={searchInputRef}
              value={searchValue}
            />
          </div>

          <div className="mt-2 max-h-64 overflow-y-auto" role="listbox">
            {filteredOptions.length ? (
              filteredOptions.map((option) => {
                const selected = option.code === value;
                return (
                  <button
                    className={cn(
                      "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent",
                      selected && "bg-accent",
                    )}
                    key={option.code}
                    onClick={() => {
                      onChange(option.code);
                      setIsOpen(false);
                    }}
                    type="button"
                  >
                    <span className="flex items-center gap-2">
                      <span aria-hidden="true" className="text-base">
                        {countryFlagEmoji(option.code)}
                      </span>
                      <span>{option.name}</span>
                    </span>
                    {selected && <Check className="size-4 text-foreground" />}
                  </button>
                );
              })
            ) : (
              <p className="px-3 py-2 text-sm text-muted-foreground">No countries match your search.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
