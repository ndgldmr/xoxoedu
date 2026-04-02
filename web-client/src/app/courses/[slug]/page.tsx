import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { EnrollButton } from "./EnrollButton";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Lesson {
  id: string;
  title: string;
  order: number;
  is_preview: boolean;
  duration_seconds: number | null;
}

interface Chapter {
  id: string;
  title: string;
  order: number;
  lessons: Lesson[];
}

interface Review {
  id: string;
  reviewer_name: string;
  rating: number;
  comment: string | null;
  created_at: string;
}

interface CourseDetail {
  id: string;
  slug: string;
  title: string;
  description: string;
  thumbnail_url: string | null;
  price: number;
  level: string;
  language: string;
  rating_avg: number | null;
  rating_count: number;
  instructor: {
    id: string;
    display_name: string;
    bio: string | null;
    avatar_url: string | null;
  };
  chapters: Chapter[];
}

async function getCourse(slug: string): Promise<CourseDetail | null> {
  try {
    const res = await fetch(`${API_URL}/api/v1/courses/${slug}`, {
      next: { revalidate: 60 },
    });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error("Failed to fetch course");
    return res.json() as Promise<CourseDetail>;
  } catch {
    return null;
  }
}

// TODO: implement when backend delivers GET /api/v1/courses/{slug}/reviews
// eslint-disable-next-line @typescript-eslint/no-unused-vars
async function getCourseReviews(_slug: string): Promise<Review[]> {
  return [];
}

export async function generateMetadata({
  params,
}: {
  params: { slug: string };
}): Promise<Metadata> {
  const course = await getCourse(params.slug);
  if (!course) return { title: "Course not found" };
  return {
    title: `${course.title} — XOXO Education`,
    description: course.description,
  };
}

function formatDuration(seconds: number) {
  const m = Math.floor(seconds / 60);
  return `${m}m`;
}

function StarRating({ rating }: { rating: number }) {
  return (
    <span className="text-amber-400">
      {Array.from({ length: 5 }).map((_, i) => (
        <span key={i}>{i < Math.round(rating) ? "★" : "☆"}</span>
      ))}
    </span>
  );
}

export default async function CourseDetailPage({
  params,
}: {
  params: { slug: string };
}) {
  const [course, reviews] = await Promise.all([
    getCourse(params.slug),
    getCourseReviews(params.slug),
  ]);

  if (!course) notFound();

  const isFree = course.price === 0;
  const totalLessons = course.chapters.reduce(
    (sum, ch) => sum + ch.lessons.length,
    0
  );

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Hero */}
      <div className="bg-gray-900 text-white">
        <div className="max-w-5xl mx-auto px-4 py-12">
          <p className="text-sm text-indigo-400 capitalize mb-2">{course.level}</p>
          <h1 className="text-3xl font-bold leading-snug mb-3">{course.title}</h1>
          <p className="text-gray-300 max-w-2xl mb-4">{course.description}</p>
          <div className="flex items-center gap-4 text-sm text-gray-400 flex-wrap">
            <span>
              By <span className="text-white font-medium">{course.instructor.display_name}</span>
            </span>
            {course.rating_avg != null && (
              <span className="text-amber-400 font-medium">
                ★ {course.rating_avg.toFixed(1)}{" "}
                <span className="text-gray-400 font-normal">({course.rating_count} reviews)</span>
              </span>
            )}
            <span>{totalLessons} lessons</span>
          </div>

          <div className="mt-6 flex items-center gap-4">
            <span className="text-2xl font-bold">
              {isFree ? "Free" : `$${(course.price / 100).toFixed(2)}`}
            </span>
            <EnrollButton courseId={course.id} courseSlug={course.slug} isFree={isFree} />
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-4 py-10 grid grid-cols-1 lg:grid-cols-3 gap-10">
        {/* Left column: syllabus + reviews */}
        <div className="lg:col-span-2 space-y-10">
          {/* Syllabus */}
          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Course content</h2>
            <div className="space-y-3">
              {course.chapters
                .sort((a, b) => a.order - b.order)
                .map((chapter) => (
                  <details
                    key={chapter.id}
                    className="bg-white border border-gray-200 rounded-lg overflow-hidden"
                  >
                    <summary className="px-4 py-3 cursor-pointer font-medium text-sm text-gray-900 flex items-center justify-between select-none">
                      <span>{chapter.title}</span>
                      <span className="text-xs text-gray-400 font-normal">
                        {chapter.lessons.length} lessons
                      </span>
                    </summary>
                    <ul className="border-t border-gray-100 divide-y divide-gray-50">
                      {chapter.lessons
                        .sort((a, b) => a.order - b.order)
                        .map((lesson) => (
                          <li
                            key={lesson.id}
                            className="flex items-center justify-between px-4 py-2 text-sm text-gray-700"
                          >
                            <span className="flex items-center gap-2">
                              {lesson.is_preview ? (
                                <span className="text-indigo-500">▶</span>
                              ) : (
                                <span className="text-gray-300">🔒</span>
                              )}
                              {lesson.title}
                              {lesson.is_preview && (
                                <span className="text-xs bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded">
                                  Preview
                                </span>
                              )}
                            </span>
                            {lesson.duration_seconds != null && (
                              <span className="text-xs text-gray-400 shrink-0 ml-4">
                                {formatDuration(lesson.duration_seconds)}
                              </span>
                            )}
                          </li>
                        ))}
                    </ul>
                  </details>
                ))}
            </div>
          </section>

          {/* Reviews */}
          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-4">
              Student reviews
              {course.rating_count > 0 && (
                <span className="ml-2 text-sm font-normal text-gray-400">
                  ({course.rating_count})
                </span>
              )}
            </h2>

            {reviews.length === 0 ? (
              <div className="bg-white border border-gray-200 rounded-xl p-8 text-center">
                <p className="text-gray-400 text-sm">No reviews yet.</p>
                <p className="text-gray-400 text-xs mt-1">Be the first to review this course.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {reviews.map((review) => (
                  <div
                    key={review.id}
                    className="bg-white border border-gray-200 rounded-xl p-5"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium text-sm text-gray-900">
                        {review.reviewer_name}
                      </span>
                      <span className="text-xs text-gray-400">
                        {new Date(review.created_at).toLocaleDateString()}
                      </span>
                    </div>
                    <StarRating rating={review.rating} />
                    {review.comment && (
                      <p className="mt-2 text-sm text-gray-600 leading-relaxed">
                        {review.comment}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        {/* Right column: Instructor */}
        <aside>
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Instructor</h2>
          <div className="bg-white border border-gray-200 rounded-xl p-5">
            {course.instructor.avatar_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={course.instructor.avatar_url}
                alt={course.instructor.display_name}
                className="w-14 h-14 rounded-full object-cover mb-3"
              />
            ) : (
              <div className="w-14 h-14 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 text-xl font-bold mb-3">
                {course.instructor.display_name[0]}
              </div>
            )}
            <p className="font-medium text-gray-900">{course.instructor.display_name}</p>
            {course.instructor.bio && (
              <p className="text-sm text-gray-500 mt-2 leading-relaxed">{course.instructor.bio}</p>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
