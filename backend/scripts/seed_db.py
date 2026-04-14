#!/usr/bin/env python3
"""
Seed the database with realistic dummy data for manual API testing.

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
    from app.db.models.announcement import Announcement
    from app.db.models.assignment import Assignment, AssignmentSubmission
    from app.db.models.certificate import Certificate, CertificateRequest
    from app.db.models.coupon import Coupon
    from app.db.models.course import Category, Chapter, Course, Lesson, LessonResource
    from app.db.models.enrollment import Enrollment, LessonProgress, UserBookmark, UserNote
    from app.db.models.payment import Payment
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

        now = datetime.now(timezone.utc)

        # ── Categories ───────────────────────────────────────────────────────
        programming = Category(name="Programming", slug="programming")
        design = Category(name="Design", slug="design")
        business = Category(name="Business", slug="business")
        db.add_all([programming, design, business])
        await db.flush()

        python_cat = Category(name="Python", slug="python", parent_id=programming.id)
        js_cat = Category(name="JavaScript", slug="javascript", parent_id=programming.id)
        ts_cat = Category(name="TypeScript", slug="typescript", parent_id=programming.id)
        ds_cat = Category(name="Data Science", slug="data-science", parent_id=programming.id)
        uiux_cat = Category(name="UI/UX", slug="ui-ux", parent_id=design.id)
        graphic_cat = Category(name="Graphic Design", slug="graphic-design", parent_id=design.id)
        marketing_cat = Category(name="Marketing", slug="marketing", parent_id=business.id)
        db.add_all([python_cat, js_cat, ts_cat, ds_cat, uiux_cat, graphic_cat, marketing_cat])
        await db.flush()
        print("[+] Created 10 categories (3 root, 7 sub).")

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
        dave = User(
            email="dave@example.com",
            password_hash=hash_password("password123"),
            role="student",
            email_verified=True,
        )
        emma = User(
            email="emma@example.com",
            password_hash=hash_password("password123"),
            role="student",
            email_verified=True,
        )
        frank = User(
            email="frank@example.com",
            password_hash=hash_password("password123"),
            role="student",
            email_verified=True,
        )
        grace = User(
            email="grace@example.com",
            password_hash=hash_password("password123"),
            role="student",
            email_verified=True,
        )
        hannah = User(
            email="hannah@example.com",
            password_hash=hash_password("password123"),
            role="student",
            email_verified=True,
        )
        ivan = User(
            email="ivan@example.com",
            password_hash=hash_password("password123"),
            role="student",
            email_verified=False,
        )
        db.add_all([admin, alice, bob, carol, dave, emma, frank, grace, hannah, ivan])
        await db.flush()

        db.add_all([
            UserProfile(user_id=admin.id, display_name="Admin", headline="Platform administrator"),
            UserProfile(
                user_id=alice.id,
                display_name="Alice Chen",
                bio="Aspiring developer learning Python and JavaScript.",
                headline="Junior Developer in Training",
                skills=["Python", "JavaScript"],
                social_links={"github": "https://github.com/alicechen"},
            ),
            UserProfile(
                user_id=bob.id,
                display_name="Bob Martinez",
                bio="Career changer with a background in finance. Now building data tools.",
                headline="Finance → Data Science Pivot",
                skills=["Python", "JavaScript", "SQL"],
                social_links={"linkedin": "https://linkedin.com/in/bobmartinez"},
            ),
            UserProfile(user_id=carol.id, display_name="Carol White"),
            UserProfile(
                user_id=dave.id,
                display_name="Dave Kim",
                bio="Software engineer brushing up on TypeScript and React.",
                headline="Software Engineer",
                skills=["JavaScript", "TypeScript", "React"],
            ),
            UserProfile(
                user_id=emma.id,
                display_name="Emma Patel",
                bio="UX designer branching into frontend development.",
                headline="UX Designer & Aspiring Frontend Dev",
                skills=["Figma", "CSS", "JavaScript"],
            ),
            UserProfile(
                user_id=frank.id,
                display_name="Frank Nguyen",
                bio="Complete beginner starting his coding journey.",
                headline="Future Developer",
                skills=[],
            ),
            UserProfile(
                user_id=grace.id,
                display_name="Grace Okonkwo",
                bio="Data analyst expanding into machine learning.",
                headline="Data Analyst & ML Enthusiast",
                skills=["Python", "Pandas", "SQL", "Tableau"],
                social_links={"github": "https://github.com/graceokonkwo"},
            ),
            UserProfile(user_id=hannah.id, display_name="Hannah Liu", headline="Product Manager"),
            UserProfile(user_id=ivan.id, display_name="Ivan Petrov"),
        ])
        await db.flush()
        print("[+] Created 10 users (1 admin, 9 students).")

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

        py_ch3 = Chapter(course_id=py_course.id, title="Functions & Modules", position=3)
        db.add(py_ch3)
        await db.flush()

        l8 = Lesson(
            chapter_id=py_ch3.id, title="Defining Functions", type="video",
            position=1, video_asset_id="mux-asset-005",
            content={"duration_seconds": 720},
        )
        l9 = Lesson(
            chapter_id=py_ch3.id, title="Arguments and Return Values", type="text",
            position=2,
            content={"html": "<p>Functions can accept parameters and return values to the caller.</p>"},
        )
        l10 = Lesson(
            chapter_id=py_ch3.id, title="Importing Modules", type="text",
            position=3,
            content={"html": "<p>Use <code>import</code> to bring in Python's standard library modules.</p>"},
        )
        l11 = Lesson(chapter_id=py_ch3.id, title="Functions Quiz", type="quiz", position=4)
        l12 = Lesson(chapter_id=py_ch3.id, title="Calculator Assignment", type="assignment", position=5)
        db.add_all([l8, l9, l10, l11, l12])
        await db.flush()

        db.add_all([
            LessonResource(
                lesson_id=l2.id,
                name="Python Installation Guide.pdf",
                file_url="https://example.com/resources/python-install-guide.pdf",
                file_type="application/pdf",
                size_bytes=204_800,
            ),
            LessonResource(
                lesson_id=l8.id,
                name="Functions Cheatsheet.pdf",
                file_url="https://example.com/resources/python-functions-cheatsheet.pdf",
                file_type="application/pdf",
                size_bytes=153_600,
            ),
            LessonResource(
                lesson_id=l10.id,
                name="Standard Library Quick Reference.pdf",
                file_url="https://example.com/resources/stdlib-quickref.pdf",
                file_type="application/pdf",
                size_bytes=307_200,
            ),
        ])

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
        q4 = QuizQuestion(
            quiz_id=quiz1.id, position=4, kind="single_choice",
            stem="Which statement immediately terminates the current loop iteration?",
            options=[
                {"id": "a", "text": "break"},
                {"id": "b", "text": "exit"},
                {"id": "c", "text": "continue"},
                {"id": "d", "text": "pass"},
            ],
            correct_answers=["c"], points=1,
        )
        db.add_all([q1, q2, q3, q4])

        quiz_functions = Quiz(
            lesson_id=l11.id,
            title="Functions Quiz",
            description="Test your understanding of Python functions.",
            max_attempts=2,
            time_limit_minutes=8,
        )
        db.add(quiz_functions)
        await db.flush()

        qf1 = QuizQuestion(
            quiz_id=quiz_functions.id, position=1, kind="single_choice",
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
            quiz_id=quiz_functions.id, position=2, kind="single_choice",
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
            quiz_id=quiz_functions.id, position=3, kind="multi_choice",
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
        asgn_calc = Assignment(
            lesson_id=l12.id,
            title="Build a Calculator",
            instructions=(
                "Create a Python module `calculator.py` with functions `add`, `subtract`, "
                "`multiply`, and `divide`. Each function should accept two numbers and return "
                "the result. Handle division by zero with a descriptive error message. "
                "Include a `main()` function demonstrating all four operations."
            ),
            allowed_extensions=["py"],
            max_file_size_bytes=1_048_576,
        )
        db.add_all([asgn1, asgn_calc])
        await db.flush()
        print("[+] Created course 'Python for Beginners' (3 chapters, 12 lessons).")

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
        jsl6 = Lesson(chapter_id=js_ch2.id, title="Closures Assignment", type="assignment", position=3)
        db.add_all([jsl4, jsl5, jsl6])
        await db.flush()

        js_ch3 = Chapter(course_id=js_course.id, title="Async JavaScript", position=3)
        db.add(js_ch3)
        await db.flush()

        jsl7 = Lesson(
            chapter_id=js_ch3.id, title="Promises", type="video",
            position=1, video_asset_id="mux-asset-006",
            content={"duration_seconds": 660},
        )
        jsl8 = Lesson(
            chapter_id=js_ch3.id, title="Async/Await", type="text",
            position=2,
            content={"html": "<p>The <code>async/await</code> syntax makes asynchronous code read like synchronous code.</p>"},
        )
        jsl9 = Lesson(chapter_id=js_ch3.id, title="Async Quiz", type="quiz", position=3)
        db.add_all([jsl7, jsl8, jsl9])
        await db.flush()

        db.add_all([
            LessonResource(
                lesson_id=jsl2.id,
                name="JS Types Reference.pdf",
                file_url="https://example.com/resources/js-types-reference.pdf",
                file_type="application/pdf",
                size_bytes=122_880,
            ),
            LessonResource(
                lesson_id=jsl7.id,
                name="Promise Patterns Cheatsheet.pdf",
                file_url="https://example.com/resources/promise-patterns.pdf",
                file_type="application/pdf",
                size_bytes=184_320,
            ),
        ])

        js_quiz = Quiz(
            lesson_id=jsl3.id, title="Variables Quiz",
            max_attempts=2, time_limit_minutes=5,
        )
        db.add(js_quiz)
        await db.flush()

        jsq1 = QuizQuestion(
            quiz_id=js_quiz.id, position=1, kind="single_choice",
            stem="Which keyword declares a block-scoped variable in modern JavaScript?",
            options=[
                {"id": "a", "text": "var"},
                {"id": "b", "text": "let"},
                {"id": "c", "text": "def"},
                {"id": "d", "text": "dim"},
            ],
            correct_answers=["b"], points=1,
        )
        jsq2 = QuizQuestion(
            quiz_id=js_quiz.id, position=2, kind="multi_choice",
            stem="Which of the following are JavaScript primitive types?",
            options=[
                {"id": "a", "text": "string"},
                {"id": "b", "text": "number"},
                {"id": "c", "text": "list"},
                {"id": "d", "text": "boolean"},
            ],
            correct_answers=["a", "b", "d"], points=2,
        )
        jsq3 = QuizQuestion(
            quiz_id=js_quiz.id, position=3, kind="single_choice",
            stem="What is the value of `typeof null` in JavaScript?",
            options=[
                {"id": "a", "text": "null"},
                {"id": "b", "text": "undefined"},
                {"id": "c", "text": "object"},
                {"id": "d", "text": "string"},
            ],
            correct_answers=["c"], points=1,
        )
        db.add_all([jsq1, jsq2, jsq3])

        js_async_quiz = Quiz(
            lesson_id=jsl9.id, title="Async JavaScript Quiz",
            max_attempts=3, time_limit_minutes=8,
        )
        db.add(js_async_quiz)
        await db.flush()

        db.add_all([
            QuizQuestion(
                quiz_id=js_async_quiz.id, position=1, kind="single_choice",
                stem="What does a Promise represent?",
                options=[
                    {"id": "a", "text": "A synchronous computation result"},
                    {"id": "b", "text": "An eventual completion or failure of an async operation"},
                    {"id": "c", "text": "A type of loop"},
                    {"id": "d", "text": "A JavaScript class"},
                ],
                correct_answers=["b"], points=1,
            ),
            QuizQuestion(
                quiz_id=js_async_quiz.id, position=2, kind="single_choice",
                stem="Which keyword pauses execution inside an async function?",
                options=[
                    {"id": "a", "text": "pause"},
                    {"id": "b", "text": "delay"},
                    {"id": "c", "text": "await"},
                    {"id": "d", "text": "hold"},
                ],
                correct_answers=["c"], points=1,
            ),
            QuizQuestion(
                quiz_id=js_async_quiz.id, position=3, kind="multi_choice",
                stem="Which Promise states are possible?",
                options=[
                    {"id": "a", "text": "pending"},
                    {"id": "b", "text": "fulfilled"},
                    {"id": "c", "text": "running"},
                    {"id": "d", "text": "rejected"},
                ],
                correct_answers=["a", "b", "d"], points=2,
            ),
        ])

        asgn_closures = Assignment(
            lesson_id=jsl6.id,
            title="Closures: Counter Factory",
            instructions=(
                "Implement a `makeCounter(start = 0)` function that returns an object with "
                "`increment()`, `decrement()`, and `value()` methods. Each call to `makeCounter` "
                "must maintain independent state. Submit your solution as a single `.js` file."
            ),
            allowed_extensions=["js"],
            max_file_size_bytes=1_048_576,
        )
        db.add(asgn_closures)
        await db.flush()
        print("[+] Created course 'JavaScript Fundamentals' (3 chapters, 9 lessons).")

        # ── Course 3: Python Data Science (published, paid) ───────────────────
        ds_course = Course(
            slug="python-data-science",
            title="Python for Data Science",
            description=(
                "Dive into data analysis with Python. Master NumPy, Pandas, Matplotlib, "
                "and an introduction to scikit-learn for machine learning."
            ),
            category_id=ds_cat.id,
            level="intermediate",
            price_cents=4999,
            status="published",
            display_instructor_name="Admin",
            display_instructor_bio="Data scientist with 8 years of industry experience at top tech companies.",
            created_by=admin.id,
        )
        db.add(ds_course)
        await db.flush()

        ds_ch1 = Chapter(course_id=ds_course.id, title="NumPy Essentials", position=1)
        db.add(ds_ch1)
        await db.flush()

        dsl1 = Lesson(
            chapter_id=ds_ch1.id, title="Introduction to NumPy", type="text",
            position=1, is_free_preview=True,
            content={"html": "<p>NumPy provides fast, vectorized array operations that underpin the entire PyData ecosystem.</p>"},
        )
        dsl2 = Lesson(
            chapter_id=ds_ch1.id, title="Arrays and Indexing", type="video",
            position=2, video_asset_id="mux-asset-007",
            content={"duration_seconds": 840},
        )
        dsl3 = Lesson(
            chapter_id=ds_ch1.id, title="Broadcasting and Vectorization", type="video",
            position=3, video_asset_id="mux-asset-008",
            content={"duration_seconds": 720},
        )
        dsl4 = Lesson(chapter_id=ds_ch1.id, title="NumPy Quiz", type="quiz", position=4)
        db.add_all([dsl1, dsl2, dsl3, dsl4])
        await db.flush()

        ds_ch2 = Chapter(course_id=ds_course.id, title="Data Wrangling with Pandas", position=2)
        db.add(ds_ch2)
        await db.flush()

        dsl5 = Lesson(
            chapter_id=ds_ch2.id, title="DataFrames and Series", type="video",
            position=1, video_asset_id="mux-asset-009",
            content={"duration_seconds": 900},
        )
        dsl6 = Lesson(
            chapter_id=ds_ch2.id, title="Cleaning and Transforming Data", type="text",
            position=2,
            content={"html": "<p>Handle missing values, rename columns, and reshape DataFrames with <code>merge</code> and <code>pivot</code>.</p>"},
        )
        dsl7 = Lesson(chapter_id=ds_ch2.id, title="Data Analysis Assignment", type="assignment", position=3)
        db.add_all([dsl5, dsl6, dsl7])
        await db.flush()

        ds_ch3 = Chapter(course_id=ds_course.id, title="Visualisation & ML Intro", position=3)
        db.add(ds_ch3)
        await db.flush()

        dsl8 = Lesson(
            chapter_id=ds_ch3.id, title="Matplotlib and Seaborn", type="video",
            position=1, video_asset_id="mux-asset-010",
            content={"duration_seconds": 780},
        )
        dsl9 = Lesson(
            chapter_id=ds_ch3.id, title="Intro to scikit-learn", type="text",
            position=2,
            content={"html": "<p>Train your first model: a linear regression on the Boston housing dataset.</p>"},
        )
        dsl10 = Lesson(chapter_id=ds_ch3.id, title="Final Quiz", type="quiz", position=3)
        db.add_all([dsl8, dsl9, dsl10])
        await db.flush()

        db.add_all([
            LessonResource(
                lesson_id=dsl2.id,
                name="NumPy Cheatsheet.pdf",
                file_url="https://example.com/resources/numpy-cheatsheet.pdf",
                file_type="application/pdf",
                size_bytes=245_760,
            ),
            LessonResource(
                lesson_id=dsl5.id,
                name="Pandas Reference Card.pdf",
                file_url="https://example.com/resources/pandas-reference.pdf",
                file_type="application/pdf",
                size_bytes=307_200,
            ),
            LessonResource(
                lesson_id=dsl7.id,
                name="Sample Dataset — titanic.csv",
                file_url="https://example.com/resources/titanic.csv",
                file_type="text/csv",
                size_bytes=61_440,
            ),
        ])

        ds_quiz = Quiz(
            lesson_id=dsl4.id, title="NumPy Quiz",
            max_attempts=2, time_limit_minutes=10,
        )
        db.add(ds_quiz)
        await db.flush()

        db.add_all([
            QuizQuestion(
                quiz_id=ds_quiz.id, position=1, kind="single_choice",
                stem="What is the NumPy function to create an array filled with zeros?",
                options=[
                    {"id": "a", "text": "np.empty()"},
                    {"id": "b", "text": "np.zeros()"},
                    {"id": "c", "text": "np.null()"},
                    {"id": "d", "text": "np.blank()"},
                ],
                correct_answers=["b"], points=1,
            ),
            QuizQuestion(
                quiz_id=ds_quiz.id, position=2, kind="single_choice",
                stem="Which attribute gives you the shape of a NumPy array?",
                options=[
                    {"id": "a", "text": ".size"},
                    {"id": "b", "text": ".dimensions"},
                    {"id": "c", "text": ".shape"},
                    {"id": "d", "text": ".ndim"},
                ],
                correct_answers=["c"], points=1,
            ),
            QuizQuestion(
                quiz_id=ds_quiz.id, position=3, kind="multi_choice",
                stem="Which of the following are valid NumPy array creation functions?",
                options=[
                    {"id": "a", "text": "np.arange()"},
                    {"id": "b", "text": "np.linspace()"},
                    {"id": "c", "text": "np.spread()"},
                    {"id": "d", "text": "np.ones()"},
                ],
                correct_answers=["a", "b", "d"], points=2,
            ),
        ])

        ds_final_quiz = Quiz(
            lesson_id=dsl10.id, title="Data Science Final Quiz",
            max_attempts=2, time_limit_minutes=15,
        )
        db.add(ds_final_quiz)
        await db.flush()

        db.add_all([
            QuizQuestion(
                quiz_id=ds_final_quiz.id, position=1, kind="single_choice",
                stem="Which Pandas method removes rows with missing values?",
                options=[
                    {"id": "a", "text": ".remove_na()"},
                    {"id": "b", "text": ".dropna()"},
                    {"id": "c", "text": ".fillna()"},
                    {"id": "d", "text": ".clean()"},
                ],
                correct_answers=["b"], points=1,
            ),
            QuizQuestion(
                quiz_id=ds_final_quiz.id, position=2, kind="single_choice",
                stem="In scikit-learn, which method trains a model on data?",
                options=[
                    {"id": "a", "text": ".train()"},
                    {"id": "b", "text": ".learn()"},
                    {"id": "c", "text": ".fit()"},
                    {"id": "d", "text": ".run()"},
                ],
                correct_answers=["c"], points=1,
            ),
        ])

        asgn_ds = Assignment(
            lesson_id=dsl7.id,
            title="Titanic Survival Analysis",
            instructions=(
                "Using the provided `titanic.csv` dataset, write a Jupyter notebook or Python "
                "script that: (1) loads the data with Pandas, (2) shows descriptive statistics, "
                "(3) handles missing values, (4) creates at least 3 visualisations with Matplotlib "
                "or Seaborn, and (5) calculates survival rates by gender and passenger class. "
                "Submit as a `.ipynb` or `.py` file."
            ),
            allowed_extensions=["ipynb", "py"],
            max_file_size_bytes=5_242_880,
        )
        db.add(asgn_ds)
        await db.flush()
        print("[+] Created course 'Python for Data Science' (3 chapters, 10 lessons).")

        # ── Course 4: TypeScript Deep Dive (published, paid) ─────────────────
        ts_course = Course(
            slug="typescript-deep-dive",
            title="TypeScript Deep Dive",
            description=(
                "Go beyond JavaScript with TypeScript's type system. "
                "Covers generics, decorators, advanced types, and integrating TS into real projects."
            ),
            category_id=ts_cat.id,
            level="advanced",
            price_cents=3499,
            status="published",
            display_instructor_name="Admin",
            display_instructor_bio="TypeScript contributor and lead engineer at a Fortune 500 company.",
            created_by=admin.id,
        )
        db.add(ts_course)
        await db.flush()

        ts_ch1 = Chapter(course_id=ts_course.id, title="The Type System", position=1)
        db.add(ts_ch1)
        await db.flush()

        tsl1 = Lesson(
            chapter_id=ts_ch1.id, title="Why TypeScript?", type="text",
            position=1, is_free_preview=True,
            content={"html": "<p>TypeScript adds static types to JavaScript, catching errors at compile time instead of runtime.</p>"},
        )
        tsl2 = Lesson(
            chapter_id=ts_ch1.id, title="Primitive and Object Types", type="video",
            position=2, video_asset_id="mux-asset-011",
            content={"duration_seconds": 660},
        )
        tsl3 = Lesson(
            chapter_id=ts_ch1.id, title="Interfaces vs Type Aliases", type="video",
            position=3, video_asset_id="mux-asset-012",
            content={"duration_seconds": 540},
        )
        tsl4 = Lesson(chapter_id=ts_ch1.id, title="Types Quiz", type="quiz", position=4)
        db.add_all([tsl1, tsl2, tsl3, tsl4])
        await db.flush()

        ts_ch2 = Chapter(course_id=ts_course.id, title="Advanced Features", position=2)
        db.add(ts_ch2)
        await db.flush()

        tsl5 = Lesson(
            chapter_id=ts_ch2.id, title="Generics", type="video",
            position=1, video_asset_id="mux-asset-013",
            content={"duration_seconds": 780},
        )
        tsl6 = Lesson(
            chapter_id=ts_ch2.id, title="Decorators", type="text",
            position=2,
            content={"html": "<p>Decorators are a stage-3 proposal that TypeScript has supported for years via <code>experimentalDecorators</code>.</p>"},
        )
        tsl7 = Lesson(chapter_id=ts_ch2.id, title="Generics Assignment", type="assignment", position=3)
        db.add_all([tsl5, tsl6, tsl7])
        await db.flush()

        ts_quiz = Quiz(
            lesson_id=tsl4.id, title="TypeScript Types Quiz",
            max_attempts=2, time_limit_minutes=8,
        )
        db.add(ts_quiz)
        await db.flush()

        db.add_all([
            QuizQuestion(
                quiz_id=ts_quiz.id, position=1, kind="single_choice",
                stem="Which TypeScript type accepts any value without type checking?",
                options=[
                    {"id": "a", "text": "unknown"},
                    {"id": "b", "text": "any"},
                    {"id": "c", "text": "object"},
                    {"id": "d", "text": "void"},
                ],
                correct_answers=["b"], points=1,
            ),
            QuizQuestion(
                quiz_id=ts_quiz.id, position=2, kind="multi_choice",
                stem="Which are valid TypeScript utility types?",
                options=[
                    {"id": "a", "text": "Partial<T>"},
                    {"id": "b", "text": "Readonly<T>"},
                    {"id": "c", "text": "Immutable<T>"},
                    {"id": "d", "text": "Required<T>"},
                ],
                correct_answers=["a", "b", "d"], points=2,
            ),
        ])

        asgn_ts = Assignment(
            lesson_id=tsl7.id,
            title="Generic Data Structures",
            instructions=(
                "Implement a generic `Stack<T>` class in TypeScript with `push(item: T)`, "
                "`pop(): T | undefined`, `peek(): T | undefined`, `isEmpty(): boolean`, "
                "and `size(): number` methods. Add a generic `Queue<T>` class as well. "
                "Include a demo file showing both structures in use. Submit as a `.ts` file."
            ),
            allowed_extensions=["ts"],
            max_file_size_bytes=1_048_576,
        )
        db.add(asgn_ts)
        await db.flush()
        print("[+] Created course 'TypeScript Deep Dive' (2 chapters, 7 lessons).")

        # ── Course 5: UI/UX Design Principles (draft) ─────────────────────────
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
        # Alice: Python (active), JS (active, paid)
        enroll_alice_py = Enrollment(user_id=alice.id, course_id=py_course.id, status="active")
        enroll_alice_js = Enrollment(
            user_id=alice.id, course_id=js_course.id, status="active",
            payment_id="pi_test_alice_js_001",
        )
        # Bob: Python (completed), DS (active, paid)
        enroll_bob_py = Enrollment(
            user_id=bob.id, course_id=py_course.id,
            status="completed", completed_at=now - timedelta(days=14),
        )
        enroll_bob_ds = Enrollment(
            user_id=bob.id, course_id=ds_course.id, status="active",
            payment_id="pi_test_bob_ds_001",
        )
        # Dave: JS (active, paid), TS (active, paid)
        enroll_dave_js = Enrollment(
            user_id=dave.id, course_id=js_course.id, status="active",
            payment_id="pi_test_dave_js_001",
        )
        enroll_dave_ts = Enrollment(
            user_id=dave.id, course_id=ts_course.id, status="active",
            payment_id="pi_test_dave_ts_001",
        )
        # Emma: Python (active), JS (active, paid)
        enroll_emma_py = Enrollment(user_id=emma.id, course_id=py_course.id, status="active")
        enroll_emma_js = Enrollment(
            user_id=emma.id, course_id=js_course.id, status="active",
            payment_id="pi_test_emma_js_001",
        )
        # Frank: Python (active, just started)
        enroll_frank_py = Enrollment(user_id=frank.id, course_id=py_course.id, status="active")
        # Grace: DS (completed, paid), Python (completed)
        enroll_grace_py = Enrollment(
            user_id=grace.id, course_id=py_course.id,
            status="completed", completed_at=now - timedelta(days=60),
        )
        enroll_grace_ds = Enrollment(
            user_id=grace.id, course_id=ds_course.id,
            status="completed", completed_at=now - timedelta(days=7),
            payment_id="pi_test_grace_ds_001",
        )
        # Hannah: Python (unenrolled)
        enroll_hannah_py = Enrollment(user_id=hannah.id, course_id=py_course.id, status="unenrolled")

        db.add_all([
            enroll_alice_py, enroll_alice_js,
            enroll_bob_py, enroll_bob_ds,
            enroll_dave_js, enroll_dave_ts,
            enroll_emma_py, enroll_emma_js,
            enroll_frank_py,
            enroll_grace_py, enroll_grace_ds,
            enroll_hannah_py,
        ])
        await db.flush()
        print("[+] Created 12 enrollments.")

        # ── Payments ─────────────────────────────────────────────────────────
        db.add_all([
            Payment(
                user_id=alice.id, course_id=js_course.id,
                amount_cents=2999, currency="usd", status="completed",
                provider="stripe", provider_payment_id="pi_test_alice_js_001",
            ),
            Payment(
                user_id=bob.id, course_id=ds_course.id,
                amount_cents=4999, currency="usd", status="completed",
                provider="stripe", provider_payment_id="pi_test_bob_ds_001",
            ),
            Payment(
                user_id=dave.id, course_id=js_course.id,
                amount_cents=1499, currency="usd", status="completed",
                provider="stripe", provider_payment_id="pi_test_dave_js_001",
            ),
            Payment(
                user_id=dave.id, course_id=ts_course.id,
                amount_cents=3499, currency="usd", status="completed",
                provider="stripe", provider_payment_id="pi_test_dave_ts_001",
            ),
            Payment(
                user_id=emma.id, course_id=js_course.id,
                amount_cents=2999, currency="usd", status="completed",
                provider="stripe", provider_payment_id="pi_test_emma_js_001",
            ),
            Payment(
                user_id=grace.id, course_id=ds_course.id,
                amount_cents=4999, currency="usd", status="completed",
                provider="stripe", provider_payment_id="pi_test_grace_ds_001",
            ),
            # A failed payment attempt from Ivan
            Payment(
                user_id=ivan.id, course_id=js_course.id,
                amount_cents=2999, currency="usd", status="failed",
                provider="stripe", provider_payment_id="pi_test_ivan_js_fail",
            ),
            # A refunded payment
            Payment(
                user_id=hannah.id, course_id=py_course.id,
                amount_cents=0, currency="usd", status="refunded",
                provider="stripe", provider_payment_id="pi_test_hannah_py_refund",
            ),
        ])
        await db.flush()
        print("[+] Created 8 payment records.")

        # ── Coupons ───────────────────────────────────────────────────────────
        db.add_all([
            Coupon(
                code="WELCOME10",
                discount_type="percentage",
                discount_value=10,
                max_uses=None,
                uses_count=3,
                applies_to=None,
                expires_at=None,
            ),
            Coupon(
                code="SUMMER25",
                discount_type="percentage",
                discount_value=25,
                max_uses=100,
                uses_count=42,
                applies_to=None,
                expires_at=datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc),
            ),
            Coupon(
                code="PYOFF500",
                discount_type="fixed",
                discount_value=500,
                max_uses=50,
                uses_count=12,
                applies_to=[str(py_course.id)],
                expires_at=None,
            ),
            Coupon(
                code="HALFOFF",
                discount_type="percentage",
                discount_value=50,
                max_uses=20,
                uses_count=20,
                applies_to=None,
                expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            Coupon(
                code="DSLAUNCH",
                discount_type="fixed",
                discount_value=1000,
                max_uses=200,
                uses_count=87,
                applies_to=[str(ds_course.id)],
                expires_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
            ),
        ])
        await db.flush()
        print("[+] Created 5 coupons.")

        # ── Lesson Progress ──────────────────────────────────────────────────
        # Alice: Python ch1+ch2 done, ch3 in progress; JS preview only
        alice_progress = [
            LessonProgress(user_id=alice.id, lesson_id=l1.id, status="completed", completed_at=now - timedelta(days=20)),
            LessonProgress(user_id=alice.id, lesson_id=l2.id, status="completed", completed_at=now - timedelta(days=20), watch_seconds=420),
            LessonProgress(user_id=alice.id, lesson_id=l3.id, status="completed", completed_at=now - timedelta(days=19)),
            LessonProgress(user_id=alice.id, lesson_id=l4.id, status="completed", completed_at=now - timedelta(days=18)),
            LessonProgress(user_id=alice.id, lesson_id=l5.id, status="completed", completed_at=now - timedelta(days=17), watch_seconds=600),
            LessonProgress(user_id=alice.id, lesson_id=l6.id, status="completed", completed_at=now - timedelta(days=17)),
            LessonProgress(user_id=alice.id, lesson_id=l7.id, status="completed", completed_at=now - timedelta(days=16)),
            LessonProgress(user_id=alice.id, lesson_id=l8.id, status="in_progress", watch_seconds=210),
            LessonProgress(user_id=alice.id, lesson_id=jsl1.id, status="completed", completed_at=now - timedelta(days=10)),
            LessonProgress(user_id=alice.id, lesson_id=jsl2.id, status="in_progress", watch_seconds=180),
        ]
        # Bob: Python all completed; DS ch1 done, ch2 in progress
        bob_progress = [
            LessonProgress(user_id=bob.id, lesson_id=l1.id, status="completed", completed_at=now - timedelta(days=50)),
            LessonProgress(user_id=bob.id, lesson_id=l2.id, status="completed", completed_at=now - timedelta(days=50), watch_seconds=420),
            LessonProgress(user_id=bob.id, lesson_id=l3.id, status="completed", completed_at=now - timedelta(days=49)),
            LessonProgress(user_id=bob.id, lesson_id=l4.id, status="completed", completed_at=now - timedelta(days=48)),
            LessonProgress(user_id=bob.id, lesson_id=l5.id, status="completed", completed_at=now - timedelta(days=47), watch_seconds=600),
            LessonProgress(user_id=bob.id, lesson_id=l6.id, status="completed", completed_at=now - timedelta(days=47)),
            LessonProgress(user_id=bob.id, lesson_id=l7.id, status="completed", completed_at=now - timedelta(days=46)),
            LessonProgress(user_id=bob.id, lesson_id=l8.id, status="completed", completed_at=now - timedelta(days=45), watch_seconds=720),
            LessonProgress(user_id=bob.id, lesson_id=l9.id, status="completed", completed_at=now - timedelta(days=44)),
            LessonProgress(user_id=bob.id, lesson_id=l10.id, status="completed", completed_at=now - timedelta(days=43)),
            LessonProgress(user_id=bob.id, lesson_id=l11.id, status="completed", completed_at=now - timedelta(days=43)),
            LessonProgress(user_id=bob.id, lesson_id=l12.id, status="completed", completed_at=now - timedelta(days=42)),
            # DS ch1
            LessonProgress(user_id=bob.id, lesson_id=dsl1.id, status="completed", completed_at=now - timedelta(days=10)),
            LessonProgress(user_id=bob.id, lesson_id=dsl2.id, status="completed", completed_at=now - timedelta(days=9), watch_seconds=840),
            LessonProgress(user_id=bob.id, lesson_id=dsl3.id, status="completed", completed_at=now - timedelta(days=8), watch_seconds=720),
            LessonProgress(user_id=bob.id, lesson_id=dsl4.id, status="completed", completed_at=now - timedelta(days=8)),
            LessonProgress(user_id=bob.id, lesson_id=dsl5.id, status="in_progress", watch_seconds=300),
        ]
        # Dave: JS all done; TS ch1 in progress
        dave_progress = [
            LessonProgress(user_id=dave.id, lesson_id=jsl1.id, status="completed", completed_at=now - timedelta(days=30)),
            LessonProgress(user_id=dave.id, lesson_id=jsl2.id, status="completed", completed_at=now - timedelta(days=29), watch_seconds=540),
            LessonProgress(user_id=dave.id, lesson_id=jsl3.id, status="completed", completed_at=now - timedelta(days=29)),
            LessonProgress(user_id=dave.id, lesson_id=jsl4.id, status="completed", completed_at=now - timedelta(days=28)),
            LessonProgress(user_id=dave.id, lesson_id=jsl5.id, status="completed", completed_at=now - timedelta(days=27), watch_seconds=480),
            LessonProgress(user_id=dave.id, lesson_id=jsl6.id, status="completed", completed_at=now - timedelta(days=27)),
            LessonProgress(user_id=dave.id, lesson_id=jsl7.id, status="completed", completed_at=now - timedelta(days=26), watch_seconds=660),
            LessonProgress(user_id=dave.id, lesson_id=jsl8.id, status="completed", completed_at=now - timedelta(days=25)),
            LessonProgress(user_id=dave.id, lesson_id=jsl9.id, status="completed", completed_at=now - timedelta(days=25)),
            LessonProgress(user_id=dave.id, lesson_id=tsl1.id, status="completed", completed_at=now - timedelta(days=5)),
            LessonProgress(user_id=dave.id, lesson_id=tsl2.id, status="in_progress", watch_seconds=350),
        ]
        # Emma: Python ch1 done; JS just started
        emma_progress = [
            LessonProgress(user_id=emma.id, lesson_id=l1.id, status="completed", completed_at=now - timedelta(days=7)),
            LessonProgress(user_id=emma.id, lesson_id=l2.id, status="completed", completed_at=now - timedelta(days=7), watch_seconds=420),
            LessonProgress(user_id=emma.id, lesson_id=l3.id, status="completed", completed_at=now - timedelta(days=6)),
            LessonProgress(user_id=emma.id, lesson_id=jsl1.id, status="completed", completed_at=now - timedelta(days=2)),
        ]
        # Frank: only watched the first lesson
        frank_progress = [
            LessonProgress(user_id=frank.id, lesson_id=l1.id, status="completed", completed_at=now - timedelta(days=1)),
            LessonProgress(user_id=frank.id, lesson_id=l2.id, status="in_progress", watch_seconds=60),
        ]
        # Grace: Python all done; DS all done
        grace_py_progress = [
            LessonProgress(user_id=grace.id, lesson_id=lid, status="completed", completed_at=now - timedelta(days=70))
            for lid in [l1.id, l3.id, l4.id, l9.id, l10.id]
        ] + [
            LessonProgress(user_id=grace.id, lesson_id=l2.id, status="completed", completed_at=now - timedelta(days=70), watch_seconds=420),
            LessonProgress(user_id=grace.id, lesson_id=l5.id, status="completed", completed_at=now - timedelta(days=68), watch_seconds=600),
            LessonProgress(user_id=grace.id, lesson_id=l6.id, status="completed", completed_at=now - timedelta(days=67)),
            LessonProgress(user_id=grace.id, lesson_id=l7.id, status="completed", completed_at=now - timedelta(days=66)),
            LessonProgress(user_id=grace.id, lesson_id=l8.id, status="completed", completed_at=now - timedelta(days=65), watch_seconds=720),
            LessonProgress(user_id=grace.id, lesson_id=l11.id, status="completed", completed_at=now - timedelta(days=63)),
            LessonProgress(user_id=grace.id, lesson_id=l12.id, status="completed", completed_at=now - timedelta(days=62)),
        ]
        grace_ds_progress = [
            LessonProgress(user_id=grace.id, lesson_id=dsl1.id, status="completed", completed_at=now - timedelta(days=30)),
            LessonProgress(user_id=grace.id, lesson_id=dsl2.id, status="completed", completed_at=now - timedelta(days=29), watch_seconds=840),
            LessonProgress(user_id=grace.id, lesson_id=dsl3.id, status="completed", completed_at=now - timedelta(days=28), watch_seconds=720),
            LessonProgress(user_id=grace.id, lesson_id=dsl4.id, status="completed", completed_at=now - timedelta(days=28)),
            LessonProgress(user_id=grace.id, lesson_id=dsl5.id, status="completed", completed_at=now - timedelta(days=20), watch_seconds=900),
            LessonProgress(user_id=grace.id, lesson_id=dsl6.id, status="completed", completed_at=now - timedelta(days=19)),
            LessonProgress(user_id=grace.id, lesson_id=dsl7.id, status="completed", completed_at=now - timedelta(days=18)),
            LessonProgress(user_id=grace.id, lesson_id=dsl8.id, status="completed", completed_at=now - timedelta(days=10), watch_seconds=780),
            LessonProgress(user_id=grace.id, lesson_id=dsl9.id, status="completed", completed_at=now - timedelta(days=9)),
            LessonProgress(user_id=grace.id, lesson_id=dsl10.id, status="completed", completed_at=now - timedelta(days=7)),
        ]

        db.add_all(
            alice_progress + bob_progress + dave_progress +
            emma_progress + frank_progress +
            grace_py_progress + grace_ds_progress
        )
        await db.flush()
        print("[+] Created lesson progress records.")

        # ── Quiz Submissions ─────────────────────────────────────────────────
        db.add_all([
            # Alice: Control Flow Quiz — fail then pass
            QuizSubmission(
                user_id=alice.id, quiz_id=quiz1.id, attempt_number=1,
                answers={str(q1.id): ["a"], str(q2.id): ["a"], str(q3.id): ["a"], str(q4.id): ["a"]},
                score=0, max_score=5, passed=False,
            ),
            QuizSubmission(
                user_id=alice.id, quiz_id=quiz1.id, attempt_number=2,
                answers={str(q1.id): ["b"], str(q2.id): ["a", "b"], str(q3.id): ["b"], str(q4.id): ["c"]},
                score=5, max_score=5, passed=True,
            ),
            # Bob: Control Flow Quiz — first attempt pass
            QuizSubmission(
                user_id=bob.id, quiz_id=quiz1.id, attempt_number=1,
                answers={str(q1.id): ["b"], str(q2.id): ["a", "b"], str(q3.id): ["b"], str(q4.id): ["c"]},
                score=5, max_score=5, passed=True,
            ),
            # Bob: Functions Quiz — pass
            QuizSubmission(
                user_id=bob.id, quiz_id=quiz_functions.id, attempt_number=1,
                answers={str(qf1.id): ["c"], str(qf2.id): ["b"], str(qf3.id): ["a", "b", "d"]},
                score=4, max_score=4, passed=True,
            ),
            # Grace: Control Flow Quiz — pass
            QuizSubmission(
                user_id=grace.id, quiz_id=quiz1.id, attempt_number=1,
                answers={str(q1.id): ["b"], str(q2.id): ["a", "b"], str(q3.id): ["b"], str(q4.id): ["c"]},
                score=5, max_score=5, passed=True,
            ),
            # Grace: Functions Quiz — pass
            QuizSubmission(
                user_id=grace.id, quiz_id=quiz_functions.id, attempt_number=1,
                answers={str(qf1.id): ["c"], str(qf2.id): ["b"], str(qf3.id): ["a", "b", "d"]},
                score=4, max_score=4, passed=True,
            ),
            # Grace: DS NumPy Quiz — pass
            QuizSubmission(
                user_id=grace.id, quiz_id=ds_quiz.id, attempt_number=1,
                answers={},
                score=4, max_score=4, passed=True,
            ),
            # Grace: DS Final Quiz — pass
            QuizSubmission(
                user_id=grace.id, quiz_id=ds_final_quiz.id, attempt_number=1,
                answers={},
                score=2, max_score=2, passed=True,
            ),
            # Dave: JS Variables Quiz — pass
            QuizSubmission(
                user_id=dave.id, quiz_id=js_quiz.id, attempt_number=1,
                answers={str(jsq1.id): ["b"], str(jsq2.id): ["a", "b", "d"], str(jsq3.id): ["c"]},
                score=4, max_score=4, passed=True,
            ),
            # Dave: JS Async Quiz — fail then pass
            QuizSubmission(
                user_id=dave.id, quiz_id=js_async_quiz.id, attempt_number=1,
                answers={},
                score=1, max_score=4, passed=False,
            ),
            QuizSubmission(
                user_id=dave.id, quiz_id=js_async_quiz.id, attempt_number=2,
                answers={},
                score=4, max_score=4, passed=True,
            ),
        ])
        await db.flush()
        print("[+] Created 11 quiz submissions.")

        # ── Assignment Submissions ─────────────────────────────────────────────
        db.add_all([
            # Alice — FizzBuzz, graded
            AssignmentSubmission(
                user_id=alice.id,
                assignment_id=asgn1.id,
                file_key="assignments/alice/fizzbuzz-v1.py",
                file_name="fizzbuzz.py",
                file_size=512,
                mime_type="text/x-python",
                scan_status="clean",
                submitted_at=now - timedelta(days=16),
                attempt_number=1,
                grade_score=88.0,
                grade_feedback="Great work! The logic is correct. Consider using f-strings for cleaner output.",
                grade_published_at=now - timedelta(days=14),
                graded_by=admin.id,
            ),
            # Bob — FizzBuzz, graded (perfect)
            AssignmentSubmission(
                user_id=bob.id,
                assignment_id=asgn1.id,
                file_key="assignments/bob/fizzbuzz.py",
                file_name="fizzbuzz.py",
                file_size=438,
                mime_type="text/x-python",
                scan_status="clean",
                submitted_at=now - timedelta(days=46),
                attempt_number=1,
                grade_score=100.0,
                grade_feedback="Perfect solution with clean, idiomatic Python. Well done!",
                grade_published_at=now - timedelta(days=44),
                graded_by=admin.id,
            ),
            # Bob — Calculator, graded
            AssignmentSubmission(
                user_id=bob.id,
                assignment_id=asgn_calc.id,
                file_key="assignments/bob/calculator.py",
                file_name="calculator.py",
                file_size=1_024,
                mime_type="text/x-python",
                scan_status="clean",
                submitted_at=now - timedelta(days=42),
                attempt_number=1,
                grade_score=95.0,
                grade_feedback="Excellent implementation. Division by zero is handled nicely. Minor point: the main() function could benefit from a loop for interactive use.",
                grade_published_at=now - timedelta(days=40),
                graded_by=admin.id,
            ),
            # Grace — Data Analysis, graded (perfect)
            AssignmentSubmission(
                user_id=grace.id,
                assignment_id=asgn_ds.id,
                file_key="assignments/grace/titanic-analysis.ipynb",
                file_name="titanic_analysis.ipynb",
                file_size=48_291,
                mime_type="application/x-ipynb+json",
                scan_status="clean",
                submitted_at=now - timedelta(days=18),
                attempt_number=1,
                grade_score=97.0,
                grade_feedback="Outstanding analysis! Your visualizations are clear and the survival rate breakdown is insightful. Consider adding a logistic regression model for extra credit.",
                grade_published_at=now - timedelta(days=15),
                graded_by=admin.id,
            ),
            # Dave — Closures assignment, submitted but not yet graded
            AssignmentSubmission(
                user_id=dave.id,
                assignment_id=asgn_closures.id,
                file_key="assignments/dave/counter-factory.js",
                file_name="counter_factory.js",
                file_size=892,
                mime_type="text/javascript",
                scan_status="clean",
                submitted_at=now - timedelta(days=27),
                attempt_number=1,
            ),
            # Alice — Closures assignment, pending
            AssignmentSubmission(
                user_id=alice.id,
                assignment_id=asgn_closures.id,
                file_key="assignments/alice/closures.js",
                file_name="closures.js",
                file_size=756,
                mime_type="text/javascript",
                scan_status="clean",
                submitted_at=now - timedelta(days=3),
                attempt_number=1,
            ),
        ])
        await db.flush()
        print("[+] Created 6 assignment submissions (4 graded, 2 pending).")

        # ── Certificates ──────────────────────────────────────────────────────
        cert_bob_py = Certificate(
            user_id=bob.id,
            course_id=py_course.id,
            verification_token=secrets.token_urlsafe(32),
            pdf_url="https://example.com/certificates/bob-python-for-beginners.pdf",
        )
        cert_grace_py = Certificate(
            user_id=grace.id,
            course_id=py_course.id,
            verification_token=secrets.token_urlsafe(32),
            pdf_url="https://example.com/certificates/grace-python-for-beginners.pdf",
        )
        cert_grace_ds = Certificate(
            user_id=grace.id,
            course_id=ds_course.id,
            verification_token=secrets.token_urlsafe(32),
            pdf_url="https://example.com/certificates/grace-python-data-science.pdf",
        )
        db.add_all([cert_bob_py, cert_grace_py, cert_grace_ds])
        await db.flush()

        # Alice has completed the JS course work — request pending review
        db.add(CertificateRequest(
            user_id=alice.id,
            course_id=js_course.id,
            status="pending",
        ))
        await db.flush()
        print("[+] Created 3 certificates and 1 certificate request.")

        # ── Announcements ─────────────────────────────────────────────────────
        db.add_all([
            Announcement(
                title="Welcome to xoxoedu!",
                body=(
                    "We're so excited to have you here. New courses are being added every month. "
                    "Check the catalogue for the latest additions, and don't forget to enrol in "
                    "a free course to get started today!"
                ),
                scope="platform",
                created_by=admin.id,
                sent_at=now - timedelta(days=30),
            ),
            Announcement(
                title="Python for Beginners — Chapter 3 is live",
                body=(
                    "We've just published Chapter 3: Functions & Modules! Head back to your course "
                    "dashboard to continue your learning journey. Three new lessons + a graded "
                    "assignment are waiting for you."
                ),
                scope="course",
                course_id=py_course.id,
                created_by=admin.id,
                sent_at=now - timedelta(days=7),
            ),
            Announcement(
                title="Scheduled maintenance — Sunday 02:00–04:00 UTC",
                body=(
                    "We will be performing infrastructure maintenance on Sunday. "
                    "The platform may be briefly unavailable during this window. "
                    "All progress is saved automatically — you won't lose any data."
                ),
                scope="platform",
                created_by=admin.id,
                sent_at=now - timedelta(days=3),
            ),
            Announcement(
                title="Data Science course — new dataset added",
                body=(
                    "We've added a richer Titanic dataset with additional feature columns "
                    "to the Data Analysis assignment. Re-download the resource file from "
                    "Lesson 7 to access the updated version."
                ),
                scope="course",
                course_id=ds_course.id,
                created_by=admin.id,
                sent_at=now - timedelta(days=1),
            ),
            # Drafted (not yet sent)
            Announcement(
                title="TypeScript Deep Dive — Spring sale",
                body=(
                    "For a limited time, use coupon code **TSLAUNCH** at checkout to get "
                    "30% off TypeScript Deep Dive. Offer ends April 30."
                ),
                scope="platform",
                created_by=admin.id,
                sent_at=None,
            ),
        ])
        await db.flush()
        print("[+] Created 5 announcements (4 sent, 1 draft).")

        # ── Notes & Bookmarks ────────────────────────────────────────────────
        db.add_all([
            UserNote(user_id=alice.id, lesson_id=l2.id, content="Remember to add Python to PATH on Windows!"),
            UserNote(user_id=alice.id, lesson_id=l4.id, content="`elif` is Python's version of else-if."),
            UserNote(user_id=alice.id, lesson_id=jsl2.id, content="typeof null === 'object' is a famous JS bug — keep this in mind."),
            UserNote(user_id=bob.id, lesson_id=l8.id, content="Default parameter values are evaluated once at definition time for mutable types — watch out!"),
            UserNote(user_id=bob.id, lesson_id=dsl3.id, content="Broadcasting rules: dimensions are aligned right-to-left; sizes must match or be 1."),
            UserNote(user_id=dave.id, lesson_id=jsl7.id, content="Promise.all fails fast — use Promise.allSettled if you need all results regardless of failures."),
            UserNote(user_id=dave.id, lesson_id=tsl1.id, content="Enable strict mode in tsconfig for the best type safety experience."),
            UserNote(user_id=grace.id, lesson_id=dsl5.id, content="df.groupby().agg() is the Swiss Army knife of Pandas — learn it well."),
        ])
        db.add_all([
            UserBookmark(user_id=alice.id, lesson_id=l5.id),
            UserBookmark(user_id=alice.id, lesson_id=jsl2.id),
            UserBookmark(user_id=alice.id, lesson_id=l8.id),
            UserBookmark(user_id=bob.id, lesson_id=dsl3.id),
            UserBookmark(user_id=bob.id, lesson_id=dsl6.id),
            UserBookmark(user_id=dave.id, lesson_id=jsl7.id),
            UserBookmark(user_id=dave.id, lesson_id=tsl5.id),
            UserBookmark(user_id=grace.id, lesson_id=dsl5.id),
            UserBookmark(user_id=grace.id, lesson_id=dsl8.id),
            UserBookmark(user_id=frank.id, lesson_id=l1.id),
        ])
        await db.commit()
        print("[+] Created 8 notes and 10 bookmarks.")

        print()
        print("Seed complete.")
        print()
        print("  Credentials")
        print("  ────────────────────────────────────────────────────────────────────────")
        print("  admin@xoxoedu.com  / admin123       role: admin")
        print("  alice@example.com  / password123    role: student  (in progress, cert request)")
        print("  bob@example.com    / password123    role: student  (completed Python, has cert)")
        print("  carol@example.com  / password123    role: student  (not enrolled, unverified)")
        print("  dave@example.com   / password123    role: student  (JS done, TS in progress)")
        print("  emma@example.com   / password123    role: student  (Python ch1 done, JS started)")
        print("  frank@example.com  / password123    role: student  (beginner, just started Python)")
        print("  grace@example.com  / password123    role: student  (completed Python + DS, certs)")
        print("  hannah@example.com / password123    role: student  (unenrolled from Python)")
        print("  ivan@example.com   / password123    role: student  (unverified, failed payment)")

    await engine.dispose()


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    asyncio.run(main(reset=reset))
