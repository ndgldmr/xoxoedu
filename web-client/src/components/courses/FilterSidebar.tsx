"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const LEVELS = ["beginner", "intermediate", "advanced"] as const;
const LANGUAGES = ["English", "Arabic", "French", "Spanish"] as const;

function RadioGroup({
  name,
  options,
  selected,
  onSelect,
  onClear,
}: {
  name: string;
  options: readonly string[];
  selected: string | null;
  onSelect: (v: string) => void;
  onClear: () => void;
}) {
  return (
    <div className="space-y-2">
      {options.map((opt) => (
        <label key={opt} className="flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            name={name}
            value={opt}
            checked={selected === opt}
            onChange={() => onSelect(opt)}
            className="accent-brand-primary"
          />
          <span className="text-sm text-content-primary capitalize">{opt}</span>
        </label>
      ))}
      {selected && (
        <button
          onClick={onClear}
          className="text-xs text-brand-secondary hover:underline mt-1"
        >
          Clear
        </button>
      )}
    </div>
  );
}

export function FilterSidebar() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [categories, setCategories] = useState<string[]>([]);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/categories`)
      .then(async (res) => {
        if (!res.ok) return;
        const json = (await res.json()) as { data: { name: string }[] | string[] };
        const items = json.data;
        if (items.length === 0) return;
        // Handle both {name: string}[] and string[] response shapes
        const names = items.map((item) =>
          typeof item === "string" ? item : item.name
        );
        setCategories(names);
      })
      .catch(() => {});
  }, []);

  const updateParam = useCallback(
    (key: string, value: string | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value) {
        params.set(key, value);
      } else {
        params.delete(key);
      }
      params.delete("page");
      router.push(`/courses?${params.toString()}`);
    },
    [router, searchParams]
  );

  const level = searchParams.get("level");
  const price = searchParams.get("price");
  const category = searchParams.get("category");
  const language = searchParams.get("language");

  return (
    <aside className="w-56 shrink-0">
      <div className="sticky top-6 space-y-6">
        {categories.length > 0 && (
          <section>
            <h2 className="text-xs font-semibold text-content-muted uppercase tracking-wider mb-3">
              Category
            </h2>
            <RadioGroup
              name="category"
              options={categories}
              selected={category}
              onSelect={(v) => updateParam("category", v)}
              onClear={() => updateParam("category", null)}
            />
          </section>
        )}

        <section>
          <h2 className="text-xs font-semibold text-content-muted uppercase tracking-wider mb-3">
            Level
          </h2>
          <RadioGroup
            name="level"
            options={LEVELS}
            selected={level}
            onSelect={(v) => updateParam("level", v)}
            onClear={() => updateParam("level", null)}
          />
        </section>

        <section>
          <h2 className="text-xs font-semibold text-content-muted uppercase tracking-wider mb-3">
            Price
          </h2>
          <RadioGroup
            name="price"
            options={["free", "paid"]}
            selected={price}
            onSelect={(v) => updateParam("price", v)}
            onClear={() => updateParam("price", null)}
          />
        </section>

        <section>
          <h2 className="text-xs font-semibold text-content-muted uppercase tracking-wider mb-3">
            Language
          </h2>
          <RadioGroup
            name="language"
            options={LANGUAGES}
            selected={language}
            onSelect={(v) => updateParam("language", v)}
            onClear={() => updateParam("language", null)}
          />
        </section>
      </div>
    </aside>
  );
}
