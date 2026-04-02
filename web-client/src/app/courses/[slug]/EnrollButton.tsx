"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/stores/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type EnrollmentStatus = "unenrolled" | "enrolled" | "completed" | "loading";

interface Enrollment {
  id: string;
  course_id: string;
  status: string;
  completed_at: string | null;
}

export function EnrollButton({
  courseId,
  courseSlug,
  isFree,
}: {
  courseId: string;
  courseSlug: string;
  isFree: boolean;
}) {
  const router = useRouter();
  const { accessToken } = useAuthStore();
  const [enrollmentStatus, setEnrollmentStatus] = useState<EnrollmentStatus>("unenrolled");
  const [enrollLoading, setEnrollLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Check enrollment status when user is authenticated
  useEffect(() => {
    if (!accessToken) return;
    setEnrollmentStatus("loading");

    fetch(`${API_URL}/api/v1/users/me/enrollments`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      credentials: "include",
    })
      .then(async (res) => {
        if (!res.ok) { setEnrollmentStatus("unenrolled"); return; }
        const json = (await res.json()) as { data?: Enrollment[] };
        const enrollments = json.data ?? [];
        const match = enrollments.find((e) => e.course_id === courseId);
        if (!match) {
          setEnrollmentStatus("unenrolled");
        } else if (match.completed_at || match.status === "completed") {
          setEnrollmentStatus("completed");
        } else {
          setEnrollmentStatus("enrolled");
        }
      })
      .catch(() => setEnrollmentStatus("unenrolled"));
  }, [accessToken, courseId]);

  async function handleEnroll() {
    if (!accessToken) {
      router.push(`/login?next=/courses/${courseSlug}`);
      return;
    }

    setEnrollLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_URL}/api/v1/enrollments`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        credentials: "include",
        body: JSON.stringify({ course_id: courseId }),
      });

      if (!res.ok) {
        const data = (await res.json()) as { detail?: string };
        setError(data.detail ?? "Enrollment failed.");
        return;
      }

      setEnrollmentStatus("enrolled");
      router.push(`/learn/${courseSlug}`);
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setEnrollLoading(false);
    }
  }

  if (enrollmentStatus === "loading") {
    return <div className="h-10 w-40 bg-white/20 rounded-lg animate-pulse" />;
  }

  if (enrollmentStatus === "completed") {
    return (
      <Link
        href="/me/certificates"
        className="bg-green-600 hover:bg-green-700 text-white font-medium px-6 py-2.5 rounded-lg transition-colors inline-block"
      >
        View certificate
      </Link>
    );
  }

  if (enrollmentStatus === "enrolled") {
    return (
      <Link
        href={`/learn/${courseSlug}`}
        className="bg-indigo-600 hover:bg-indigo-700 text-white font-medium px-6 py-2.5 rounded-lg transition-colors inline-block"
      >
        Continue learning
      </Link>
    );
  }

  return (
    <div>
      <button
        onClick={handleEnroll}
        disabled={enrollLoading}
        className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-medium px-6 py-2.5 rounded-lg transition-colors"
      >
        {enrollLoading ? "Enrolling…" : isFree ? "Enroll for free" : "Buy now"}
      </button>
      {error && <p className="text-red-400 text-sm mt-2">{error}</p>}
    </div>
  );
}
