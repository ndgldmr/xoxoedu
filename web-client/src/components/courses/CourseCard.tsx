import Link from "next/link";
import Image from "next/image";
import { GraduationCap } from "lucide-react";

export interface CourseCardData {
  id: string;
  slug: string;
  title: string;
  description: string;
  thumbnail_url: string | null;
  instructor_name: string;
  price: number;
  rating_avg: number | null;
  rating_count: number;
  level: "beginner" | "intermediate" | "advanced";
}

export function CourseCard({ course }: { course: CourseCardData }) {
  const isFree = course.price === 0;

  return (
    <Link
      href={`/courses/${course.slug}`}
      className="group flex flex-col bg-surface-base rounded-xl border border-border overflow-hidden hover:shadow-md transition-shadow"
    >
      <div className="relative aspect-video bg-surface-raised">
        {course.thumbnail_url ? (
          <Image
            src={course.thumbnail_url}
            alt={course.title}
            fill
            className="object-cover"
            sizes="(max-width: 768px) 100vw, 33vw"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <GraduationCap className="w-10 h-10 text-content-secondary/30" />
          </div>
        )}
      </div>

      <div className="flex flex-col flex-1 p-4">
        <h3 className="font-medium text-content-primary text-sm leading-snug line-clamp-2 group-hover:text-brand-secondary transition-colors">
          {course.title}
        </h3>
        <p className="text-xs text-content-secondary mt-1">{course.instructor_name}</p>

        <div className="flex items-center gap-1 mt-2">
          {course.rating_avg != null && (
            <>
              <span className="text-xs font-semibold text-brand-primary">
                {course.rating_avg.toFixed(1)}
              </span>
              <span className="text-brand-primary text-xs">★</span>
              <span className="text-xs text-content-secondary">({course.rating_count})</span>
            </>
          )}
          <span className="text-xs text-content-secondary capitalize ml-auto">{course.level}</span>
        </div>

        <div className="mt-3 pt-3 border-t border-border">
          <span className={`text-sm font-semibold ${isFree ? "text-green-600" : "text-content-primary"}`}>
            {isFree ? "Free" : `$${(course.price / 100).toFixed(2)}`}
          </span>
        </div>
      </div>
    </Link>
  );
}
