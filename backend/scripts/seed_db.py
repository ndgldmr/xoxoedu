#!/usr/bin/env python3
"""
Seed the database with realistic dummy data for manual API testing.

Usage:
    uv run scripts/seed_db.py              # seed (skips if already seeded)
    uv run scripts/seed_db.py --reset      # wipe all seed data and re-seed
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_SEED_MARKER_SLUG = "python-for-beginners"


async def _reset(db) -> None:
    from sqlalchemy import text

    tables = [
        "user_bookmarks",
        "user_notes",
        "lesson_progress",
        "assignment_submissions",
        "quiz_submissions",
        "enrollments",
        "lesson_resources",
        "assignments",
        "quiz_questions",
        "quizzes",
        "lessons",
        "chapters",
        "courses",
        "categories",
        "sessions",
        "oauth_accounts",
        "user_profiles",
        "users",
    ]
    for table in tables:
        await db.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
    await db.commit()
    print("[~] All tables truncated.")


async def main(reset: bool = False) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings
    from app.core.security import hash_password
    from app.db.models.assignment import Assignment, AssignmentSubmission
    from app.db.models.course import Category, Chapter, Course, Lesson, LessonResource
    from app.db.models.enrollment import Enrollment, LessonProgress, UserBookmark, UserNote
    from app.db.models.quiz import Quiz, QuizQuestion, QuizSubmission
    from app.db.models.user import User, UserProfile

    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        if reset:
            await _reset(db)
        else:
            existing = await db.scalar(
                select(Course).where(Course.slug == _SEED_MARKER_SLUG)
            )
            if existing:
                print("[!] Database already seeded. Use --reset to re-seed.")
                await engine.dispose()
                return

        # ── Categories ───────────────────────────────────────────────────────
        programming = Category(name="Programming", slug="programming")
        design = Category(name="Design", slug="design")
        db.add_all([programming, design])
        await db.flush()

        python_cat = Category(name="Python", slug="python", parent_id=programming.id)
        js_cat = Category(name="JavaScript", slug="javascript", parent_id=programming.id)
        uiux_cat = Category(name="UI/UX", slug="ui-ux", parent_id=design.id)
        db.add_all([python_cat, js_cat, uiux_cat])
        await db.flush()
        print("[+] Created 5 categories.")

        # ── Users ────────────────────────────────────────────────────────────
        admin = User(
            email="admin@xoxoedu.com",
            password_hash=hash_password("admin123"),
            role="admin",
            email_verified=True,
        )
        alice = User(
            email="alice@example.com",
            password_hash=hash_password("password123"),
            role="student",
            email_verified=True,
        )
        bob = User(
            email="bob@example.com",
            password_hash=hash_password("password123"),
            role="student",
            email_verified=True,
        )
        carol = User(
            email="carol@example.com",
            password_hash=hash_password("password123"),
            role="student",
            email_verified=False,
        )
        db.add_all([admin, alice, bob, carol])
        await db.flush()

        db.add_all([
            UserProfile(user_id=admin.id, display_name="Admin", headline="Platform administrator"),
            UserProfile(
                user_id=alice.id,
                display_name="Alice",
                bio="Aspiring developer learning Python.",
                skills=["Python"],
            ),
            UserProfile(
                user_id=bob.id,
                display_name="Bob",
                bio="Career changer with a background in finance.",
                skills=["Python", "JavaScript"],
            ),
            UserProfile(user_id=carol.id, display_name="Carol"),
        ])
        await db.flush()
        print("[+] Created 4 users (1 admin, 3 students).")

        # ── Course 1: Python for Beginners (published, free) ─────────────────
        py_course = Course(
            slug="python-for-beginners",
            title="Python for Beginners",
            description=(
                "A complete introduction to Python programming. "
                "Learn variables, control flow, functions, and more with hands-on exercises."
            ),
            category_id=python_cat.id,
            level="beginner",
            price_cents=0,
            status="published",
            display_instructor_name="Admin",
            display_instructor_bio="Experienced Python developer and educator.",
            created_by=admin.id,
        )
        db.add(py_course)
        await db.flush()

        py_ch1 = Chapter(course_id=py_course.id, title="Getting Started", position=1)
        db.add(py_ch1)
        await db.flush()

        l1 = Lesson(
            chapter_id=py_ch1.id, title="Welcome to the Course", type="text",
            position=1, is_free_preview=True,
            content={"html": "<h2>Welcome!</h2><p>In this course you will learn Python from the ground up.</p>"},
        )
        l2 = Lesson(
            chapter_id=py_ch1.id, title="Installing Python", type="video",
            position=2, is_free_preview=True,
            video_asset_id="mux-asset-001",
            content={"duration_seconds": 420},
        )
        l3 = Lesson(
            chapter_id=py_ch1.id, title="Your First Program", type="text",
            position=3,
            content={"html": "<p>Let's write <code>print('Hello, world!')</code> together.</p>"},
        )
        db.add_all([l1, l2, l3])
        await db.flush()

        py_ch2 = Chapter(course_id=py_course.id, title="Control Flow", position=2)
        db.add(py_ch2)
        await db.flush()

        l4 = Lesson(
            chapter_id=py_ch2.id, title="If Statements", type="text", position=1,
            content={"html": "<p>Conditional logic with <code>if</code>, <code>elif</code>, and <code>else</code>.</p>"},
        )
        l5 = Lesson(
            chapter_id=py_ch2.id, title="Loops", type="video", position=2,
            video_asset_id="mux-asset-002",
            content={"duration_seconds": 600},
        )
        l6 = Lesson(chapter_id=py_ch2.id, title="Control Flow Quiz", type="quiz", position=3)
        l7 = Lesson(chapter_id=py_ch2.id, title="FizzBuzz Assignment", type="assignment", position=4)
        db.add_all([l4, l5, l6, l7])
        await db.flush()

        db.add(LessonResource(
            lesson_id=l2.id,
            name="Python Installation Guide.pdf",
            file_url="https://example.com/resources/python-install-guide.pdf",
            file_type="application/pdf",
            size_bytes=204_800,
        ))

        quiz1 = Quiz(
            lesson_id=l6.id,
            title="Control Flow Quiz",
            description="Test your knowledge of if statements and loops.",
            max_attempts=3,
            time_limit_minutes=10,
        )
        db.add(quiz1)
        await db.flush()

        q1 = QuizQuestion(
            quiz_id=quiz1.id, position=1, kind="single_choice",
            stem="Which keyword introduces a conditional branch in Python?",
            options=[
                {"id": "a", "text": "when"},
                {"id": "b", "text": "if"},
                {"id": "c", "text": "case"},
                {"id": "d", "text": "check"},
            ],
            correct_answers=["b"], points=1,
        )
        q2 = QuizQuestion(
            quiz_id=quiz1.id, position=2, kind="multi_choice",
            stem="Which of the following are valid Python loop constructs?",
            options=[
                {"id": "a", "text": "for"},
                {"id": "b", "text": "while"},
                {"id": "c", "text": "repeat"},
                {"id": "d", "text": "loop"},
            ],
            correct_answers=["a", "b"], points=2,
        )
        q3 = QuizQuestion(
            quiz_id=quiz1.id, position=3, kind="single_choice",
            stem="What does `range(3)` produce?",
            options=[
                {"id": "a", "text": "1, 2, 3"},
                {"id": "b", "text": "0, 1, 2"},
                {"id": "c", "text": "0, 1, 2, 3"},
                {"id": "d", "text": "1, 2"},
            ],
            correct_answers=["b"], points=1,
        )
        db.add_all([q1, q2, q3])

        asgn1 = Assignment(
            lesson_id=l7.id,
            title="FizzBuzz Challenge",
            instructions=(
                "Write a Python script that prints numbers 1–100, replacing multiples of 3 "
                "with `Fizz`, multiples of 5 with `Buzz`, and multiples of both with `FizzBuzz`. "
                "Upload your `.py` file."
            ),
            allowed_extensions=["py"],
            max_file_size_bytes=1_048_576,
        )
        db.add(asgn1)
        await db.flush()
        print("[+] Created course 'Python for Beginners' (2 chapters, 7 lessons).")

        # ── Course 2: JavaScript Fundamentals (published, paid) ───────────────
        js_course = Course(
            slug="javascript-fundamentals",
            title="JavaScript Fundamentals",
            description=(
                "Master the core concepts of JavaScript: variables, functions, "
                "closures, async/await, and the DOM."
            ),
            category_id=js_cat.id,
            level="intermediate",
            price_cents=2999,
            status="published",
            display_instructor_name="Admin",
            display_instructor_bio="Full-stack JavaScript engineer with 10 years of experience.",
            created_by=admin.id,
        )
        db.add(js_course)
        await db.flush()

        js_ch1 = Chapter(course_id=js_course.id, title="The Basics", position=1)
        db.add(js_ch1)
        await db.flush()

        jsl1 = Lesson(
            chapter_id=js_ch1.id, title="What is JavaScript?", type="text",
            position=1, is_free_preview=True,
            content={"html": "<p>JavaScript is the language of the web. It runs in every browser.</p>"},
        )
        jsl2 = Lesson(
            chapter_id=js_ch1.id, title="Variables and Types", type="video",
            position=2, video_asset_id="mux-asset-003",
            content={"duration_seconds": 540},
        )
        jsl3 = Lesson(chapter_id=js_ch1.id, title="Quiz: Variables", type="quiz", position=3)
        db.add_all([jsl1, jsl2, jsl3])
        await db.flush()

        js_ch2 = Chapter(course_id=js_course.id, title="Functions", position=2)
        db.add(js_ch2)
        await db.flush()

        jsl4 = Lesson(
            chapter_id=js_ch2.id, title="Function Declarations", type="text", position=1,
            content={"html": "<p>Functions are first-class citizens in JavaScript.</p>"},
        )
        jsl5 = Lesson(
            chapter_id=js_ch2.id, title="Arrow Functions", type="video",
            position=2, video_asset_id="mux-asset-004",
            content={"duration_seconds": 480},
        )
        db.add_all([jsl4, jsl5])
        await db.flush()

        js_quiz = Quiz(
            lesson_id=jsl3.id, title="Variables Quiz",
            max_attempts=2, time_limit_minutes=5,
        )
        db.add(js_quiz)
        await db.flush()

        db.add_all([
            QuizQuestion(
                quiz_id=js_quiz.id, position=1, kind="single_choice",
                stem="Which keyword declares a block-scoped variable in modern JavaScript?",
                options=[
                    {"id": "a", "text": "var"},
                    {"id": "b", "text": "let"},
                    {"id": "c", "text": "def"},
                    {"id": "d", "text": "dim"},
                ],
                correct_answers=["b"], points=1,
            ),
            QuizQuestion(
                quiz_id=js_quiz.id, position=2, kind="multi_choice",
                stem="Which of the following are JavaScript primitive types?",
                options=[
                    {"id": "a", "text": "string"},
                    {"id": "b", "text": "number"},
                    {"id": "c", "text": "list"},
                    {"id": "d", "text": "boolean"},
                ],
                correct_answers=["a", "b", "d"], points=2,
            ),
        ])
        await db.flush()
        print("[+] Created course 'JavaScript Fundamentals' (2 chapters, 5 lessons).")

        # ── Course 3: UI/UX Design Principles (draft) ─────────────────────────
        uiux_course = Course(
            slug="uiux-design-principles",
            title="UI/UX Design Principles",
            description=(
                "Learn user-centered design thinking, wireframing, prototyping, "
                "and usability testing."
            ),
            category_id=uiux_cat.id,
            level="beginner",
            price_cents=4999,
            status="draft",
            display_instructor_name="Admin",
            created_by=admin.id,
        )
        db.add(uiux_course)
        await db.flush()

        usch1 = Chapter(course_id=uiux_course.id, title="Design Thinking", position=1)
        db.add(usch1)
        await db.flush()

        db.add_all([
            Lesson(
                chapter_id=usch1.id, title="Introduction to Design Thinking",
                type="text", position=1, is_free_preview=True,
                content={"html": "<p>Design thinking is a human-centered approach to problem solving.</p>"},
            ),
            Lesson(
                chapter_id=usch1.id, title="User Research Methods",
                type="text", position=2,
                content={"html": "<p>Interviews, surveys, and usability tests help you understand your users.</p>"},
            ),
        ])
        await db.flush()
        print("[+] Created course 'UI/UX Design Principles' — draft (1 chapter, 2 lessons).")

        # ── Enrollments ──────────────────────────────────────────────────────
        now = datetime.now(timezone.utc)

        enroll_alice_py = Enrollment(user_id=alice.id, course_id=py_course.id, status="active")
        enroll_alice_js = Enrollment(user_id=alice.id, course_id=js_course.id, status="active")
        enroll_bob_py = Enrollment(
            user_id=bob.id, course_id=py_course.id,
            status="completed", completed_at=now,
        )
        db.add_all([enroll_alice_py, enroll_alice_js, enroll_bob_py])
        await db.flush()
        print("[+] Created 3 enrollments.")

        # ── Lesson Progress ──────────────────────────────────────────────────
        # Alice: Python ch1 fully done, ch2 l4 done, l5 in progress
        alice_progress = [
            LessonProgress(user_id=alice.id, lesson_id=l1.id, status="completed", completed_at=now),
            LessonProgress(user_id=alice.id, lesson_id=l2.id, status="completed", completed_at=now, watch_seconds=420),
            LessonProgress(user_id=alice.id, lesson_id=l3.id, status="completed", completed_at=now),
            LessonProgress(user_id=alice.id, lesson_id=l4.id, status="completed", completed_at=now),
            LessonProgress(user_id=alice.id, lesson_id=l5.id, status="in_progress", watch_seconds=180),
            # JS: only viewed the free preview
            LessonProgress(user_id=alice.id, lesson_id=jsl1.id, status="completed", completed_at=now),
        ]
        # Bob: Python all lessons completed
        bob_progress = [
            LessonProgress(user_id=bob.id, lesson_id=l1.id, status="completed", completed_at=now),
            LessonProgress(user_id=bob.id, lesson_id=l2.id, status="completed", completed_at=now, watch_seconds=420),
            LessonProgress(user_id=bob.id, lesson_id=l3.id, status="completed", completed_at=now),
            LessonProgress(user_id=bob.id, lesson_id=l4.id, status="completed", completed_at=now),
            LessonProgress(user_id=bob.id, lesson_id=l5.id, status="completed", completed_at=now, watch_seconds=600),
            LessonProgress(user_id=bob.id, lesson_id=l6.id, status="completed", completed_at=now),
            LessonProgress(user_id=bob.id, lesson_id=l7.id, status="completed", completed_at=now),
        ]
        db.add_all(alice_progress + bob_progress)
        await db.flush()
        print("[+] Created lesson progress records.")

        # ── Quiz Submissions ─────────────────────────────────────────────────
        # Alice: failed attempt 1, passed attempt 2
        # Bob: passed on first attempt
        db.add_all([
            QuizSubmission(
                user_id=alice.id, quiz_id=quiz1.id, attempt_number=1,
                answers={str(q1.id): ["a"], str(q2.id): ["a"], str(q3.id): ["a"]},
                score=0, max_score=4, passed=False,
            ),
            QuizSubmission(
                user_id=alice.id, quiz_id=quiz1.id, attempt_number=2,
                answers={str(q1.id): ["b"], str(q2.id): ["a", "b"], str(q3.id): ["b"]},
                score=4, max_score=4, passed=True,
            ),
            QuizSubmission(
                user_id=bob.id, quiz_id=quiz1.id, attempt_number=1,
                answers={str(q1.id): ["b"], str(q2.id): ["a", "b"], str(q3.id): ["b"]},
                score=4, max_score=4, passed=True,
            ),
        ])
        await db.flush()
        print("[+] Created 3 quiz submissions.")

        # ── Assignment Submission ─────────────────────────────────────────────
        db.add(AssignmentSubmission(
            user_id=alice.id,
            assignment_id=asgn1.id,
            file_key="assignments/fizzbuzz-alice.py",
            file_name="fizzbuzz.py",
            file_size=512,
            mime_type="text/x-python",
            scan_status="clean",
            submitted_at=now,
        ))
        await db.flush()
        print("[+] Created 1 assignment submission.")

        # ── Notes & Bookmarks ────────────────────────────────────────────────
        db.add_all([
            UserNote(user_id=alice.id, lesson_id=l2.id, content="Remember to add Python to PATH on Windows!"),
            UserNote(user_id=alice.id, lesson_id=l4.id, content="`elif` is Python's version of else-if."),
        ])
        db.add_all([
            UserBookmark(user_id=alice.id, lesson_id=l5.id),
            UserBookmark(user_id=alice.id, lesson_id=jsl2.id),
        ])
        await db.commit()
        print("[+] Created 2 notes and 2 bookmarks.")

        print()
        print("Seed complete.")
        print()
        print("  Credentials")
        print("  ───────────────────────────────────────────────────────────")
        print("  admin@xoxoedu.com  / admin123       role: admin")
        print("  alice@example.com  / password123    role: student  (enrolled, in progress)")
        print("  bob@example.com    / password123    role: student  (completed Python)")
        print("  carol@example.com  / password123    role: student  (not enrolled, unverified email)")

    await engine.dispose()


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    asyncio.run(main(reset=reset))
