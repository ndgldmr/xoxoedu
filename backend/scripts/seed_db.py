#!/usr/bin/env python3
"""
Seed the database with one admin, one student, and one fully-featured course.

Usage:
    uv run scripts/seed_db.py              # seed (skips if already seeded)
    uv run scripts/seed_db.py --reset      # wipe all seed data and re-seed
"""
import asyncio
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_SEED_MARKER_SLUG = "python-for-beginners"


async def _reset(db) -> None:
    from sqlalchemy import text

    tables = [
        "certificate_requests",
        "certificates",
        "announcements",
        "ai_usage_logs",
        "ai_usage_budgets",
        "quiz_feedback",
        "payments",
        "coupons",
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
    from app.db.models.ai import AIUsageBudget, AIUsageLog
    from app.db.models.announcement import Announcement
    from app.db.models.assignment import Assignment, AssignmentSubmission
    from app.db.models.certificate import Certificate, CertificateRequest
    from app.db.models.coupon import Coupon
    from app.db.models.course import Category, Chapter, Course, Lesson, LessonResource
    from app.db.models.enrollment import Enrollment, LessonProgress, UserBookmark, UserNote
    from app.db.models.payment import Payment
    from app.db.models.quiz import Quiz, QuizFeedback, QuizQuestion, QuizSubmission
    from app.db.models.user import User

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

        now = datetime.now(timezone.utc)

        # ── Category ─────────────────────────────────────────────────────────
        programming = Category(name="Programming", slug="programming")
        db.add(programming)
        await db.flush()
        python_cat = Category(name="Python", slug="python", parent_id=programming.id)
        db.add(python_cat)
        await db.flush()
        print("[+] Created categories.")

        # ── Users ─────────────────────────────────────────────────────────────
        admin = User(
            email="admin@xoxoedu.com",
            password_hash=hash_password("admin123"),
            role="admin",
            email_verified=True,
            display_name="Admin",
            headline="Platform administrator",
        )
        student = User(
            email="student@xoxoedu.com",
            password_hash=hash_password("password123"),
            role="student",
            email_verified=True,
            display_name="Alex Student",
            bio="Learning Python to build my first web app.",
            headline="Aspiring Developer",
            skills=["Python", "HTML"],
            social_links={"github": "https://github.com/alexstudent"},
        )
        db.add_all([admin, student])
        await db.flush()
        print("[+] Created 2 users (1 admin, 1 student).")

        # ── Course ────────────────────────────────────────────────────────────
        course = Course(
            slug="python-for-beginners",
            title="Python for Beginners",
            description=(
                "A complete introduction to Python programming. "
                "Learn variables, control flow, functions, and more with hands-on exercises."
            ),
            category_id=python_cat.id,
            level="beginner",
            price_cents=2999,
            currency="USD",
            status="published",
            display_instructor_name="Admin",
            display_instructor_bio="Experienced Python developer and educator.",
            created_by=admin.id,
        )
        db.add(course)
        await db.flush()

        # ── AI Config ─────────────────────────────────────────────────────────
        db.add(AIUsageBudget(
            course_id=course.id,
            ai_enabled=True,
            tone="encouraging",
            monthly_token_limit=50_000,
            alert_threshold=0.8,
        ))

        # ── Coupons ───────────────────────────────────────────────────────────
        coupon_welcome = Coupon(
            code="WELCOME10",
            discount_type="percentage",
            discount_value=10,
            max_uses=None,
            uses_count=1,
            applies_to=None,
            expires_at=None,
        )
        coupon_course = Coupon(
            code="PYLAUNCH",
            discount_type="fixed",
            discount_value=500,
            max_uses=50,
            uses_count=3,
            applies_to=None,
            expires_at=datetime(2026, 12, 31, tzinfo=timezone.utc),
        )
        db.add_all([coupon_welcome, coupon_course])

        # ── Chapters & Lessons ────────────────────────────────────────────────
        ch1 = Chapter(course_id=course.id, title="Getting Started", position=1)
        db.add(ch1)
        await db.flush()

        l1 = Lesson(
            chapter_id=ch1.id, title="Welcome to the Course", type="text",
            position=1, is_free_preview=True,
            content={"body": "<h2>Welcome!</h2><p>In this course you will learn Python from the ground up.</p>"},
        )
        l2 = Lesson(
            chapter_id=ch1.id, title="Setting Up Your Environment", type="text",
            position=2, is_free_preview=True,
            content={"body": "<p>Install Python 3.12 from python.org and open a terminal to verify with <code>python --version</code>.</p>"},
        )
        l3 = Lesson(
            chapter_id=ch1.id, title="Your First Program", type="text",
            position=3,
            content={"body": "<p>Let's write <code>print('Hello, world!')</code> together.</p>"},
        )
        db.add_all([l1, l2, l3])
        await db.flush()

        db.add(LessonResource(
            lesson_id=l2.id,
            name="Python Setup Guide.pdf",
            file_url="https://example.com/resources/python-setup-guide.pdf",
            file_type="application/pdf",
            size_bytes=204_800,
        ))

        ch2 = Chapter(course_id=course.id, title="Control Flow", position=2)
        db.add(ch2)
        await db.flush()

        l4 = Lesson(
            chapter_id=ch2.id, title="If Statements", type="text", position=1,
            content={"body": "<p>Conditional logic with <code>if</code>, <code>elif</code>, and <code>else</code>.</p>"},
        )
        l5 = Lesson(
            chapter_id=ch2.id, title="Loops", type="text", position=2,
            content={"body": "<p>Use <code>for</code> and <code>while</code> to repeat blocks of code.</p>"},
        )
        l6_quiz_lesson = Lesson(chapter_id=ch2.id, title="Control Flow Quiz", type="quiz", position=3)
        l7_asgn_lesson = Lesson(chapter_id=ch2.id, title="FizzBuzz Assignment", type="assignment", position=4)
        db.add_all([l4, l5, l6_quiz_lesson, l7_asgn_lesson])
        await db.flush()

        ch3 = Chapter(course_id=course.id, title="Functions", position=3)
        db.add(ch3)
        await db.flush()

        l8 = Lesson(
            chapter_id=ch3.id, title="Defining Functions", type="text", position=1,
            content={"body": "<p>Use the <code>def</code> keyword to define reusable blocks of code.</p>"},
        )
        l9 = Lesson(
            chapter_id=ch3.id, title="Arguments and Return Values", type="text", position=2,
            content={"body": "<p>Functions can accept parameters and return values to the caller.</p>"},
        )
        l10_quiz_lesson = Lesson(chapter_id=ch3.id, title="Functions Quiz", type="quiz", position=3)
        l11_asgn_lesson = Lesson(chapter_id=ch3.id, title="Calculator Assignment", type="assignment", position=4)
        db.add_all([l8, l9, l10_quiz_lesson, l11_asgn_lesson])
        await db.flush()

        db.add(LessonResource(
            lesson_id=l9.id,
            name="Functions Cheatsheet.pdf",
            file_url="https://example.com/resources/python-functions-cheatsheet.pdf",
            file_type="application/pdf",
            size_bytes=153_600,
        ))
        print("[+] Created course with 3 chapters and 11 lessons.")

        # ── Quizzes ───────────────────────────────────────────────────────────
        quiz_cf = Quiz(
            lesson_id=l6_quiz_lesson.id,
            title="Control Flow Quiz",
            description="Test your knowledge of if statements and loops.",
            max_attempts=3,
            time_limit_minutes=10,
        )
        db.add(quiz_cf)
        await db.flush()

        q1 = QuizQuestion(
            quiz_id=quiz_cf.id, position=1, kind="single_choice",
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
            quiz_id=quiz_cf.id, position=2, kind="multi_choice",
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
            quiz_id=quiz_cf.id, position=3, kind="single_choice",
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

        quiz_fn = Quiz(
            lesson_id=l10_quiz_lesson.id,
            title="Functions Quiz",
            description="Test your understanding of Python functions.",
            max_attempts=2,
            time_limit_minutes=8,
        )
        db.add(quiz_fn)
        await db.flush()

        qf1 = QuizQuestion(
            quiz_id=quiz_fn.id, position=1, kind="single_choice",
            stem="Which keyword is used to define a function in Python?",
            options=[
                {"id": "a", "text": "func"},
                {"id": "b", "text": "define"},
                {"id": "c", "text": "def"},
                {"id": "d", "text": "function"},
            ],
            correct_answers=["c"], points=1,
        )
        qf2 = QuizQuestion(
            quiz_id=quiz_fn.id, position=2, kind="single_choice",
            stem="What is returned by a function with no `return` statement?",
            options=[
                {"id": "a", "text": "0"},
                {"id": "b", "text": "None"},
                {"id": "c", "text": "False"},
                {"id": "d", "text": "An error is raised"},
            ],
            correct_answers=["b"], points=1,
        )
        qf3 = QuizQuestion(
            quiz_id=quiz_fn.id, position=3, kind="multi_choice",
            stem="Which of the following are valid ways to pass arguments in Python?",
            options=[
                {"id": "a", "text": "Positional arguments"},
                {"id": "b", "text": "Keyword arguments"},
                {"id": "c", "text": "Named pointers"},
                {"id": "d", "text": "Default parameter values"},
            ],
            correct_answers=["a", "b", "d"], points=2,
        )
        db.add_all([qf1, qf2, qf3])
        print("[+] Created 2 quizzes with 6 questions.")

        # ── Assignments ───────────────────────────────────────────────────────
        asgn_fizzbuzz = Assignment(
            lesson_id=l7_asgn_lesson.id,
            title="FizzBuzz Challenge",
            instructions=(
                "Write a Python script that prints numbers 1–100, replacing multiples of 3 "
                "with `Fizz`, multiples of 5 with `Buzz`, and multiples of both with `FizzBuzz`. "
                "Upload your `.py` file."
            ),
            allowed_extensions=["py"],
            max_file_size_bytes=1_048_576,
        )
        asgn_calc = Assignment(
            lesson_id=l11_asgn_lesson.id,
            title="Build a Calculator",
            instructions=(
                "Create a Python module `calculator.py` with functions `add`, `subtract`, "
                "`multiply`, and `divide`. Handle division by zero with a descriptive error message."
            ),
            allowed_extensions=["py"],
            max_file_size_bytes=1_048_576,
        )
        db.add_all([asgn_fizzbuzz, asgn_calc])
        await db.flush()

        # ── Enrollment & Payment ──────────────────────────────────────────────
        enrollment = Enrollment(
            user_id=student.id,
            course_id=course.id,
            status="active",
            payment_id="pi_test_student_py_001",
        )
        db.add(enrollment)

        db.add(Payment(
            user_id=student.id,
            course_id=course.id,
            amount_cents=2699,  # WELCOME10 applied
            currency="usd",
            status="completed",
            provider="stripe",
            provider_payment_id="pi_test_student_py_001",
        ))
        await db.flush()

        # ── Lesson Progress ───────────────────────────────────────────────────
        # Ch1: all done. Ch2: lessons done, quiz done, assignment done.
        # Ch3: first two lessons done, quiz in progress (submitted), assignment pending.
        db.add_all([
            LessonProgress(user_id=student.id, lesson_id=l1.id, status="completed", completed_at=now - timedelta(days=14)),
            LessonProgress(user_id=student.id, lesson_id=l2.id, status="completed", completed_at=now - timedelta(days=13)),
            LessonProgress(user_id=student.id, lesson_id=l3.id, status="completed", completed_at=now - timedelta(days=12)),
            LessonProgress(user_id=student.id, lesson_id=l4.id, status="completed", completed_at=now - timedelta(days=10)),
            LessonProgress(user_id=student.id, lesson_id=l5.id, status="completed", completed_at=now - timedelta(days=9)),
            LessonProgress(user_id=student.id, lesson_id=l6_quiz_lesson.id, status="completed", completed_at=now - timedelta(days=9)),
            LessonProgress(user_id=student.id, lesson_id=l7_asgn_lesson.id, status="completed", completed_at=now - timedelta(days=8)),
            LessonProgress(user_id=student.id, lesson_id=l8.id, status="completed", completed_at=now - timedelta(days=5)),
            LessonProgress(user_id=student.id, lesson_id=l9.id, status="completed", completed_at=now - timedelta(days=4)),
            LessonProgress(user_id=student.id, lesson_id=l10_quiz_lesson.id, status="in_progress"),
        ])
        await db.flush()

        # ── Quiz Submissions & AI Feedback ────────────────────────────────────
        # Control Flow Quiz: failed attempt 1, passed attempt 2
        sub_cf_fail = QuizSubmission(
            user_id=student.id, quiz_id=quiz_cf.id, attempt_number=1,
            answers={str(q1.id): ["a"], str(q2.id): ["a"], str(q3.id): ["a"]},
            score=0, max_score=4, passed=False,
        )
        db.add(sub_cf_fail)
        await db.flush()

        db.add_all([
            QuizFeedback(
                submission_id=sub_cf_fail.id, question_id=q1.id,
                feedback_text="Not quite! The correct keyword is `if`. `when` is not a Python keyword — you may be thinking of other languages. Try reviewing the If Statements lesson.",
            ),
            QuizFeedback(
                submission_id=sub_cf_fail.id, question_id=q2.id,
                feedback_text="Remember, Python has two loop constructs: `for` and `while`. `repeat` and `loop` don't exist in Python.",
            ),
            QuizFeedback(
                submission_id=sub_cf_fail.id, question_id=q3.id,
                feedback_text="`range(3)` starts at 0 by default and goes up to (but not including) 3, so it produces 0, 1, 2.",
            ),
        ])

        sub_cf_pass = QuizSubmission(
            user_id=student.id, quiz_id=quiz_cf.id, attempt_number=2,
            answers={str(q1.id): ["b"], str(q2.id): ["a", "b"], str(q3.id): ["b"]},
            score=4, max_score=4, passed=True,
        )
        db.add(sub_cf_pass)
        await db.flush()

        db.add_all([
            QuizFeedback(
                submission_id=sub_cf_pass.id, question_id=q1.id,
                feedback_text="Correct! `if` is exactly the keyword you need. Great improvement from your last attempt!",
            ),
            QuizFeedback(
                submission_id=sub_cf_pass.id, question_id=q2.id,
                feedback_text="Perfect — both `for` and `while` are Python's loop keywords. Well done!",
            ),
            QuizFeedback(
                submission_id=sub_cf_pass.id, question_id=q3.id,
                feedback_text="Exactly right. `range(n)` always starts at 0 and produces n values. You've got it!",
            ),
        ])

        # Functions Quiz: one passing submission
        sub_fn = QuizSubmission(
            user_id=student.id, quiz_id=quiz_fn.id, attempt_number=1,
            answers={str(qf1.id): ["c"], str(qf2.id): ["b"], str(qf3.id): ["a", "b", "d"]},
            score=4, max_score=4, passed=True,
        )
        db.add(sub_fn)
        await db.flush()

        db.add_all([
            QuizFeedback(
                submission_id=sub_fn.id, question_id=qf1.id,
                feedback_text="Correct! `def` is the keyword used to define functions in Python.",
            ),
            QuizFeedback(
                submission_id=sub_fn.id, question_id=qf2.id,
                feedback_text="Exactly right. A function with no `return` statement implicitly returns `None`.",
            ),
            QuizFeedback(
                submission_id=sub_fn.id, question_id=qf3.id,
                feedback_text="Perfect! Positional, keyword, and default parameter values are all valid — great job getting all three.",
            ),
        ])
        print("[+] Created 3 quiz submissions with AI feedback.")

        # ── Assignment Submissions ─────────────────────────────────────────────
        db.add_all([
            # FizzBuzz — graded
            AssignmentSubmission(
                user_id=student.id,
                assignment_id=asgn_fizzbuzz.id,
                file_key="assignments/student/fizzbuzz.py",
                file_name="fizzbuzz.py",
                file_size=512,
                mime_type="text/x-python",
                scan_status="clean",
                submitted_at=now - timedelta(days=8),
                attempt_number=1,
                grade_score=92.0,
                grade_feedback="Great work! Logic is correct and the output is clean. Consider using f-strings for even more readable output.",
                grade_published_at=now - timedelta(days=6),
                graded_by=admin.id,
            ),
            # Calculator — submitted, not yet graded
            AssignmentSubmission(
                user_id=student.id,
                assignment_id=asgn_calc.id,
                file_key="assignments/student/calculator.py",
                file_name="calculator.py",
                file_size=876,
                mime_type="text/x-python",
                scan_status="clean",
                submitted_at=now - timedelta(days=1),
                attempt_number=1,
            ),
        ])
        print("[+] Created 2 assignment submissions (1 graded, 1 pending).")

        # ── Certificate ───────────────────────────────────────────────────────
        # Student has effectively completed ch1 + ch2; pending request for full cert
        db.add(CertificateRequest(
            user_id=student.id,
            course_id=course.id,
            status="pending",
        ))

        # A certificate issued earlier for a completed run (simulates completion)
        cert = Certificate(
            user_id=student.id,
            course_id=course.id,
            verification_token=secrets.token_urlsafe(32),
            pdf_url="https://example.com/certificates/student-python-for-beginners.pdf",
        )
        db.add(cert)
        await db.flush()
        print("[+] Created 1 certificate and 1 pending request.")

        # ── Announcements ─────────────────────────────────────────────────────
        db.add_all([
            Announcement(
                title="Welcome to xoxoedu!",
                body=(
                    "We're excited to have you here. New courses are added every month — "
                    "check the catalogue and get started today!"
                ),
                scope="platform",
                created_by=admin.id,
                sent_at=now - timedelta(days=30),
            ),
            Announcement(
                title="Python for Beginners — Chapter 3 is live",
                body=(
                    "Chapter 3: Functions is now published! Head back to your course "
                    "dashboard — two new lessons and a graded assignment are waiting."
                ),
                scope="course",
                course_id=course.id,
                created_by=admin.id,
                sent_at=now - timedelta(days=5),
            ),
            # Draft announcement (not yet sent)
            Announcement(
                title="Spring sale — 20% off all courses",
                body="Use code SPRING20 at checkout this week only.",
                scope="platform",
                created_by=admin.id,
                sent_at=None,
            ),
        ])
        print("[+] Created 3 announcements (2 sent, 1 draft).")

        # ── Notes & Bookmarks ────────────────────────────────────────────────
        db.add_all([
            UserNote(user_id=student.id, lesson_id=l2.id, content="Add Python to PATH on Windows — don't forget this step!"),
            UserNote(user_id=student.id, lesson_id=l4.id, content="`elif` is Python's version of else-if. Cleaner than nested ifs."),
            UserNote(user_id=student.id, lesson_id=l9.id, content="Default mutable args are a trap — use None as default and initialise inside the function."),
        ])
        db.add_all([
            UserBookmark(user_id=student.id, lesson_id=l5.id),
            UserBookmark(user_id=student.id, lesson_id=l9.id),
        ])
        print("[+] Created 3 notes and 2 bookmarks.")

        # ── AI Usage Log ──────────────────────────────────────────────────────
        db.add_all([
            AIUsageLog(
                user_id=student.id, course_id=course.id,
                feature="quiz_feedback", tokens_in=420, tokens_out=310,
                model="gemini/gemini-2.0-flash",
            ),
            AIUsageLog(
                user_id=student.id, course_id=course.id,
                feature="quiz_feedback", tokens_in=380, tokens_out=290,
                model="gemini/gemini-2.0-flash",
            ),
            AIUsageLog(
                user_id=student.id, course_id=course.id,
                feature="quiz_feedback", tokens_in=400, tokens_out=320,
                model="gemini/gemini-2.0-flash",
            ),
        ])

        await db.commit()
        print("[+] Created AI usage budget and 3 usage log entries.")

        print()
        print("Seed complete.")
        print()
        print("  Credentials")
        print("  ─────────────────────────────────────────────────────────")
        print("  admin@xoxoedu.com   / admin123     role: admin")
        print("  student@xoxoedu.com / password123  role: student (active, in progress)")

    await engine.dispose()


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    asyncio.run(main(reset=reset))
