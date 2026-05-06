import type {ComponentProps, JSX} from "react";
import {ChevronLeft, ChevronRight} from "lucide-react";
import {DayPicker} from "react-day-picker";

import {buttonVariants} from "./button";
import {cn} from "../../lib/utils";

export type CalendarProps = ComponentProps<typeof DayPicker>;

export function Calendar({className, classNames, showOutsideDays = false, ...props}: CalendarProps): JSX.Element {
  return (
    <DayPicker
      className={cn("p-0", className)}
      classNames={{
        root: "w-full",
        months: "flex flex-col",
        month: "space-y-4",
        month_caption: "flex items-center justify-center gap-2 pt-1",
        caption_label: "text-sm font-medium",
        nav: "hidden",
        dropdowns: "flex w-full items-center gap-2",
        dropdown_root: "relative flex-1",
        dropdown: "h-9 w-full cursor-pointer rounded-md border border-input bg-background px-3 text-sm text-foreground shadow-none outline-none",
        month_grid: "w-full border-collapse",
        weekdays: "grid grid-cols-7 gap-1",
        weekday: "h-8 text-center text-xs font-medium text-muted-foreground",
        week: "mt-1 grid grid-cols-7 gap-1",
        day: "h-9 w-9 p-0 text-center text-sm",
        day_button: cn(
          buttonVariants({variant: "ghost"}),
          "h-9 w-9 p-0 font-normal aria-selected:opacity-100",
        ),
        selected: "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground focus:bg-primary focus:text-primary-foreground",
        today: "border border-border text-foreground",
        outside: "text-muted-foreground/40 aria-selected:bg-accent/40 aria-selected:text-muted-foreground/70",
        disabled: "pointer-events-none text-muted-foreground/40",
        hidden: "invisible",
        ...classNames,
      }}
      components={{
        Chevron: ({orientation, className: iconClassName, ...iconProps}) =>
          orientation === "left" ? (
            <ChevronLeft className={cn("size-4", iconClassName)} {...iconProps} />
          ) : (
            <ChevronRight className={cn("size-4", iconClassName)} {...iconProps} />
          ),
      }}
      showOutsideDays={showOutsideDays}
      {...props}
    />
  );
}
