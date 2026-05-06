#!/usr/bin/env python3
"""
Seed the database with the three XOXO programs (OC, PT, FE), realistic
student profiles, subscriptions, placements, batches, live sessions, and
billing notifications.

Usage:
    uv run scripts/seed_db.py              # seed (skips if already seeded)
    uv run scripts/seed_db.py --reset      # wipe all seed data and re-seed
"""
import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_SEED_MARKER_SLUG = "grammar-foundations"  # OC program's first course


async def _reset(db) -> None:
    from sqlalchemy import text

    tables = [
        # New aligned tables — must come first (cascade order)
        "session_attendance",
        "live_sessions",
        "batch_transfer_requests",
        "batch_enrollments",
        "batches",
        "placement_results",
        "placement_attempts",
        "payment_transactions",
        "billing_cycles",
        "subscriptions",
        "subscription_plans",
        "program_enrollments",
        "program_steps",
        "programs",
        # Notification tables
        "notification_deliveries",
        "notifications",
        "notification_preferences",
        # Legacy content tables
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


def _assert_migrations_current() -> None:
    """Exit with a clear message if alembic migrations are not at head.

    Uses alembic's own API to compare the DB's current revision against the
    head of the local migration scripts.  Call this before any seeding or reset
    so that truncate/insert errors caused by missing tables are surfaced early
    with actionable guidance.
    """
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text

    # Resolve alembic.ini relative to the backend root (one level up from scripts/)
    alembic_ini = Path(__file__).parent.parent / "alembic.ini"

    from app.config import settings as _settings

    sync_url = _settings.DATABASE_URL_SYNC

    try:
        engine = create_engine(sync_url)
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_heads = set(context.get_current_heads())
        engine.dispose()
    except Exception as exc:
        print(f"[!] Could not connect to database to check migrations: {exc}")
        sys.exit(1)

    script = ScriptDirectory.from_config(Config(str(alembic_ini)))
    expected_heads = set(script.get_heads())

    if current_heads != expected_heads:
        missing = expected_heads - current_heads
        print("[!] Database schema is not up to date.")
        print(f"    Current:  {current_heads or '(no migrations applied)'}")
        print(f"    Expected: {expected_heads}")
        if missing:
            print(f"    Missing:  {missing}")
        print()
        print("    Run:  alembic upgrade head")
        sys.exit(1)


async def main(reset: bool = False) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings
    from app.core.security import hash_password
    from app.db.models.batch import Batch, BatchEnrollment, BatchTransferRequest
    from app.db.models.course import Category, Chapter, Course, Lesson
    from app.db.models.enrollment import Enrollment, LessonProgress
    from app.db.models.live_session import LiveSession
    from app.db.models.notification import Notification
    from app.db.models.placement import PlacementAttempt, PlacementResult
    from app.db.models.program import Program, ProgramEnrollment, ProgramStep
    from app.db.models.session_attendance import SessionAttendance
    from app.db.models.subscription import (
        BillingCycle,
        PaymentTransaction,
        Subscription,
        SubscriptionPlan,
    )
    from app.db.models.user import User
    from app.modules.notifications.constants import NotificationType

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
        today = now.date()

        # ── Users ─────────────────────────────────────────────────────────────
        admin = User(
            email="admin@xoxoedu.com",
            password_hash=hash_password("Admin1234!"),
            role="admin",
            email_verified=True,
            display_name="Admin",
            headline="Platform administrator",
        )
        alice = User(
            email="alice@student.com",
            password_hash=hash_password("Student1234!"),
            role="student",
            email_verified=True,
            display_name="Alice Ferreira",
            country="BR",
            bio="Improving my English to grow my international career.",
            headline="Marketing Professional",
        )
        bob = User(
            email="bob@student.com",
            password_hash=hash_password("Student1234!"),
            role="student",
            email_verified=True,
            display_name="Bob Tremblay",
            country="CA",
            bio="Learning English for professional development.",
            headline="Software Developer",
        )
        carol = User(
            email="carol@student.com",
            password_hash=hash_password("Student1234!"),
            role="student",
            email_verified=True,
            display_name="Carol Santos",
            country="PT",
            bio="Fluent English speaker looking to refine my skills.",
            headline="UX Designer",
        )
        db.add_all([admin, alice, bob, carol])
        await db.flush()
        print("[+] Created 4 users (1 admin, 3 students).")

        # ── Subscription Plans ────────────────────────────────────────────────
        plan_br = SubscriptionPlan(
            name="Brazil Monthly",
            market="BR",
            currency="BRL",
            amount_cents=2990,
            interval="month",
            is_active=True,
        )
        plan_ca = SubscriptionPlan(
            name="Canada Monthly",
            market="CA",
            currency="CAD",
            amount_cents=1990,
            interval="month",
            is_active=True,
        )
        plan_eu = SubscriptionPlan(
            name="Europe Monthly",
            market="EU",
            currency="EUR",
            amount_cents=1490,
            interval="month",
            is_active=True,
        )
        db.add_all([plan_br, plan_ca, plan_eu])
        await db.flush()
        print("[+] Created 3 subscription plans (BR, CA, EU).")

        # ── Subscriptions ─────────────────────────────────────────────────────
        period_start = now - timedelta(days=15)
        period_end = now + timedelta(days=15)

        sub_alice = Subscription(
            user_id=alice.id,
            plan_id=plan_br.id,
            market="BR",
            currency="BRL",
            amount_cents=2990,
            status="active",
            provider="stripe",
            provider_subscription_id="sub_test_alice",
            stripe_customer_id="cus_test_alice",
            current_period_start=period_start,
            current_period_end=period_end,
        )
        sub_bob = Subscription(
            user_id=bob.id,
            plan_id=plan_ca.id,
            market="CA",
            currency="CAD",
            amount_cents=1990,
            status="active",
            provider="stripe",
            provider_subscription_id="sub_test_bob",
            stripe_customer_id="cus_test_bob",
            current_period_start=period_start,
            current_period_end=period_end,
        )
        sub_carol = Subscription(
            user_id=carol.id,
            plan_id=plan_eu.id,
            market="EU",
            currency="EUR",
            amount_cents=1490,
            status="past_due",
            provider="stripe",
            provider_subscription_id="sub_test_carol",
            stripe_customer_id="cus_test_carol",
            current_period_start=now - timedelta(days=45),
            current_period_end=now - timedelta(days=15),
        )
        db.add_all([sub_alice, sub_bob, sub_carol])
        await db.flush()

        # Alice: paid cycle + succeeded transaction
        cycle_alice = BillingCycle(
            subscription_id=sub_alice.id,
            due_date=today - timedelta(days=15),
            paid_at=now - timedelta(days=14),
            amount_cents=2990,
            currency="BRL",
            status="paid",
        )
        db.add(cycle_alice)
        await db.flush()
        db.add(PaymentTransaction(
            user_id=alice.id,
            subscription_id=sub_alice.id,
            billing_cycle_id=cycle_alice.id,
            amount_cents=2990,
            currency="BRL",
            status="succeeded",
            provider="stripe",
            provider_transaction_id="ch_test_alice_001",
        ))

        # Bob: paid cycle
        cycle_bob = BillingCycle(
            subscription_id=sub_bob.id,
            due_date=today - timedelta(days=15),
            paid_at=now - timedelta(days=14),
            amount_cents=1990,
            currency="CAD",
            status="paid",
        )
        db.add(cycle_bob)

        # Carol: pending overdue cycle (triggers billing reminder)
        cycle_carol = BillingCycle(
            subscription_id=sub_carol.id,
            due_date=today - timedelta(days=15),
            amount_cents=1490,
            currency="EUR",
            status="pending",
        )
        db.add(cycle_carol)
        await db.flush()
        print("[+] Created 3 subscriptions with billing cycles.")

        # ── Programs ──────────────────────────────────────────────────────────
        prog_pt = Program(
            code="PT",
            title="Portuguese Program",
            description=(
                "Weekly live conversation sessions to develop fluency and confidence "
                "through music, cinema, and travel topics. Intermediate level."
            ),
            marketing_summary="Live Portuguese conversation circles built around culture, confidence, and weekly speaking practice.",
            cover_image_url="https://images.unsplash.com/photo-1516302752625-fcc3c50ae61f?auto=format&fit=crop&w=1200&q=80",
            display_order=1,
            is_active=True,
        )
        prog_fe = Program(
            code="FE",
            title="Fluent English Program",
            description=(
                "Weekly live discussion groups conducted entirely in English for "
                "fluent speakers to refine critical thinking and cultural exchange. Advanced level."
            ),
            marketing_summary="Advanced English discussion pathways designed to sharpen clarity, confidence, and real-world expression.",
            cover_image_url="https://images.unsplash.com/photo-1522202176988-66273c2fd55f?auto=format&fit=crop&w=1200&q=80",
            display_order=2,
            is_active=True,
        )
        prog_oc = Program(
            code="OC",
            title="Online Course",
            description=(
                "Self-paced recorded lessons covering grammar and practical vocabulary, "
                "with AI-personalized review activities. Beginner level."
            ),
            marketing_summary="Self-paced foundations with structured lessons, practical vocabulary, and flexible review support.",
            cover_image_url="https://images.unsplash.com/photo-1513258496099-48168024aec0?auto=format&fit=crop&w=1200&q=80",
            display_order=3,
            is_active=True,
        )
        db.add_all([prog_pt, prog_fe, prog_oc])
        await db.flush()
        print("[+] Created 3 programs (PT, FE, OC).")

        # ── Courses + Chapters + Lessons ──────────────────────────────────────

        def _make_text_lesson(chapter_id, title, position, body, is_free_preview=False):
            return Lesson(
                chapter_id=chapter_id,
                title=title,
                type="text",
                position=position,
                is_free_preview=is_free_preview,
                content={"body": body},
            )

        # PT — Course 1: Conversation Basics
        cat_language = Category(name="Language Learning", slug="language-learning")
        db.add(cat_language)
        await db.flush()

        course_pt1 = Course(
            slug="conversation-basics",
            title="Conversation Basics",
            description="Foundational conversation skills for intermediate English speakers.",
            category_id=cat_language.id,
            level="intermediate",
            status="published",
            display_instructor_name="XOXO Education Team",
            created_by=admin.id,
        )
        db.add(course_pt1)
        await db.flush()

        ch_pt1a = Chapter(course_id=course_pt1.id, title="Getting Started", position=1)
        db.add(ch_pt1a)
        await db.flush()
        lessons_pt1 = [
            _make_text_lesson(ch_pt1a.id, "Welcome to the PT Program", 1,
                "<p>Overview of the Portuguese Program format and weekly session structure.</p>",
                is_free_preview=True),
            _make_text_lesson(ch_pt1a.id, "Introducing Yourself", 2,
                "<p>Phrases and vocabulary for introductions in social and professional settings.</p>"),
            _make_text_lesson(ch_pt1a.id, "Everyday Topics: Music and Cinema", 3,
                "<p>Discussing music genres, movies, and personal preferences in English.</p>"),
        ]
        db.add_all(lessons_pt1)
        await db.flush()

        # PT — Course 2: Real-World Topics
        course_pt2 = Course(
            slug="real-world-topics",
            title="Real-World Topics",
            description="Advanced conversation practice on travel, culture, and current events.",
            category_id=cat_language.id,
            level="intermediate",
            status="published",
            display_instructor_name="XOXO Education Team",
            created_by=admin.id,
        )
        db.add(course_pt2)
        await db.flush()

        ch_pt2a = Chapter(course_id=course_pt2.id, title="Travel and Culture", position=1)
        db.add(ch_pt2a)
        await db.flush()
        lessons_pt2 = [
            _make_text_lesson(ch_pt2a.id, "Talking About Travel", 1,
                "<p>Vocabulary and expressions for describing travel experiences.</p>",
                is_free_preview=True),
            _make_text_lesson(ch_pt2a.id, "Cultural Exchange", 2,
                "<p>Comparing cultural customs and traditions across countries.</p>"),
            _make_text_lesson(ch_pt2a.id, "Current Events Discussion", 3,
                "<p>Frameworks for discussing news and current events confidently.</p>"),
        ]
        db.add_all(lessons_pt2)
        await db.flush()

        # FE — Course 1: Critical Discussions
        course_fe1 = Course(
            slug="critical-discussions",
            title="Critical Discussions",
            description="Structured discussion practice on culture, ideas, and current events.",
            category_id=cat_language.id,
            level="advanced",
            status="published",
            display_instructor_name="XOXO Education Team",
            created_by=admin.id,
        )
        db.add(course_fe1)
        await db.flush()

        ch_fe1a = Chapter(course_id=course_fe1.id, title="Discussion Foundations", position=1)
        db.add(ch_fe1a)
        await db.flush()
        lessons_fe1 = [
            _make_text_lesson(ch_fe1a.id, "Welcome to the FE Program", 1,
                "<p>Overview of the Fluent English Program discussion format and expectations.</p>",
                is_free_preview=True),
            _make_text_lesson(ch_fe1a.id, "Structuring Your Argument", 2,
                "<p>Techniques for presenting clear, logical arguments in group discussions.</p>"),
            _make_text_lesson(ch_fe1a.id, "Active Listening and Response", 3,
                "<p>Listening strategies and how to respond constructively in live discussions.</p>"),
        ]
        db.add_all(lessons_fe1)
        await db.flush()

        # FE — Course 2: Cultural Exchange
        course_fe2 = Course(
            slug="cultural-exchange",
            title="Cultural Exchange",
            description="Exploring global cultural perspectives through guided English discussions.",
            category_id=cat_language.id,
            level="advanced",
            status="published",
            display_instructor_name="XOXO Education Team",
            created_by=admin.id,
        )
        db.add(course_fe2)
        await db.flush()

        ch_fe2a = Chapter(course_id=course_fe2.id, title="Global Perspectives", position=1)
        db.add(ch_fe2a)
        await db.flush()
        lessons_fe2 = [
            _make_text_lesson(ch_fe2a.id, "Cross-Cultural Communication", 1,
                "<p>Understanding and navigating cultural differences in English conversations.</p>",
                is_free_preview=True),
            _make_text_lesson(ch_fe2a.id, "Tech and Society", 2,
                "<p>Discussing technology's impact on society, work, and personal life.</p>"),
            _make_text_lesson(ch_fe2a.id, "Values and Identity", 3,
                "<p>Articulating personal values and exploring identity through discussion.</p>"),
        ]
        db.add_all(lessons_fe2)
        await db.flush()

        # OC — Course 1: Grammar Foundations
        course_oc1 = Course(
            slug="grammar-foundations",  # seed marker
            title="Grammar Foundations",
            description="Short interactive lessons covering core English grammar rules.",
            category_id=cat_language.id,
            level="beginner",
            status="published",
            display_instructor_name="XOXO Education Team",
            created_by=admin.id,
        )
        db.add(course_oc1)
        await db.flush()

        ch_oc1a = Chapter(course_id=course_oc1.id, title="Sentence Structure", position=1)
        ch_oc1b = Chapter(course_id=course_oc1.id, title="Verb Tenses", position=2)
        db.add_all([ch_oc1a, ch_oc1b])
        await db.flush()
        lessons_oc1a = [
            _make_text_lesson(ch_oc1a.id, "Welcome to the Online Course", 1,
                "<p>Overview of the OC program: self-paced lessons, quizzes, and AI review.</p>",
                is_free_preview=True),
            _make_text_lesson(ch_oc1a.id, "Nouns and Articles", 2,
                "<p>Using definite and indefinite articles correctly with singular and plural nouns.</p>"),
        ]
        lessons_oc1b = [
            _make_text_lesson(ch_oc1b.id, "Simple Present Tense", 1,
                "<p>Forming and using the simple present for habits, routines, and facts.</p>"),
            _make_text_lesson(ch_oc1b.id, "Simple Past Tense", 2,
                "<p>Regular and irregular past tense verbs with practice exercises.</p>"),
        ]
        db.add_all(lessons_oc1a + lessons_oc1b)
        await db.flush()

        # OC — Course 2: Practical Vocabulary
        course_oc2 = Course(
            slug="practical-vocabulary",
            title="Practical Vocabulary",
            description="Everyday English vocabulary for work, travel, and daily life.",
            category_id=cat_language.id,
            level="beginner",
            status="published",
            display_instructor_name="XOXO Education Team",
            created_by=admin.id,
        )
        db.add(course_oc2)
        await db.flush()

        ch_oc2a = Chapter(course_id=course_oc2.id, title="Workplace English", position=1)
        ch_oc2b = Chapter(course_id=course_oc2.id, title="Travel English", position=2)
        db.add_all([ch_oc2a, ch_oc2b])
        await db.flush()
        lessons_oc2a = [
            _make_text_lesson(ch_oc2a.id, "Emails and Meetings", 1,
                "<p>Essential vocabulary for professional emails and workplace meetings.</p>"),
            _make_text_lesson(ch_oc2a.id, "Asking for Help", 2,
                "<p>Polite expressions for requesting assistance and clarification at work.</p>"),
        ]
        lessons_oc2b = [
            _make_text_lesson(ch_oc2b.id, "At the Airport", 1,
                "<p>Check-in, security, and boarding vocabulary for international travel.</p>"),
            _make_text_lesson(ch_oc2b.id, "Restaurants and Hotels", 2,
                "<p>Ordering food, making reservations, and handling travel situations confidently.</p>"),
        ]
        db.add_all(lessons_oc2a + lessons_oc2b)
        await db.flush()

        # OC — Course 3: AI Review Practice
        course_oc3 = Course(
            slug="ai-review-practice",
            title="AI Review Practice",
            description="Adaptive AI-personalized review activities based on your quiz performance.",
            category_id=cat_language.id,
            level="beginner",
            status="published",
            display_instructor_name="XOXO Education Team",
            created_by=admin.id,
        )
        db.add(course_oc3)
        await db.flush()

        ch_oc3a = Chapter(course_id=course_oc3.id, title="AI-Powered Review", position=1)
        ch_oc3b = Chapter(course_id=course_oc3.id, title="Progress Check", position=2)
        db.add_all([ch_oc3a, ch_oc3b])
        await db.flush()
        lessons_oc3a = [
            _make_text_lesson(ch_oc3a.id, "How AI Review Works", 1,
                "<p>Understanding how the platform personalizes your practice based on past performance.</p>",
                is_free_preview=True),
            _make_text_lesson(ch_oc3a.id, "Grammar Patterns Review", 2,
                "<p>AI-selected grammar exercises tailored to your weakest areas.</p>"),
        ]
        lessons_oc3b = [
            _make_text_lesson(ch_oc3b.id, "Vocabulary Recall Drills", 1,
                "<p>Spaced-repetition vocabulary practice using your learning history.</p>"),
            _make_text_lesson(ch_oc3b.id, "Final Practice Assessment", 2,
                "<p>Comprehensive adaptive quiz covering all OC program content.</p>"),
        ]
        db.add_all(lessons_oc3a + lessons_oc3b)
        await db.flush()
        print("[+] Created 7 courses with chapters and lessons (PT×2, FE×2, OC×3).")

        # ── Program Steps ─────────────────────────────────────────────────────
        db.add_all([
            ProgramStep(program_id=prog_pt.id, course_id=course_pt1.id, position=1, is_required=True),
            ProgramStep(program_id=prog_pt.id, course_id=course_pt2.id, position=2, is_required=True),
            ProgramStep(program_id=prog_fe.id, course_id=course_fe1.id, position=1, is_required=True),
            ProgramStep(program_id=prog_fe.id, course_id=course_fe2.id, position=2, is_required=True),
            ProgramStep(program_id=prog_oc.id, course_id=course_oc1.id, position=1, is_required=True),
            ProgramStep(program_id=prog_oc.id, course_id=course_oc2.id, position=2, is_required=True),
            ProgramStep(program_id=prog_oc.id, course_id=course_oc3.id, position=3, is_required=True),
        ])
        await db.flush()
        print("[+] Created program steps (PT×2, FE×2, OC×3).")

        # ── Placement ─────────────────────────────────────────────────────────
        # Alice: B1 → PT
        attempt_alice = PlacementAttempt(
            user_id=alice.id,
            answers={"q1": "b", "q2": "a", "q3": "c", "q4": "b", "q5": "a"},
            score=18,
            started_at=now - timedelta(days=35),
            completed_at=now - timedelta(days=35),
        )
        # Bob: A2 → OC
        attempt_bob = PlacementAttempt(
            user_id=bob.id,
            answers={"q1": "a", "q2": "b", "q3": "a", "q4": "a", "q5": "b"},
            score=8,
            started_at=now - timedelta(days=30),
            completed_at=now - timedelta(days=30),
        )
        # Carol: C1 → FE
        attempt_carol = PlacementAttempt(
            user_id=carol.id,
            answers={"q1": "c", "q2": "b", "q3": "c", "q4": "c", "q5": "b"},
            score=28,
            started_at=now - timedelta(days=28),
            completed_at=now - timedelta(days=28),
        )
        db.add_all([attempt_alice, attempt_bob, attempt_carol])
        await db.flush()

        db.add_all([
            PlacementResult(
                user_id=alice.id,
                attempt_id=attempt_alice.id,
                program_id=prog_pt.id,
                level="B1",
                is_override=False,
            ),
            PlacementResult(
                user_id=bob.id,
                attempt_id=attempt_bob.id,
                program_id=prog_oc.id,
                level="A2",
                is_override=False,
            ),
            PlacementResult(
                user_id=carol.id,
                attempt_id=attempt_carol.id,
                program_id=prog_fe.id,
                level="C1",
                is_override=False,
            ),
        ])
        await db.flush()
        print("[+] Created placement attempts and results.")

        # ── Program Enrollments ───────────────────────────────────────────────
        pe_alice = ProgramEnrollment(
            user_id=alice.id,
            program_id=prog_pt.id,
            status="active",
        )
        pe_bob = ProgramEnrollment(
            user_id=bob.id,
            program_id=prog_oc.id,
            status="active",
        )
        pe_carol = ProgramEnrollment(
            user_id=carol.id,
            program_id=prog_fe.id,
            status="active",
        )
        db.add_all([pe_alice, pe_bob, pe_carol])
        await db.flush()
        print("[+] Created program enrollments (alice→PT, bob→OC, carol→FE).")

        # ── Course Enrollments (for unlock engine) ────────────────────────────
        # Alice has completed PT step 1 (course_pt1), so she needs an Enrollment row.
        enr_alice_pt1 = Enrollment(
            user_id=alice.id,
            course_id=course_pt1.id,
            status="completed",
        )
        # Bob is on OC step 1 — active enrollment
        enr_bob_oc1 = Enrollment(
            user_id=bob.id,
            course_id=course_oc1.id,
            status="active",
        )
        # Carol is on FE step 1 — active enrollment
        enr_carol_fe1 = Enrollment(
            user_id=carol.id,
            course_id=course_fe1.id,
            status="active",
        )
        db.add_all([enr_alice_pt1, enr_bob_oc1, enr_carol_fe1])
        await db.flush()

        # ── Lesson Progress ───────────────────────────────────────────────────
        # Alice: all lessons in PT step 1 completed
        for lesson in lessons_pt1:
            db.add(LessonProgress(
                user_id=alice.id,
                lesson_id=lesson.id,
                status="completed",
                completed_at=now - timedelta(days=7),
            ))
        # Bob: first lesson of OC step 1 completed
        db.add(LessonProgress(
            user_id=bob.id,
            lesson_id=lessons_oc1a[0].id,
            status="completed",
            completed_at=now - timedelta(days=3),
        ))
        # Carol: first 2 lessons of FE step 1 completed
        for lesson in lessons_fe1[:2]:
            db.add(LessonProgress(
                user_id=carol.id,
                lesson_id=lesson.id,
                status="completed",
                completed_at=now - timedelta(days=5),
            ))
        await db.flush()
        print("[+] Created lesson progress records.")

        # ── Batches (capacity=15) ─────────────────────────────────────────────
        batch_pt_a = Batch(
            program_id=prog_pt.id,
            title="PT Spring 2026 — Cohort A",
            status="active",
            timezone="America/Sao_Paulo",
            starts_at=now - timedelta(days=30),
            ends_at=now + timedelta(days=60),
            capacity=15,
        )
        batch_pt_b = Batch(
            program_id=prog_pt.id,
            title="PT Summer 2026 — Cohort B",
            status="upcoming",
            timezone="America/Sao_Paulo",
            starts_at=now + timedelta(days=14),
            ends_at=now + timedelta(days=104),
            capacity=15,
        )
        batch_fe_a = Batch(
            program_id=prog_fe.id,
            title="FE Spring 2026 — Cohort A",
            status="active",
            timezone="Europe/Lisbon",
            starts_at=now - timedelta(days=14),
            ends_at=now + timedelta(days=46),
            capacity=15,
        )
        batch_oc_a = Batch(
            program_id=prog_oc.id,
            title="OC Spring 2026 — Cohort A",
            status="active",
            timezone="America/Toronto",
            starts_at=now - timedelta(days=7),
            ends_at=now + timedelta(days=83),
            capacity=15,
        )
        batch_oc_b = Batch(
            program_id=prog_oc.id,
            title="OC Summer 2026 — Cohort B",
            status="upcoming",
            timezone="America/Toronto",
            starts_at=now + timedelta(days=14),
            ends_at=now + timedelta(days=104),
            capacity=15,
        )
        db.add_all([batch_pt_a, batch_pt_b, batch_fe_a, batch_oc_a, batch_oc_b])
        await db.flush()
        print("[+] Created 5 batches (PT×2, FE×1, OC×2) with capacity=15.")

        # ── Batch Enrollments ─────────────────────────────────────────────────
        db.add_all([
            BatchEnrollment(batch_id=batch_pt_a.id, user_id=alice.id, program_enrollment_id=pe_alice.id),
            BatchEnrollment(batch_id=batch_fe_a.id, user_id=carol.id, program_enrollment_id=pe_carol.id),
            BatchEnrollment(batch_id=batch_oc_a.id, user_id=bob.id, program_enrollment_id=pe_bob.id),
        ])
        await db.flush()
        print("[+] Created batch enrollments (alice→PT-A, carol→FE-A, bob→OC-A).")

        # ── Live Sessions ─────────────────────────────────────────────────────
        # PT Batch A — 2 sessions
        session_pt1 = LiveSession(
            batch_id=batch_pt_a.id,
            title="Música e Cinema",
            description="Discussion session on music genres and favourite films.",
            starts_at=now - timedelta(days=7),
            ends_at=now - timedelta(days=7) + timedelta(hours=1),
            timezone="America/Sao_Paulo",
            provider="google_meet",
            join_url="https://meet.google.com/test-pt-001",
            status="scheduled",
        )
        session_pt2 = LiveSession(
            batch_id=batch_pt_a.id,
            title="Viagens",
            description="Sharing travel stories and discussing dream destinations.",
            starts_at=now + timedelta(days=7),
            ends_at=now + timedelta(days=7) + timedelta(hours=1),
            timezone="America/Sao_Paulo",
            provider="google_meet",
            join_url="https://meet.google.com/test-pt-002",
            status="scheduled",
        )
        # FE Batch A — 2 sessions
        session_fe1 = LiveSession(
            batch_id=batch_fe_a.id,
            title="Current Events",
            description="Discussion of this week's top news stories.",
            starts_at=now - timedelta(days=3),
            ends_at=now - timedelta(days=3) + timedelta(hours=1),
            timezone="Europe/Lisbon",
            provider="zoom",
            join_url="https://zoom.us/test-fe-001",
            status="scheduled",
        )
        session_fe2 = LiveSession(
            batch_id=batch_fe_a.id,
            title="Tech and Society",
            description="How technology is reshaping the world — an open discussion.",
            starts_at=now + timedelta(days=7),
            ends_at=now + timedelta(days=7) + timedelta(hours=1),
            timezone="Europe/Lisbon",
            provider="zoom",
            join_url="https://zoom.us/test-fe-002",
            status="scheduled",
        )
        # OC Batch A — 1 session (office hours / Q&A)
        session_oc1 = LiveSession(
            batch_id=batch_oc_a.id,
            title="Grammar Q&A",
            description="Live office hours to answer questions about grammar foundations.",
            starts_at=now - timedelta(days=1),
            ends_at=now - timedelta(days=1) + timedelta(hours=1),
            timezone="America/Toronto",
            provider="zoom",
            join_url="https://zoom.us/test-oc-001",
            status="scheduled",
        )
        db.add_all([session_pt1, session_pt2, session_fe1, session_fe2, session_oc1])
        await db.flush()
        print("[+] Created 5 live sessions (PT×2, FE×2, OC×1).")

        # ── Session Attendance (past sessions only) ───────────────────────────
        db.add_all([
            SessionAttendance(session_id=session_pt1.id, user_id=alice.id, status="present"),
            SessionAttendance(session_id=session_fe1.id, user_id=carol.id, status="present"),
            SessionAttendance(session_id=session_oc1.id, user_id=bob.id, status="absent"),
        ])
        await db.flush()
        print("[+] Created session attendance records.")

        # ── Batch Transfer Request ────────────────────────────────────────────
        db.add(BatchTransferRequest(
            user_id=bob.id,
            from_batch_id=batch_oc_a.id,
            to_batch_id=batch_oc_b.id,
            status="pending",
            reason="My schedule changed and I need a later cohort start date.",
        ))
        await db.flush()
        print("[+] Created batch transfer request (bob: OC-A → OC-B, pending).")

        # ── Notifications ─────────────────────────────────────────────────────
        db.add_all([
            # Carol: payment overdue reminder
            Notification(
                recipient_id=carol.id,
                type=NotificationType.PAYMENT_DUE_SOON,
                title="Your payment is overdue",
                body=(
                    f"Your subscription payment of €14.90 was due on "
                    f"{(today - timedelta(days=15)).strftime('%B %d, %Y')}. "
                    "Please update your payment method to maintain access."
                ),
                actor_summary="XOXO Education",
                target_url="/home/account",
                event_metadata={
                    "subscription_id": str(sub_carol.id),
                    "billing_cycle_id": str(cycle_carol.id),
                    "amount_cents": 1490,
                    "currency": "EUR",
                },
            ),
            # Bob: batch transfer update
            Notification(
                recipient_id=bob.id,
                type=NotificationType.LIVE_SESSION_REMINDER,
                title="Transfer request received",
                body="Your request to transfer to OC Summer 2026 — Cohort B has been received and is under review.",
                actor_summary="XOXO Education",
                target_url="/home/batch",
                event_metadata={
                    "from_batch_id": str(batch_oc_a.id),
                    "to_batch_id": str(batch_oc_b.id),
                },
            ),
            # Alice: program milestone
            Notification(
                recipient_id=alice.id,
                type=NotificationType.GRADE_PUBLISHED,
                title="Step 1 complete — well done!",
                body="You've finished Conversation Basics. Step 2 (Real-World Topics) is now unlocked.",
                actor_summary="XOXO Education",
                target_url="/programs/PT",
                event_metadata={
                    "program_id": str(prog_pt.id),
                    "completed_step_position": 1,
                },
            ),
            # Carol: upcoming session reminder
            Notification(
                recipient_id=carol.id,
                type=NotificationType.LIVE_SESSION_REMINDER,
                title="Live session tomorrow: Tech and Society",
                body="Your FE discussion group meets tomorrow. Topic: Tech and Society. Join link is ready.",
                actor_summary="XOXO Education",
                target_url="/home/calendar",
                event_metadata={
                    "session_id": str(session_fe2.id),
                    "batch_id": str(batch_fe_a.id),
                },
            ),
        ])
        await db.commit()
        print("[+] Created 4 notifications.")

        # ── Summary ───────────────────────────────────────────────────────────
        print()
        print("Seed complete.")
        print()
        print("  Credentials")
        print("  ─────────────────────────────────────────────────────────")
        print("  admin@xoxoedu.com   / Admin1234!    role: admin")
        print("  alice@student.com   / Student1234!  role: student (PT, active, step 2)")
        print("  bob@student.com     / Student1234!  role: student (OC, active, pending transfer)")
        print("  carol@student.com   / Student1234!  role: student (FE, past_due subscription)")
        print()
        print("  Programs")
        print("  ─────────────────────────────────────────────────────────")
        print("  PT  Portuguese Program       — 2 steps, 1 active batch")
        print("  FE  Fluent English Program   — 2 steps, 1 active batch")
        print("  OC  Online Course            — 3 steps, 1 active + 1 upcoming batch")

    await engine.dispose()


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    _assert_migrations_current()
    asyncio.run(main(reset=reset))
