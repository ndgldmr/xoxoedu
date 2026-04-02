import Link from "next/link";
import { Sparkles, GraduationCap, Smartphone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/layout/Logo";
import { CourseCard, type CourseCardData } from "@/components/courses/CourseCard";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function getFeaturedCourses(): Promise<CourseCardData[]> {
  try {
    const res = await fetch(`${API_URL}/api/v1/courses?limit=4`, {
      next: { revalidate: 300 },
    });
    if (!res.ok) return [];
    const json = (await res.json()) as { data: CourseCardData[] };
    return json.data;
  } catch {
    return [];
  }
}

const VALUE_PROPS = [
  {
    icon: Sparkles,
    title: "AI feedback on everything",
    body: "Submit a quiz or assignment and get detailed, constructive AI feedback within minutes — no waiting for a human to grade.",
  },
  {
    icon: GraduationCap,
    title: "Earn real certificates",
    body: "Complete a course and earn a verifiable certificate with a unique token anyone can check online.",
  },
  {
    icon: Smartphone,
    title: "Learn on any device",
    body: "Full feature parity on web and mobile. Pick up exactly where you left off, on any screen.",
  },
];

export default async function LandingPage() {
  const featuredCourses = await getFeaturedCourses();

  return (
    <div className="min-h-screen bg-surface-base">
      {/* Nav */}
      <header className="border-b border-border">
        <div className="max-w-7xl mx-auto px-4 h-16 flex items-center justify-between">
          <Logo height={36} />
          <nav className="flex items-center gap-6">
            <Link
              href="/courses"
              className="text-sm text-content-secondary hover:text-content-primary transition-colors"
            >
              Courses
            </Link>
            <Link
              href="/login"
              className="text-sm text-content-secondary hover:text-content-primary transition-colors"
            >
              Sign in
            </Link>
            <Button asChild size="sm">
              <Link href="/register">Get started</Link>
            </Button>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="bg-gradient-to-b from-amber-50 to-surface-base pt-20 pb-24 px-4 text-center">
        <h1 className="text-5xl font-bold text-content-primary leading-tight max-w-3xl mx-auto">
          Learn anything with{" "}
          <span className="text-brand-primary">AI-powered</span> feedback
        </h1>
        <p className="mt-5 text-lg text-content-secondary max-w-xl mx-auto">
          Expert-built courses with instant AI feedback on every quiz and
          assignment — so you always know exactly where to improve.
        </p>
        <div className="mt-8 flex items-center justify-center gap-4">
          <Button asChild size="lg">
            <Link href="/courses">Browse courses</Link>
          </Button>
          <Button asChild size="lg" variant="outline">
            <Link href="/register">Sign up free</Link>
          </Button>
        </div>
        <p className="mt-8 text-xs text-content-secondary uppercase tracking-wider">
          Join thousands of learners already on the platform
        </p>
      </section>

      {/* Value props */}
      <section className="max-w-5xl mx-auto px-4 py-16">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {VALUE_PROPS.map(({ icon: Icon, title, body }) => (
            <div key={title} className="bg-surface-raised rounded-2xl p-6 text-left">
              <div className="w-10 h-10 rounded-lg bg-brand-primary/10 flex items-center justify-center">
                <Icon className="w-5 h-5 text-brand-primary" />
              </div>
              <h3 className="mt-3 font-semibold text-content-primary">{title}</h3>
              <p className="mt-2 text-sm text-content-secondary leading-relaxed">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Featured courses */}
      {featuredCourses.length > 0 && (
        <section className="max-w-7xl mx-auto px-4 pb-20">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-xl font-semibold text-content-primary">Featured courses</h2>
            <Link
              href="/courses"
              className="text-sm text-brand-secondary hover:underline"
            >
              View all →
            </Link>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {featuredCourses.map((course) => (
              <CourseCard key={course.id} course={course} />
            ))}
          </div>
        </section>
      )}

      {/* Footer */}
      <footer className="border-t border-border py-8 px-4">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <Logo height={30} />
          <nav className="flex items-center gap-6 text-sm text-content-secondary">
            <Link href="/courses" className="hover:text-content-primary transition-colors">Courses</Link>
            <Link href="/login" className="hover:text-content-primary transition-colors">Sign in</Link>
            <Link href="/register" className="hover:text-content-primary transition-colors">Register</Link>
          </nav>
          <p className="text-xs text-content-secondary">© {new Date().getFullYear()} XOXO Education</p>
        </div>
      </footer>
    </div>
  );
}
