import type {ReactNode} from "react";
import {useId, useState} from "react";

import {cn} from "../../lib/utils";

export interface TabDefinition {
  readonly content: ReactNode;
  readonly title: string;
  readonly value: string;
}

interface TabsProps {
  readonly activeTabClassName?: string;
  readonly containerClassName?: string;
  readonly contentClassName?: string;
  readonly defaultValue?: string;
  readonly onValueChange?: (value: string) => void;
  readonly tabClassName?: string;
  readonly tabs: readonly TabDefinition[];
  readonly value?: string;
}

export function Tabs({
  activeTabClassName,
  containerClassName,
  contentClassName,
  defaultValue,
  onValueChange,
  tabClassName,
  tabs,
  value,
}: TabsProps): React.JSX.Element {
  const fallbackValue = defaultValue ?? tabs[0]?.value ?? "";
  const [internalValue, setInternalValue] = useState(fallbackValue);
  const tabListId = useId();
  const activeValue = value ?? internalValue;
  const activeTab = tabs.find((tab) => tab.value === activeValue) ?? tabs[0] ?? null;

  if (!activeTab) {
    return <div className={containerClassName} />;
  }

  const handleValueChange = (nextValue: string): void => {
    if (value === undefined) {
      setInternalValue(nextValue);
    }
    onValueChange?.(nextValue);
  };

  return (
    <div className={cn("flex w-full flex-col gap-5", containerClassName)}>
      <div
        aria-label="Authentication options"
        className="inline-flex w-fit items-center gap-1 rounded-full border border-border/60 bg-background/80 p-1 shadow-[0_1px_0_rgba(255,255,255,0.7)_inset,0_18px_50px_rgba(15,23,42,0.08)] backdrop-blur"
        role="tablist"
      >
        {tabs.map((tab) => {
          const selected = tab.value === activeTab.value;
          const panelId = `${tabListId}-${tab.value}-panel`;
          const triggerId = `${tabListId}-${tab.value}-tab`;

          return (
            <button
              aria-controls={panelId}
              aria-selected={selected}
              className={cn(
                "rounded-full px-4 py-2 text-sm font-semibold tracking-tight text-muted-foreground transition-all duration-200 hover:text-foreground",
                selected &&
                  cn(
                    "bg-foreground text-background shadow-[0_10px_30px_rgba(15,23,42,0.18)]",
                    activeTabClassName,
                  ),
                tabClassName,
              )}
              id={triggerId}
              key={tab.value}
              onClick={() => handleValueChange(tab.value)}
              role="tab"
              type="button"
            >
              {tab.title}
            </button>
          );
        })}
      </div>

      <div
        aria-labelledby={`${tabListId}-${activeTab.value}-tab`}
        className={cn("[animation:auth-tab-panel_220ms_ease] outline-none", contentClassName)}
        id={`${tabListId}-${activeTab.value}-panel`}
        role="tabpanel"
      >
        {activeTab.content}
      </div>
    </div>
  );
}
