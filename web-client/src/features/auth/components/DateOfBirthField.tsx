import type {JSX} from "react";

import {Input} from "../../../components/ui/input";
import {cn} from "../../../lib/utils";

interface DateOfBirthFieldProps {
  readonly disabled?: boolean;
  readonly error?: string;
  readonly onChange: (value: string) => void;
  readonly value: string;
}

function formatDateIso(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function DateOfBirthField({disabled = false, error, onChange, value}: DateOfBirthFieldProps): JSX.Element {
  const today = new Date();
  const maxDate = formatDateIso(new Date(today.getFullYear(), today.getMonth(), today.getDate()));

  return (
    <Input
      aria-invalid={error ? "true" : undefined}
      aria-label="Date of birth"
      aria-required="true"
      className={cn("h-12 rounded-md border-border bg-background", error && "border-destructive")}
      disabled={disabled}
      max={maxDate}
      onChange={(event) => onChange(event.target.value)}
      type="date"
      value={value}
    />
  );
}
