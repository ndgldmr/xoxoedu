"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { CourseCard, type CourseCardData } from "@/components/courses/CourseCard";
import { FilterSidebar } from "@/components/courses/FilterSidebar";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const PAGE_SIZE = 12;

interface CoursesResponse {
  data: CourseCardData[];
  meta: {
    total: number;
    skip: number;
    limit: number;
  };
  error: string | null;
}

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

function CourseBrowseContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const searchInput = searchParams.get("search") ?? "";
  const [localSearch, setLocalSearch] = useState(searchInput);
  const debouncedSearch = useDebouncedValue(localSearch, 300);
  const isFirstRender = useRef(true);

  // Push debounced search value into URL
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    const params = new URLSearchParams(searchParams.toString());
    if (debouncedSearch) {
      params.set("search", debouncedSearch);
    } else {
      params.delete("search");
    }
    params.delete("page");
    router.push(`/courses?${params.toString()}`);
  }, [debouncedSearch]); // eslint-disable-line react-hooks/exhaustive-deps

  const level = searchParams.get("level");
  const price = searchParams.get("price");
  const page = Number(searchParams.get("page") ?? "1");
  const skip = (page - 1) * PAGE_SIZE;

  const queryParams = new URLSearchParams();
  if (debouncedSearch) queryParams.set("search", debouncedSearch);
  if (level) queryParams.set("level", level);
  if (price) queryParams.set("price", price);
  queryParams.set("skip", String(skip));
  queryParams.set("limit", String(PAGE_SIZE));

  const { data, isLoading, isError } = useQuery<CoursesResponse>({
    queryKey: ["courses", debouncedSearch, level, price, page],
    queryFn: async () => {
      const res = await fetch(`${API_URL}/api/v1/courses?${queryParams.toString()}`);
      if (!res.ok) throw new Error("Failed to fetch courses");
      return res.json() as Promise<CoursesResponse>;
    },
  });

  const total = data?.meta.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  function goToPage(p: number) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("page", String(p));
    router.push(`/courses?${params.toString()}`);
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold text-gray-900">Browse Courses</h1>
        </div>

        {/* Search bar */}
        <div className="mb-6">
          <input
            type="search"
            placeholder="Search courses…"
            value={localSearch}
            onChange={(e) => setLocalSearch(e.target.value)}
            className="w-full max-w-md border border-gray-300 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>

        <div className="flex gap-8">
          <FilterSidebar />

          <div className="flex-1 min-w-0">
            {isLoading ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div
                    key={i}
                    className="bg-gray-200 rounded-xl aspect-[4/3] animate-pulse"
                  />
                ))}
              </div>
            ) : isError ? (
              <p className="text-red-600 text-sm">Failed to load courses. Please try again.</p>
            ) : !data || data.data.length === 0 ? (
              <p className="text-gray-500 text-sm">No courses found.</p>
            ) : (
              <>
                <p className="text-xs text-gray-400 mb-4">{total} courses</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
                  {data.data.map((course) => (
                    <CourseCard key={course.id} course={course} />
                  ))}
                </div>

                {totalPages > 1 && (
                  <div className="flex items-center justify-center gap-2 mt-8">
                    <button
                      onClick={() => goToPage(page - 1)}
                      disabled={page <= 1}
                      className="px-3 py-1 text-sm border border-gray-300 rounded-lg disabled:opacity-40 hover:bg-gray-100"
                    >
                      ← Prev
                    </button>
                    <span className="text-sm text-gray-500">
                      {page} / {totalPages}
                    </span>
                    <button
                      onClick={() => goToPage(page + 1)}
                      disabled={page >= totalPages}
                      className="px-3 py-1 text-sm border border-gray-300 rounded-lg disabled:opacity-40 hover:bg-gray-100"
                    >
                      Next →
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function CourseBrowsePage() {
  return (
    <Suspense>
      <CourseBrowseContent />
    </Suspense>
  );
}
