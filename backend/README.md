# XOXO Education — Backend

The backend is a Python 3.12 + FastAPI application serving all XOXO Education functionality via a versioned REST API. It uses a monolith-with-module-boundaries architecture — Core, AI, and Media are feature modules within a single deployable service — backed by PostgreSQL (with pgvector), Redis, and S3-compatible object storage.

---

## Table of Contents

1. [Tech Stack](#1-tech-stack)
2. [System Design](#2-system-design)
3. [Module Structure](#3-module-structure)
4. [Database Schema](#4-database-schema)
5. [API Endpoints](#5-api-endpoints)
6. [Authentication & Security](#6-authentication--security)
7. [Background Jobs](#7-background-jobs)
8. [AI Features](#8-ai-features)
9. [Environment Variables](#9-environment-variables)
10. [Testing](#10-testing)
11. [Deployment](#11-deployment)
12. [Trade-offs & Design Decisions](#12-trade-offs--design-decisions)
13. [Scalability](#13-scalability)
14. [Future Improvements](#14-future-improvements)
15. [Sprint Scope](#15-sprint-scope)

---

## 1. Tech Stack

| Layer | Technology | Version | Purpose |
|---|---|---|---|
| Language | Python | 3.12+ | Async-native; best AI/ML ecosystem |
| Web framework | FastAPI | Latest | Async, auto-generated OpenAPI, DI container |
| ORM | SQLAlchemy (async) | 2.x | Type-safe queries, pgvector support |
| Migrations | Alembic | Latest | Forward-only schema versioning |
| Validation | Pydantic | 2.x | Request/response schemas |
| Task queue | Celery | 5.x | Async background jobs |
| Message broker | RabbitMQ | 3.13 | Celery task broker (AMQP) |
| Cache / results | Redis | 7.x | Celery result backend, session store, rate limiting |
| Database | PostgreSQL | 16 | Primary data store |
| Vector search | pgvector | Latest | HNSW index for RAG embeddings inside Postgres |
| AI abstraction | LiteLLM | Latest | Unified interface to multiple LLM providers |
| Transcription | OpenAI Whisper | API | Audio-to-VTT caption generation |
| Video hosting | Mux / Cloudflare Stream | — | HLS adaptive bitrate, webhook delivery |
| Storage | S3 / Cloudflare R2 | — | Files, certificates, VTT captions |
| Payments | Stripe | — | Checkout, webhooks, refunds |
| Package manager | uv | Latest | Fast, deterministic Python dependency management |
| Linting | Ruff | Latest | Linting + formatting |
| Type checking | mypy | Latest | Static type analysis |
| Testing | pytest + pytest-asyncio | Latest | Unit and integration tests |
| HTTP mocking | respx | Latest | Mock external HTTP calls in tests |
| Containerization | Docker + Compose | — | Dev parity with production |

---

## 2. System Design

### High-Level Architecture

```mermaid
graph TD
    subgraph Clients
        WEB["Web (React + Vite)"]
        MOB["Mobile (Expo)"]
    end

    subgraph API ["FastAPI — /api/v1/"]
        AUTH["auth\nusers"]
        COURSES["courses\nenrollments\nquizzes\nassignments"]
        PAY["payments\ncoupons\ncertificates"]
        AI_MOD["ai\nrag"]
        VIDEO["video\nmedia"]
        ADMIN["admin"]
    end

    subgraph Data
        PG[("PostgreSQL 16\n+ pgvector")]
        REDIS[("Redis 7\n(cache / results)")]
        RABBIT[("RabbitMQ 3\n(broker)")]
        S3["S3 / R2"]
    end

    subgraph Workers ["Celery Workers"]
        TRX["Transcription"]
        FEED["AI Feedback"]
        RAG["RAG Indexing"]
        CERT["Certificate PDF"]
        EMAIL["Email Broadcast"]
    end

    subgraph External
        MUX["Mux\n(video)"]
        STRIPE["Stripe\n(payments)"]
        LLM["LiteLLM\n→ LLM provider"]
        WHISPER["Whisper\n(transcription)"]
        EMBED["Embedding model"]
    end

    WEB --> API
    MOB --> API
    API --> PG
    API --> REDIS
    API --> S3
    API -->|enqueue tasks| RABBIT
    RABBIT --> Workers
    TRX --> WHISPER
    TRX --> S3
    FEED --> LLM
    RAG --> EMBED
    RAG --> PG
    CERT --> S3
    VIDEO --> MUX
    PAY --> STRIPE
```

### Request Lifecycle

```mermaid
sequenceDiagram
    participant Client
    participant FastAPI
    participant Middleware
    participant Dependency
    participant DB
    participant Redis

    Client->>FastAPI: HTTP request
    FastAPI->>Middleware: RequestIDMiddleware (assigns request_id)
    Middleware->>Dependency: verify_token() / get_db()
    Dependency->>Redis: check session (if auth required)
    Dependency->>DB: AsyncSession pool checkout
    Dependency-->>FastAPI: (current_user, db)
    FastAPI->>DB: query / mutation
    DB-->>FastAPI: result
    FastAPI-->>Client: {"success": true, "data": {...}}
```

### Response Envelope

Every endpoint returns the same envelope shape:

```json
{
  "success": true,
  "data": { ... }
}
```

On error:

```json
{
  "success": false,
  "error": {
    "code": "ENROLLMENT_NOT_FOUND",
    "message": "Enrollment not found",
    "detail": null
  }
}
```

---

## 3. Module Structure

```
backend/
├── app/
│   ├── main.py                  # App factory, middleware, router registration
│   ├── core/
│   │   ├── exceptions.py        # AppException + global exception handlers
│   │   ├── middleware.py        # RequestIDMiddleware
│   │   ├── rbac.py              # require_role() dependency
│   │   ├── responses.py         # ok() response helper
│   │   ├── security.py          # JWT encode/decode (RS256)
│   │   ├── storage.py           # S3/R2 upload abstraction
│   │   ├── mux.py               # Mux API client
│   │   └── redis.py             # Redis connection pool
│   ├── db/
│   │   ├── session.py           # AsyncSession factory
│   │   └── models/
│   │       ├── __init__.py
│   │       ├── user.py          # User
│   │       ├── course.py        # Category, Course, Chapter, Lesson, LessonResource, LessonTranscript
│   │       ├── enrollment.py    # Enrollment, LessonProgress, UserNote, UserBookmark
│   │       ├── quiz.py          # Quiz, QuizQuestion, QuizSubmission, QuizFeedback
│   │       ├── assignment.py    # Assignment, AssignmentSubmission
│   │       ├── certificate.py   # Certificate, CertificateRequest
│   │       ├── payment.py       # Payment
│   │       ├── coupon.py        # Coupon
│   │       ├── announcement.py  # Announcement
│   │       ├── ai.py            # AIUsageLog, AIUsageBudget
│   │       ├── rag.py           # LessonChunk (pgvector)
│   │       ├── discussion.py    # DiscussionPost (lesson threads)
│   │       ├── notification.py  # Notification, NotificationPreference, NotificationDelivery
│   │       ├── session.py       # Session (token tracking)
│   │       └── oauth_account.py # OAuthAccount (Google)
│   ├── modules/
│   │   ├── auth/       # router.py · service.py · schemas.py
│   │   ├── users/
│   │   ├── courses/
│   │   ├── enrollments/
│   │   ├── quizzes/
│   │   ├── assignments/
│   │   ├── payments/
│   │   ├── coupons/
│   │   ├── certificates/
│   │   ├── video/
│   │   ├── ai/
│   │   ├── admin/
│   │   ├── discussions/
│   │   ├── notifications/
│   │   ├── media/      # stub — no endpoints yet
│   │   └── rag/        # tasks only — no router yet
│   └── worker/
│       ├── celery_app.py        # Celery configuration
│       └── email.py             # Email task stub
├── alembic/
│   ├── alembic.ini
│   └── versions/               # 16 migration files (see §15)
├── tests/
│   ├── unit/
│   └── integration/
│       └── conftest.py          # Fixtures: test DB, test client, auth headers
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

---

## 4. Database Schema

### Entity-Relationship Diagram

```mermaid
erDiagram
    User {
        uuid id PK
        string email
        string username
        string password_hash
        boolean is_verified
        string role
        timestamp created_at
        string display_name
        string avatar_url
        string bio
        string headline
    }
    Session {
        uuid id PK
        uuid user_id FK
        string token_hash
        timestamp expires_at
        boolean revoked
    }
    OAuthAccount {
        uuid id PK
        uuid user_id FK
        string provider
        string provider_user_id
    }
    Category {
        uuid id PK
        string name
        string slug
    }
    Course {
        uuid id PK
        uuid category_id FK
        string title
        string slug
        string description
        integer price_cents
        string status
        string level
        string instructor_name
    }
    Chapter {
        uuid id PK
        uuid course_id FK
        string title
        integer order
    }
    Lesson {
        uuid id PK
        uuid chapter_id FK
        string title
        string type
        integer order
        boolean is_locked
        string mux_playback_id
    }
    LessonResource {
        uuid id PK
        uuid lesson_id FK
        string title
        string file_url
    }
    LessonTranscript {
        uuid id PK
        uuid lesson_id FK
        string vtt_key
        text plain_text
        timestamp updated_at
    }
    Enrollment {
        uuid id PK
        uuid user_id FK
        uuid course_id FK
        string status
        timestamp enrolled_at
        timestamp completed_at
    }
    LessonProgress {
        uuid id PK
        uuid user_id FK
        uuid lesson_id FK
        integer watch_position_secs
        string status
    }
    UserNote {
        uuid id PK
        uuid user_id FK
        uuid lesson_id FK
        text content
    }
    UserBookmark {
        uuid id PK
        uuid user_id FK
        uuid lesson_id FK
    }
    Quiz {
        uuid id PK
        uuid lesson_id FK
        string title
        integer time_limit_secs
        integer max_attempts
        float passing_score_percent
    }
    QuizQuestion {
        uuid id PK
        uuid quiz_id FK
        string type
        text question_text
        json options
        json correct_answer
        integer order
    }
    QuizSubmission {
        uuid id PK
        uuid user_id FK
        uuid quiz_id FK
        float score_percent
        boolean is_passed
        timestamp submitted_at
    }
    QuizFeedback {
        uuid id PK
        uuid submission_id FK
        text feedback_text
        integer tokens_used
    }
    Assignment {
        uuid id PK
        uuid lesson_id FK
        string title
        json rubric
        json submission_types
        boolean re_submission_allowed
    }
    AssignmentSubmission {
        uuid id PK
        uuid user_id FK
        uuid assignment_id FK
        string status
        text student_submission
        text feedback
        float grade_score
        string grade_status
    }
    Payment {
        uuid id PK
        uuid user_id FK
        uuid course_id FK
        integer amount_cents
        string stripe_session_id
        string status
    }
    Coupon {
        uuid id PK
        string code
        string type
        float amount_value
        uuid course_id FK
        timestamp expires_at
    }
    Certificate {
        uuid id PK
        uuid user_id FK
        uuid course_id FK
        string verification_token
        string pdf_url
        timestamp issued_at
    }
    CertificateRequest {
        uuid id PK
        uuid user_id FK
        uuid course_id FK
        string status
        uuid reviewed_by FK
    }
    Announcement {
        uuid id PK
        string title
        text content
        uuid created_by FK
        timestamp scheduled_for
        string target_audience
    }
    AIUsageLog {
        uuid id PK
        uuid course_id FK
        string feature_type
        string model
        integer input_tokens
        integer output_tokens
        integer cost_cents
    }
    AIUsageBudget {
        uuid id PK
        uuid course_id FK
        integer monthly_budget_cents
        string month
        integer used_cents
        timestamp alerted_at_80_percent
    }
    LessonChunk {
        uuid id PK
        uuid lesson_id FK
        text chunk_text
        vector embedding
        integer chunk_order
    }
    DiscussionPost {
        uuid id PK
        uuid lesson_id FK
        uuid author_id FK
        uuid parent_id FK
        text body
        timestamp deleted_at
        timestamp edited_at
        timestamp created_at
        timestamp updated_at
    }
    Notification {
        uuid id PK
        uuid recipient_id FK
        string type
        string title
        text body
        string actor_summary
        string target_url
        json event_metadata
        timestamp read_at
        timestamp created_at
    }
    NotificationPreference {
        uuid id PK
        uuid user_id FK
        string notification_type
        boolean in_app_enabled
        boolean email_enabled
        timestamp created_at
        timestamp updated_at
    }

    User ||--o{ Session : has
    User ||--o{ OAuthAccount : has
    User ||--o{ Enrollment : has
    User ||--o{ LessonProgress : has
    User ||--o{ UserNote : has
    User ||--o{ UserBookmark : has
    User ||--o{ QuizSubmission : has
    User ||--o{ AssignmentSubmission : has
    User ||--o{ Payment : has
    User ||--o{ Certificate : has
    User ||--o{ CertificateRequest : has
    User ||--o{ Notification : receives
    User ||--o{ NotificationPreference : configures
    Course ||--o{ Chapter : has
    Course ||--o{ Enrollment : has
    Course ||--o{ Payment : has
    Course ||--o{ Certificate : has
    Course ||--o{ CertificateRequest : has
    Course ||--o{ AIUsageLog : has
    Course ||--o{ AIUsageBudget : has
    Course }o--|| Category : "belongs to"
    Chapter ||--o{ Lesson : has
    Lesson ||--o{ LessonResource : has
    Lesson ||--o{ LessonTranscript : has
    Lesson ||--o{ LessonProgress : has
    Lesson ||--o{ UserNote : has
    Lesson ||--o{ UserBookmark : has
    Lesson ||--|| Quiz : has
    Lesson ||--|| Assignment : has
    Lesson ||--o{ LessonChunk : has
    Lesson ||--o{ DiscussionPost : has
    DiscussionPost }o--o| DiscussionPost : "replies to"
    DiscussionPost }o--|| User : "authored by"
    Quiz ||--o{ QuizQuestion : has
    Quiz ||--o{ QuizSubmission : has
    QuizSubmission ||--o{ QuizFeedback : has
    Assignment ||--o{ AssignmentSubmission : has
    Coupon }o--o| Course : "scoped to"
```

### Key Design Patterns

- **Soft deletes** — `is_deleted` + `deleted_at` on transactional tables for audit trails.
- **Forward-only progress** — `lesson_progress.status = completed` cannot be reverted; ensures integrity of completion logic.
- **Idempotent submissions** — Duplicate quiz/assignment submissions are rejected by unique constraints.
- **Timestamps everywhere** — `created_at` + `updated_at` on all tables.
- **HNSW index on `lesson_chunks.embedding`** — Approximate nearest-neighbor search via pgvector's HNSW index for sub-millisecond RAG retrieval.

---

## 5. API Endpoints

All endpoints are prefixed `/api/v1/`. Authenticated endpoints require `Authorization: Bearer <access_token>`.

### Auth — `/auth`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/register` | Public | Register with email, unique `username`, password, and display name |
| POST | `/auth/resend-verification` | Public | Resend verification email |
| GET | `/auth/verify-email/{token}` | Public | Verify email address |
| POST | `/auth/login` | Public | Login; returns access token + sets refresh cookie |
| POST | `/auth/refresh` | Cookie | Rotate refresh token; returns new access token |
| POST | `/auth/logout` | JWT | Revoke current session |
| POST | `/auth/forgot-password` | Public | Request password reset email |
| POST | `/auth/reset-password/{token}` | Public | Reset password with token |
| GET | `/auth/google` | Public | Initiate Google OAuth2 flow |
| GET | `/auth/google/callback` | Public | OAuth2 callback; issues JWT + refresh cookie |

### Users — `/users`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/users/me` | JWT | Get current user profile |
| PATCH | `/users/me` | JWT | Update editable profile fields; `username` is not currently editable |
| GET | `/users/me/sessions` | JWT | List active sessions |
| DELETE | `/users/me/sessions/{session_id}` | JWT | Revoke a specific session |

### Courses — `/courses`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/categories` | Public | List all categories |
| GET | `/courses` | Public | List published courses (filter: category, level, price) |
| GET | `/courses/{slug}` | Public | Course detail with chapters + lessons |
| GET | `/search` | Public | Full-text search across courses |

### Enrollments & Progress

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/courses/{course_id}/enroll` | JWT | Enroll in a course |
| DELETE | `/enrollments/{enrollment_id}` | JWT | Unenroll |
| GET | `/users/me/enrollments` | JWT | List all of the student's enrollments |
| POST | `/lessons/{lesson_id}/progress` | JWT | Save lesson progress (watch position + status; idempotent) |
| GET | `/courses/{course_id}/progress` | JWT | Get full course progress for current user |
| GET | `/users/me/continue` | JWT | Next incomplete lesson per enrolled course |
| GET | `/users/me/notes` | JWT | All notes across all enrolled courses |
| POST | `/lessons/{lesson_id}/notes` | JWT | Create or update note on a lesson |
| GET | `/lessons/{lesson_id}/notes` | JWT | Get note for a specific lesson |
| DELETE | `/lessons/{lesson_id}/notes` | JWT | Delete note |
| POST | `/lessons/{lesson_id}/bookmark` | JWT | Toggle bookmark (creates if absent, removes if present) |
| GET | `/users/me/bookmarks` | JWT | List all bookmarked lessons |

### Quizzes — `/quizzes`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/quizzes/by-lesson/{lesson_id}` | JWT | Get quiz for a lesson |
| GET | `/quizzes/{quiz_id}` | JWT | Get quiz with questions (correct answers masked until attempts exhausted) |
| POST | `/quizzes/{quiz_id}/submit` | JWT | Submit quiz answers; triggers AI feedback task |
| GET | `/quizzes/{quiz_id}/submissions` | JWT | List all of the student's submissions for a quiz |
| GET | `/quizzes/submissions/{submission_id}` | JWT | Get a single submission result + AI feedback |

### Assignments — `/assignments`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/assignments/by-lesson/{lesson_id}` | JWT | Get assignment for a lesson |
| GET | `/assignments/{assignment_id}` | JWT | Get assignment details + rubric |
| POST | `/assignments/{assignment_id}/upload` | JWT | Request a presigned R2 PUT URL; creates submission row |
| POST | `/assignments/submissions/{submission_id}/confirm` | JWT | Stamp `submitted_at` after direct R2 upload completes |
| GET | `/assignments/{assignment_id}/submissions` | JWT | List the student's submissions for an assignment |

### Payments — `/payments`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/payments/checkout` | JWT | Create Stripe Checkout session |
| POST | `/payments/webhook` | Unsigned | Stripe webhook receiver (HMAC signature-verified) |
| GET | `/users/me/payments` | JWT | Payment history for the current student |

### Coupons — `/coupons`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/coupons/validate` | JWT | Validate a discount code; returns final price |

### Certificates — `/certificates`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/certificates/generate` | JWT | Trigger certificate issuance for a completed course |
| GET | `/certificates` | JWT | List all certificates earned by the current student |
| GET | `/verify/{token}` | Public | Public certificate verification by token |
| POST | `/certificate-requests` | JWT | Submit a manual certificate review request |

### Video & Transcripts

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/webhooks/mux` | Unsigned | Mux webhook receiver (HMAC signature-verified); triggers transcription task |
| GET | `/lessons/{lesson_id}/transcript` | JWT | Get transcript (VTT URL + plain text) for a lesson |
| PATCH | `/lessons/{lesson_id}/transcript` | JWT + Admin | Edit plain-text transcript; regenerates VTT + re-triggers RAG indexing |

### AI — `/ai`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/ai/admin/ai/config/{course_id}` | JWT + Admin | Get AI config for a course (returns platform defaults if unconfigured) |
| PATCH | `/ai/admin/ai/config/{course_id}` | JWT + Admin | Create or update AI config (model, tone, prompt override, monthly budget) |

### Course Assistant — `/courses`, `/assistant`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/courses/{course_id}/assistant` | JWT | Ask the course assistant a question; creates or continues the student's conversation for this course |
| GET | `/assistant/conversations/{conversation_id}/stream` | JWT | Stream an assistant response token-by-token via SSE; emits `token`, `citations`, and `done` events |
| GET | `/assistant/conversations` | JWT | List the student's conversations, optionally filtered by `?course_id=` |

### Discussions — `/lessons`, `/discussions`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/lessons/{lesson_id}/discussions` | JWT | Create a top-level post or reply in a lesson's thread |
| GET | `/lessons/{lesson_id}/discussions` | JWT | Paginated thread fetch; `?parent_id=` for replies, `?cursor=` for next page; includes `upvote_count` and `viewer_has_upvoted` per post |
| PATCH | `/discussions/{post_id}` | JWT | Edit post body (own posts only; admins may edit any post) |
| DELETE | `/discussions/{post_id}` | JWT | Soft-delete post; body replaced with tombstone, replies preserved |
| POST | `/discussions/{post_id}/upvote` | JWT | Toggle upvote on/off; authors cannot vote on their own posts |
| POST | `/discussions/{post_id}/flag` | JWT | Create or update an open moderation flag (reason + optional context); authors cannot flag their own posts |

### Notifications — `/notifications`, `/notification-prefs`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/notifications` | JWT | Current user's in-app notification feed, newest-first; supports `?cursor=` and `?limit=`, and returns `meta.unread_count` |
| POST | `/notifications/read-all` | JWT | Mark all unread notifications for the current user as read |
| PATCH | `/notification-prefs` | JWT | Partially update per-type channel preferences for `in_app` and `email` |

### Admin — `/admin`

**User management:**

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/admin/users` | JWT + Admin | List all users |
| PATCH | `/admin/users/{user_id}/role` | JWT + Admin | Promote or demote a user's role |
| DELETE | `/admin/users/{user_id}` | JWT + Admin | Delete a user |

**Course & content management:**

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/admin/courses` | JWT + Admin | Create a course |
| PATCH | `/admin/courses/{course_id}` | JWT + Admin | Update course metadata |
| DELETE | `/admin/courses/{course_id}` | JWT + Admin | Soft-delete a course |
| POST | `/admin/courses/{course_id}/chapters` | JWT + Admin | Create a chapter |
| PATCH | `/admin/chapters/{chapter_id}` | JWT + Admin | Update a chapter |
| DELETE | `/admin/chapters/{chapter_id}` | JWT + Admin | Delete a chapter |
| PATCH | `/admin/courses/{course_id}/chapters/reorder` | JWT + Admin | Update chapter positions |
| POST | `/admin/chapters/{chapter_id}/lessons` | JWT + Admin | Create a lesson |
| PATCH | `/admin/lessons/{lesson_id}` | JWT + Admin | Update a lesson |
| DELETE | `/admin/lessons/{lesson_id}` | JWT + Admin | Delete a lesson |
| PATCH | `/admin/chapters/{chapter_id}/lessons/reorder` | JWT + Admin | Update lesson positions |
| POST | `/admin/lessons/{lesson_id}/video` | JWT + Admin | Initiate Mux video upload for a lesson |
| POST | `/admin/lessons/{lesson_id}/resources` | JWT + Admin | Attach a downloadable resource to a lesson |
| POST | `/admin/quizzes` | JWT + Admin | Create a quiz with questions |
| POST | `/admin/assignments` | JWT + Admin | Create an assignment |

**Grading:**

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/admin/courses/{course_id}/submissions` | JWT + Admin | Paginated grading queue |
| PATCH | `/admin/submissions/{submission_id}/grade` | JWT + Admin | Save grade + feedback (draft or published) |
| POST | `/admin/submissions/{submission_id}/reopen` | JWT + Admin | Reopen a submission for resubmission |

**Billing:**

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/admin/coupons` | JWT + Admin | Create a coupon |
| GET | `/admin/coupons` | JWT + Admin | List all coupons with usage stats |
| PATCH | `/admin/coupons/{coupon_id}` | JWT + Admin | Update a coupon |
| DELETE | `/admin/coupons/{coupon_id}` | JWT + Admin | Delete a coupon |
| GET | `/admin/payments` | JWT + Admin | Paginated payment history across all students |
| POST | `/admin/payments/{payment_id}/refund` | JWT + Admin | Issue a Stripe refund |

**Analytics & communications:**

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/admin/courses/{course_id}/analytics` | JWT + Admin | Course engagement analytics |
| GET | `/admin/courses/{course_id}/students` | JWT + Admin | Enrolled student progress table |
| GET | `/admin/analytics/platform` | JWT + Admin | Platform-wide analytics |
| POST | `/admin/announcements` | JWT + Admin | Create + schedule an announcement |
| GET | `/admin/announcements` | JWT + Admin | List announcements |

**Discussion moderation:**

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/admin/moderation/flags` | JWT + Admin | Paginated flagged-post queue; filterable by `?status=` (default `open`), `?reason=`, `?cursor=` |
| POST | `/admin/moderation/flags/{flag_id}/resolve` | JWT + Admin | Resolve a flag with outcome `dismissed`, `content_removed`, or `warned`; `content_removed` auto-soft-deletes the post |

---

## 6. Authentication & Security

### JWT Flow

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant DB
    participant Redis

    Client->>API: POST /auth/login {email, password}
    API->>DB: fetch user by email
    DB-->>API: User record
    API->>API: bcrypt.verify(password, hash)
    API->>DB: create Session record (token_hash, expires_at)
    API-->>Client: access_token (15 min) + Set-Cookie: refresh_token (30 days, httpOnly)

    Note over Client,API: Subsequent requests

    Client->>API: GET /users/me + Authorization: Bearer <access_token>
    API->>API: RS256 verify(access_token)
    API->>Redis: check session_id not revoked
    Redis-->>API: ok
    API-->>Client: user data

    Note over Client,API: Token refresh

    Client->>API: POST /auth/refresh (sends refresh cookie)
    API->>DB: validate Session (not revoked, not expired)
    API-->>Client: new access_token
```

### Key security properties

- **RS256 (asymmetric)** — Private key signs tokens; public key verifies. The public key can be distributed to other services without exposing signing capability.
- **httpOnly refresh cookie** — Refresh token is never accessible to JavaScript; eliminates XSS token theft.
- **Session table** — Revocation is explicit. `POST /auth/logout` marks the session as revoked in the DB. Compromised tokens can be invalidated without rotating the key pair.
- **RBAC** — `require_role(Role.ADMIN)` FastAPI dependency. Role is encoded in the JWT and verified server-side on every request.
- **Webhook signature verification** — Both Stripe and Mux webhooks are verified using HMAC signatures before any processing occurs.
- **Password hashing** — bcrypt with a work factor appropriate for the hardware.

### OAuth2 (Google)

The OAuth2 flow uses a standard redirect-based PKCE flow. On callback, the backend upserts an `OAuthAccount` record linked to the user and issues the same JWT + refresh cookie pair as email login.

---

## 7. Background Jobs

All async work is handled by Celery 5 with RabbitMQ as the message broker and Redis as the result backend.

```mermaid
graph TD
    subgraph Triggers
        MUX_HOOK["Mux webhook\n(video.asset.ready)"]
        QUIZ_SUB["Quiz submission"]
        ASSIGN_SUB["Assignment submission"]
        LESSON_EDIT["Lesson content mutation"]
        CERT_REQ["Certificate request"]
        ANNOUNCE["Admin announcement"]
    end

    subgraph Tasks
        TRX["transcribe_video\n• extract audio (ffmpeg)\n• Whisper API → VTT\n• upload VTT to R2\n• update LessonTranscript"]
        FEED_Q["generate_quiz_feedback\n• fetch submission + answers\n• LiteLLM → LLM\n• save QuizFeedback\n• log AIUsageLog"]
        FEED_A["generate_assignment_feedback\n• fetch submission + rubric\n• LiteLLM → LLM\n• update AssignmentSubmission\n• log AIUsageLog"]
        RAG["index_lesson_chunks\n• chunk lesson content\n• batch embed (embedding model)\n• upsert LessonChunk (pgvector)"]
        CERT["generate_certificate_pdf\n• render PDF template\n• upload to R2\n• update Certificate record"]
        EMAIL["broadcast_announcement\n• resolve target audience\n• queue per-recipient emails"]
    end

    MUX_HOOK --> TRX
    QUIZ_SUB --> FEED_Q
    ASSIGN_SUB --> FEED_A
    LESSON_EDIT --> RAG
    CERT_REQ --> CERT
    ANNOUNCE --> EMAIL
```

**Retry policy:** All tasks use Celery's exponential-backoff retry with a configurable max retry count. Failed tasks are visible in the Celery task queue; a dead-letter queue is planned for Phase 5.

---

## 8. AI Features

### AI Feedback (Quizzes & Assignments)

When a student submits a short-answer quiz or assignment, the API immediately returns a success response and enqueues an async feedback task. The task calls the configured LLM via LiteLLM with the submission content, the rubric (for assignments), and a per-course system prompt override (if set). The resulting feedback is saved and available on the next poll of the submission endpoint.

**Per-course configuration** (via `/ai/admin/config/{course_id}`):
- Model override (default: configured via LiteLLM)
- Feedback tone (encouraging / neutral / critical)
- Custom system prompt prefix
- Monthly token budget with 80% alert threshold

### Whisper Transcription

When Mux signals that a video asset is ready (`video.asset.ready` webhook), the backend enqueues `transcribe_video`. The worker downloads the audio track, sends it to the OpenAI Whisper API, receives a WebVTT transcript, uploads the VTT file to R2, and creates a `LessonTranscript` record. Admins can then edit the transcript via `PATCH /transcripts/{lesson_id}`.

### RAG Course Assistant (Sprint 9)

**Indexing:** On any lesson content mutation, `index_lesson_chunks` is triggered. The task chunks the lesson text, embeds each chunk using the configured embedding model, and upserts into the `lesson_chunks` table (pgvector, 1536-dimensional HNSW index).

**Retrieval (Sprint 9A — complete):** When a student queries the course assistant, the backend embeds the query, performs a cosine ANN search against `lesson_chunks` scoped strictly to the enrolled course, retrieves the top-5 chunks, and constructs a context-augmented prompt via a Jinja2 template. The complete response is returned as JSON. Conversation history (last 8 turns) is included for multi-turn context. Rate-limited to 20 queries per student per hour per course via a Redis rolling-window counter.

**Streaming (Sprint 9B — complete):** LLM responses stream token-by-token via SSE (`EventSourceResponse` from `sse-starlette`). Each `data:` event carries `{"token": "..."}`. After the model finishes, a `citations` event delivers a JSON array of deduplicated source lessons, followed by a terminal `done` event. Both message turns are committed atomically after the stream closes.

---

## 9. Environment Variables

Copy `.env.example` to `.env` for local development.

| Variable | Required | Description | Example |
|---|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL async connection string | `postgresql+asyncpg://user:pass@localhost/xoxoedu` |
| `REDIS_URL` | Yes | Redis connection string | `redis://localhost:6379/0` |
| `JWT_PRIVATE_KEY` | Yes | RS256 private key (PEM, base64-encoded) | — |
| `JWT_PUBLIC_KEY` | Yes | RS256 public key (PEM, base64-encoded) | — |
| `JWT_ALGORITHM` | No | Default: `RS256` | `RS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | Default: `15` | `15` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | Default: `30` | `30` |
| `GOOGLE_CLIENT_ID` | Yes (OAuth) | Google OAuth2 app client ID | — |
| `GOOGLE_CLIENT_SECRET` | Yes (OAuth) | Google OAuth2 app client secret | — |
| `GOOGLE_REDIRECT_URI` | Yes (OAuth) | OAuth2 callback URL | `http://localhost:8000/api/v1/auth/oauth/google/callback` |
| `STRIPE_SECRET_KEY` | Yes (payments) | Stripe secret key | `sk_test_…` |
| `STRIPE_WEBHOOK_SECRET` | Yes (payments) | Stripe webhook signing secret | `whsec_…` |
| `MUX_TOKEN_ID` | Yes (video) | Mux API token ID | — |
| `MUX_TOKEN_SECRET` | Yes (video) | Mux API token secret | — |
| `MUX_WEBHOOK_SECRET` | Yes (video) | Mux webhook signing secret | — |
| `S3_ENDPOINT_URL` | Yes | S3 or R2 endpoint | `http://localhost:9000` (MinIO locally) |
| `S3_ACCESS_KEY_ID` | Yes | S3/R2 access key | — |
| `S3_SECRET_ACCESS_KEY` | Yes | S3/R2 secret key | — |
| `S3_BUCKET_NAME` | Yes | Default storage bucket name | `xoxoedu` |
| `LITELLM_MODEL` | Yes (AI) | Default LLM model identifier | `gemini/gemini-2.0-flash` |
| `LITELLM_API_KEY` | Yes (AI) | API key for the configured LLM provider | — |
| `OPENAI_API_KEY` | Yes (Whisper/embed) | OpenAI API key for Whisper + embeddings | `sk-…` |
| `EMBEDDING_MODEL` | No | Embedding model identifier | `text-embedding-3-small` |
| `CELERY_BROKER_URL` | Yes (prod) | Celery broker URL; falls back to `REDIS_URL` in local dev | `amqp://user:pass@rabbitmq:5672//` |
| `CORS_ORIGINS` | No | Comma-separated allowed origins | `http://localhost:5173` |
| `DEBUG` | No | Enable debug mode | `false` |

---

## 10. Testing

### Setup

Integration tests require the full Docker Compose stack. Since `docker compose up` starts everything (PostgreSQL, Redis, MinIO, API, worker), bring up just the infrastructure services for testing:

```bash
docker compose up -d db redis minio
uv run alembic upgrade head
```

### Running tests

```bash
# All tests
uv run pytest

# Unit tests only (no Docker required)
uv run pytest tests/unit/

# Integration tests
uv run pytest tests/integration/

# With coverage
uv run pytest --cov=app --cov-report=html

# Specific module
uv run pytest tests/integration/test_video_transcription.py
```

### Test structure

- **Unit tests** (`tests/unit/`) — Test models and service functions in isolation. External HTTP calls are mocked with `respx`. No database required.
- **Integration tests** (`tests/integration/`) — Spin up a real test database, run migrations, exercise full request/response cycles via the FastAPI `TestClient`. Auth fixtures in `conftest.py` provide pre-authenticated student and admin headers.

### Test conventions

- One test file per module (e.g., `test_auth.py`, `test_quizzes.py`)
- Fixtures are in `conftest.py` and scoped to the session or function as appropriate
- Database state is reset between test functions using transaction rollback
- Celery tasks are patched in integration tests to prevent real external calls

---

## 11. Deployment

### Docker

The `Dockerfile` builds a single image used for both the API server (`api` service) and the Celery worker (`worker` service) — the only difference is the `command` override in `docker-compose.yml`. `docker compose up` starts the full stack: PostgreSQL, Redis, MinIO (with bucket auto-creation), the API server, and the worker.

```bash
# Start everything
docker compose up -d

# Run migrations (required on first run and after schema changes)
uv run alembic upgrade head

# View logs
docker compose logs -f api
docker compose logs -f worker

# Rebuild after code changes
docker compose up -d --build
```

### Production checklist

1. Set all required environment variables (see §9).
2. Generate RS256 key pair and store securely (never commit).
3. Run `alembic upgrade head` before deploying new code.
4. Deploy at least one Celery worker alongside the API.
5. Configure Stripe + Mux webhook URLs to point at the production API.
6. Set `CORS_ORIGINS` to the production web domain.
7. Enable HTTPS at the load balancer / reverse proxy layer.
8. Set up a PostgreSQL connection pool (PgBouncer recommended for high concurrency).

### Migrations

Alembic migrations are forward-only. Never edit a migration after it has been applied to any environment.

Sprint 10C adds `0015_notification_core`, which backfills `users.username` and creates
`notifications` plus `notification_prefs`. Existing local databases must be upgraded to
`head` before running the API after this sprint.

Sprint 10D adds `0016_notification_deliveries`, which records per-notification delivery
state for email enqueue/send attempts, opt-outs, and failure troubleshooting.

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Create a new migration (autogenerate from model diff)
uv run alembic revision --autogenerate -m "describe the change"

# Rollback one step (dev only)
uv run alembic downgrade -1
```

---

## 12. Trade-offs & Design Decisions

### PostgreSQL + pgvector instead of a dedicated vector database

**Decision:** Store lesson embeddings in a `lesson_chunks` table with a pgvector HNSW index rather than using a dedicated vector database (Pinecone, Weaviate, Qdrant).

**Why:** The RAG use case is scoped — only lesson content for enrolled courses is retrieved. At the scale of a single LMS (thousands to low millions of chunks), pgvector with an HNSW index delivers sub-millisecond ANN search without introducing a second database to operate, back up, and keep in sync. If the embedding corpus grows to tens of millions of records or requires hybrid search with heavy filtering, a dedicated vector DB becomes worth the operational cost.

### LiteLLM instead of direct provider SDKs

**Decision:** All LLM calls go through LiteLLM rather than calling Anthropic, Google, or OpenAI SDKs directly.

**Why:** Provides a single interface to swap models at the course level or globally without code changes. Enables fallback routing (e.g., fall back to a cheaper model if the primary is rate-limited) and unified cost tracking. The abstraction cost is minimal; LiteLLM is a thin proxy.

### Celery + Redis instead of FastAPI BackgroundTasks

**Decision:** Async jobs (transcription, AI feedback, RAG indexing, email) use Celery rather than FastAPI's built-in `BackgroundTasks`.

**Why:** FastAPI `BackgroundTasks` run in the same process as the API server. They are lost on restart, cannot be retried, cannot be distributed across workers, and block the event loop under CPU-bound load. Celery tasks are durable (RabbitMQ-brokered, Redis result-backend), retryable with exponential backoff, distributable across as many workers as needed, and observable via task inspection tools.

### RS256 (asymmetric JWT) instead of HS256

**Decision:** JWTs are signed with an RS256 key pair rather than a shared HMAC secret.

**Why:** With HS256, any service that verifies tokens must also hold the secret, which means it could also issue tokens. RS256 separates signing (private key, API only) from verification (public key, distributable). This matters when adding other services (e.g., a mobile push gateway, a CDN edge function) that need to verify tokens without being able to forge them.

### Monolith with module boundaries first

**Decision:** Core, AI, and Media are modules in one deployable FastAPI app, not separate services.

**Why:** The operational complexity of microservices (service discovery, inter-service auth, distributed tracing, deployment coordination) is not justified until traffic actually demands it. The module boundaries (`app/modules/`) are enforced at the code level; splitting into services later requires extracting a module and adding an HTTP or gRPC interface, which is a well-defined operation.

---

## 13. Scalability

### What scales horizontally today

- **API servers** — Stateless. Add instances behind a load balancer; all state is in PostgreSQL and Redis.
- **Celery workers** — Independent processes. Scale by adding worker instances. Workers can be specialized by queue (e.g., a GPU-heavy transcription queue vs. a lightweight email queue).

### Bottlenecks to address at scale

| Bottleneck | Mitigation |
|---|---|
| PostgreSQL write throughput | Read replicas for read-heavy queries; PgBouncer for connection pooling |
| Vector search at tens of millions of chunks | Partition `lesson_chunks` by course; consider dedicated vector DB |
| Celery task fan-out for announcements | Batch email dispatch; rate-limit outbound email |
| Large file uploads to S3 | Issue pre-signed S3 URLs and upload directly from the client; API never proxies file bytes |
| JWT validation on every request | Cache public key in memory; Redis for revocation lookup (already done) |

### Planned horizontal split (when needed)

The module boundary pattern means AI and Media modules can be extracted into separate services with minimal disruption. The split would be driven by:
- AI tasks consuming enough CPU/memory to starve the Core API
- Media processing (transcription) requiring GPU workers
- Independent deployment cadence requirements

---

## 14. Future Improvements

| Area | Improvement |
|---|---|
| **RAG** | Citation extraction with source links; multi-turn conversation memory; scope enforcement (only answer from enrolled course content) |
| **AI** | Streaming AI feedback (SSE) for assignments; AI-generated course summaries; adaptive quiz difficulty |
| **Observability** | OpenTelemetry traces + spans; Sentry error tracking; Prometheus metrics endpoint; structured JSON logging |
| **Security** | Security audit (OWASP top 10); rate limiting per endpoint; IP-based suspicious login detection; GDPR data export/deletion |
| **Testing** | Load testing with k6; chaos testing for Celery worker failure scenarios; contract tests against OpenAPI schema |
| **Real-time** | Notification SSE/push delivery; live session support (WebRTC or third-party) |
| **Social** | Peer review for assignments |
| **Code exercises** | Sandboxed code execution (Docker or WASM runtime) for programming courses |
| **Batches / cohorts** | Group enrollments, cohort progress dashboards, batch-scoped announcements |
| **Calendar** | iCal export for live sessions; reminder notifications |
| **Media library** | Admin-side asset management (reuse videos/docs across courses) |
| **Mobile API** | Push notification delivery (APNs / FCM); device token registration endpoint |

---

## 15. Sprint Scope

> Sprint length: 2 weeks. Each sprint delivers working, tested, deployable software — not just code.

---

### Phase 1 — Foundation ✅

#### Sprint 1 — Project Bootstrap & Auth ✅

**Goal:** A working, deployable API with authentication; CI running.

**Backend:**
- [x] Initialize FastAPI project structure (modules: `auth`, `users`, `courses`, `ai`, `media`)
- [x] Docker Compose: PostgreSQL, Redis, API service, Celery worker
- [x] Alembic configured; initial migration: `users`, `sessions`, `oauth_accounts`
- [x] `POST /api/v1/auth/register` — email + username + password registration
- [x] Email verification flow (`GET /api/v1/auth/verify-email/{token}`)
- [x] `POST /api/v1/auth/login` — returns JWT access token + sets refresh token cookie
- [x] `POST /api/v1/auth/refresh` — rotates refresh token
- [x] `POST /api/v1/auth/logout` — revokes refresh token
- [x] `POST /api/v1/auth/forgot-password` and `POST /api/v1/auth/reset-password/{token}`
- [x] RBAC middleware: role-based route guards (`require_role`)
- [x] `GET /api/v1/users/me` — return current user profile
- [x] `PATCH /api/v1/users/me` — update profile
- [x] `GET /api/v1/users/me/sessions` — list active sessions
- [x] `DELETE /api/v1/users/me/sessions/{id}` — revoke a session
- [x] `GET /api/v1/admin/users` — list all users (admin only)
- [x] `PATCH /api/v1/admin/users/{id}/role` — promote / demote a user (admin only)
- [x] `DELETE /api/v1/admin/users/{id}` — delete a user (admin only)
- [x] `scripts/create_admin.py` — seed script to bootstrap the first admin account

**Testing:**
- [x] Unit tests: token generation/validation, password hashing, permission guards
- [x] Integration tests: full auth flows (register, verify, login, refresh, logout, reset)
- [x] Integration tests: admin user management (list, promote, demote, delete, RBAC guards)
- [x] CI pipeline: GitHub Actions running `pytest` on every PR

**Infrastructure:**
- [x] GitHub Actions CI: lint (`ruff`), type check (`mypy`), test (`pytest`)
- [x] Railway deployment pipeline — API, Celery worker, Postgres, Redis

---

#### Sprint 2 — Course Structure & Content ✅

**Goal:** Admins can create courses with full content hierarchy; students can browse and view.

**Backend:**
- [x] Migrations: `categories`, `courses`, `chapters`, `lessons`, `lesson_resources`
- [x] `POST /api/v1/admin/courses` — create course (admin only)
- [x] `GET /api/v1/courses` — list published courses (filterable: category, level, price)
- [x] `GET /api/v1/courses/{slug}` — course detail with chapters and lessons
- [x] `PATCH /api/v1/admin/courses/{id}` — update course
- [x] `DELETE /api/v1/admin/courses/{id}` — soft-delete (archive)
- [x] `POST /api/v1/admin/courses/{id}/chapters` — create chapter
- [x] `PATCH /api/v1/admin/chapters/{id}` — update chapter; `DELETE /api/v1/admin/chapters/{id}`
- [x] `PATCH /api/v1/admin/courses/{id}/chapters/reorder` — update chapter positions
- [x] `POST /api/v1/admin/chapters/{id}/lessons` — create lesson
- [x] `PATCH /api/v1/admin/lessons/{id}` — update lesson; `DELETE /api/v1/admin/lessons/{id}`
- [x] `PATCH /api/v1/admin/chapters/{id}/lessons/reorder` — update lesson positions
- [x] `POST /api/v1/admin/lessons/{id}/resources` — attach resource
- [x] PostgreSQL FTS search: `GET /api/v1/search?q=...`

**Testing:**
- [x] Integration tests: full CRUD for course → chapter → lesson hierarchy
- [x] Integration tests: reorder chapters and lessons; verify positions
- [x] Integration tests: search returns correct results; non-published courses excluded

---

#### Sprint 3 — Enrollment & Progress ✅

**Goal:** Students can enroll in free courses and track their progress.

**Backend:**
- [x] Migrations: `enrollments`, `lesson_progress`, `user_notes`, `user_bookmarks`
- [x] `POST /api/v1/courses/{id}/enroll` — enroll in free course
- [x] `DELETE /api/v1/enrollments/{id}` — unenroll
- [x] `GET /api/v1/users/me/enrollments` — list student's enrollments
- [x] `POST /api/v1/lessons/{id}/progress` — save lesson progress (idempotent)
- [x] `GET /api/v1/courses/{id}/progress` — get full course progress for current user
- [x] `GET /api/v1/users/me/continue` — return the next incomplete lesson per enrolled course
- [x] `POST /api/v1/lessons/{id}/notes` — create/update personal note
- [x] `GET /api/v1/lessons/{id}/notes` — get personal note
- [x] `DELETE /api/v1/lessons/{id}/notes` — delete personal note
- [x] `POST /api/v1/lessons/{id}/bookmark` — toggle bookmark (creates if absent, removes if present)
- [x] `GET /api/v1/users/me/bookmarks` — list all bookmarks
- [x] pgweb added to Docker Compose for local DB browsing

**Testing:**
- [x] Unit tests: progress percentage calculation, enrollment eligibility, completion detection
- [x] Integration tests: enroll → mark lessons complete → course progress updates
- [x] Integration tests: unenroll + re-enroll → prior progress preserved
- [x] Integration tests: idempotency — duplicate progress saves do not create duplicate records

---

### Phase 2 — Assessment & Payments ✅

#### Sprint 4 — Quizzes & Assignments ✅

**Goal:** Students can take quizzes and submit assignments; objective quiz scoring works.

**Backend:**
- [x] Migrations: `quizzes`, `quiz_questions`, `quiz_submissions`, `assignments`, `assignment_submissions`
- [x] `POST /api/v1/admin/quizzes` — create quiz with questions (admin only)
- [x] `GET /api/v1/quizzes/{id}` — get quiz (correct answers masked until all attempts exhausted)
- [x] `POST /api/v1/quizzes/{id}/submit` — submit quiz; auto-score single-choice and multi-choice questions
- [x] `GET /api/v1/quizzes/{id}/submissions` — student's submission history
- [x] `GET /api/v1/quizzes/submissions/{id}` — single submission detail
- [x] `POST /api/v1/admin/assignments` — create assignment (admin only)
- [x] `GET /api/v1/assignments/{id}` — get assignment detail
- [x] `POST /api/v1/assignments/{id}/upload` — request presigned R2 PUT URL; creates submission row with `submitted_at=None`
- [x] `POST /api/v1/assignments/submissions/{id}/confirm` — stamp `submitted_at` after direct R2 upload completes
- [x] `GET /api/v1/assignments/{id}/submissions` — student's submission history
- [x] `assignment_submissions.scan_status` column (`pending` default) — virus scan hook deferred to Sprint 12
- [x] `app/core/storage.py` — lazy boto3 R2 client with `generate_presigned_put`

**Testing:**
- [x] Unit tests: quiz scoring (`_score_single_choice`, `_score_multi_choice`, `_score_submission`) — 13 tests
- [x] Unit tests: storage URL helpers (`get_public_url` with and without custom domain) — 3 tests
- [x] Integration tests: submit quiz → verify score → verify attempt count increments
- [x] Integration tests: correct answers NOT returned before all attempts exhausted
- [x] Integration tests: `MAX_ATTEMPTS_EXCEEDED` on N+1 submission
- [x] Integration tests: assignment file upload flow (presigned URL mocked)

---

#### Sprint 5 — Payments & Certificates ✅

**Goal:** Paid course enrollment via Stripe; certificates issued on completion.

**Backend:**
- [x] Migrations: `payments`, `coupons`, `certificates`, `certificate_requests`
- [x] `POST /api/v1/payments/checkout` — create Stripe Checkout session
- [x] `POST /api/v1/payments/webhook` — handle `checkout.session.completed` → enrollment; `charge.refunded` → enrollment status update
- [x] `POST /api/v1/coupons/validate` — validate coupon code; returns discount type, amount, and final price
- [x] `GET /api/v1/users/me/payments` — payment history for authenticated student
- [x] Certificate eligibility check hooked into `_maybe_complete_enrollment` (fires after every lesson completion)
- [x] `POST /api/v1/certificates/generate` — manually trigger certificate issuance for a completed course
- [x] Certificate PDF generation via WeasyPrint; uploaded to R2 as `certificates/<id>.pdf` (Celery task)
- [x] `GET /api/v1/certificates` — list student's certificates
- [x] `GET /api/v1/verify/{token}` — public certificate verification (no auth required)
- [x] `POST /api/v1/certificate-requests` — manual review request flow
- [x] Admin billing endpoints (A9): `POST/GET/PATCH/DELETE /api/v1/admin/coupons`, `GET /api/v1/admin/payments`, `POST /api/v1/admin/payments/{id}/refund`

**Key flows:**

```
Stripe payment
──────────────
Student → POST /payments/checkout → Backend creates Payment(pending) → Stripe Checkout session
Student pays on Stripe hosted page → Stripe fires checkout.session.completed webhook
Backend: Payment → completed, Enrollment created → student redirected to /courses/{slug}?payment=success

Coupon validation
─────────────────
POST /coupons/validate { code, course_id, original_amount_cents }
→ lookup by code → check expiry → check uses_count < max_uses → check course scope
→ { discount_type, discount_amount_cents, final_amount_cents }

Certificate issuance
────────────────────
POST /progress (status=completed) → _maybe_complete_enrollment()
→ all lessons done? → enrollment.status = completed → Certificate row created (verification_token)
→ generate_certificate_pdf.delay() → Celery: render HTML → WeasyPrint PDF → upload R2 → certificate.pdf_url set
```

**Testing:**
- [x] Unit tests: coupon discount calculation (percentage, fixed, cap at original price) — 7 tests
- [x] Unit tests: coupon validation edge cases (expired, usage exceeded, wrong course, global) — 4 tests
- [x] Integration tests: `checkout.session.completed` webhook → Payment completed, Enrollment created
- [x] Integration tests: `charge.refunded` webhook → Payment refunded, Enrollment refunded
- [x] Integration tests: invalid webhook signature → 400
- [x] Integration tests: `GET /users/me/payments` returns payment history
- [x] Integration tests: `POST /certificates/generate` issues cert for completed enrollment
- [x] Integration tests: `POST /certificates/generate` returns 422 for incomplete enrollment
- [x] Integration tests: `GET /verify/{token}` returns correct data; invalid token → 404

---

#### Sprint 6 — Admin Grading & Analytics ✅

**Goal:** Admins can grade submissions; analytics dashboard data available.

**Backend:**
- [x] `GET /api/v1/admin/courses/{id}/submissions` — paginated submission queue with filters
- [x] `PATCH /api/v1/admin/submissions/{id}/grade` — save grade + feedback (draft/published)
- [x] `POST /api/v1/admin/submissions/{id}/reopen` — allow student resubmission
- [x] `GET /api/v1/admin/courses/{id}/analytics` — completion rate, average quiz score, lesson drop-off
- [x] `GET /api/v1/admin/analytics/platform` — platform-wide metrics (admin only)
- [x] `GET /api/v1/admin/courses/{id}/students` — student progress table
- [x] Analytics: direct SQLAlchemy async aggregate queries (`func.count`, `func.avg`) — no materialized view at current scale
- [x] `POST /api/v1/admin/announcements` — create + schedule announcement (email via Celery)
- [x] `GET /api/v1/admin/announcements` — list announcements

**Testing:**
- [x] Unit tests: grade calculation, submission queue ordering
- [x] Integration tests: grade submission → `grade_published_at` set → notification enqueued
- [x] Integration tests: analytics aggregations correct with known fixture data
- [x] Integration tests: announcement sends email to all enrolled students (mocked email)

---

### Phase 3 — AI Layer 🚧

#### Sprint 7 — AI Quiz & Assignment Feedback ✅

**Goal:** Short-answer quiz questions and assignment submissions receive LLM-generated feedback.

**Backend:**
- [x] LiteLLM integration with retry logic and circuit breaker
- [x] Prompt template system (Jinja2): `quiz_feedback.j2`, `assignment_feedback.j2`
- [x] Celery task: `generate_quiz_feedback(submission_id)` — triggered post-submit
- [x] `quiz_feedback` table and storage
- [x] Celery task: `generate_assignment_feedback(submission_id)` — triggered post-submit
- [x] Text extraction from PDF (`pdfplumber`) and DOCX (`python-docx`) for file submissions
- [x] AI feedback fields in submission response DTOs
- [x] `GET /api/v1/admin/ai/config/{course_id}` — get AI config
- [x] `PATCH /api/v1/admin/ai/config/{course_id}` — update AI config (on/off, tone, system prompt, monthly budget)
- [x] Token usage logging: `ai_usage_logs` table; 80% budget alert threshold

**Testing:**
- [x] Unit tests: prompt template rendering with various inputs; rubric, question, and answer injected correctly
- [x] Unit tests: AI response parsing; malformed LLM response handling
- [x] Unit tests: token count estimation; prompt truncation when over context limit
- [x] Integration tests: submit short-answer quiz → Celery task fires → feedback stored (mocked LLM)
- [x] Integration tests: submit assignment → text extraction → Celery task fires → feedback stored (mocked LLM)
- [x] Integration tests: AI disabled per course → no feedback task enqueued

---

#### Sprint 8A — Video Transcription ✅

**Goal:** Video lessons auto-generate WebVTT captions via Whisper.

**Backend:**
- [x] Mux webhook receiver (`POST /api/v1/webhooks/mux`) with HMAC signature verification
- [x] Celery task: `transcribe_video(lesson_id)` — triggered on `video.asset.ready` webhook
- [x] ffmpeg audio extraction from Mux asset → OpenAI Whisper API → WebVTT generation → R2 upload
- [x] `lesson_transcripts` table populated; `mux_playback_id` added to `lessons`
- [x] `GET /api/v1/lessons/{id}/transcript` — return transcript (VTT + plain text)
- [x] `PATCH /api/v1/lessons/{id}/transcript` — admin edits transcript

**Testing:**
- [x] Unit tests: VTT generation from Whisper response format
- [x] Integration tests: video webhook → transcript task fires → VTT stored (mocked Whisper)

---

#### Sprint 8B — RAG Indexing ✅

**Goal:** Course content indexed as embeddings in pgvector for the RAG assistant.

**Backend:**
- [x] Migration: `lesson_chunks` table with `vector(1536)` column and HNSW index (pgvector)
- [x] Celery task: `index_lesson_chunks(lesson_id)` — triggered on all 4 lesson content-mutation paths (create, update, transcript update, delete)
- [x] Chunking strategy with configurable overlap; no orphaned sentences
- [x] Batch embedding via embedding model; upsert into `lesson_chunks` (old chunks replaced on re-index)
- [x] 341 tests passing at completion

**Testing:**
- [x] Unit tests: text chunking algorithm (correct overlap, no orphaned sentences)
- [x] Integration tests: lesson published → index task fires → chunks and embeddings stored (mocked embeddings)
- [x] Integration tests: lesson content updated → re-index fires → old chunks replaced

---

#### Sprint 9A — Conversations & Core RAG Pipeline ✅

**Goal:** Students can send a message to the course assistant and receive a complete (non-streaming) response grounded in indexed course content.

**Backend:**
- [x] Migrations: `conversations`, `conversation_messages` tables
- [x] `POST /api/v1/courses/{id}/assistant` — start or continue a conversation; returns complete JSON response
- [x] `GET /api/v1/assistant/conversations` — list student's conversations per course
- [x] RAG query pipeline: embed query → pgvector cosine ANN search (top-k, scoped to `course_id`) → build context prompt → LLM call
- [x] Conversation history: load last 8 turns; truncate oldest turns when over token limit before sending to LLM
- [x] Scope enforcement: `course_id` filter on every vector search; enrollment check gates the endpoint
- [x] Rate limiting: 20 AI queries per student per hour per course (Redis rolling-window counter)
- [x] Token usage logged to `ai_usage_logs` per message
- [x] 363 tests passing at completion

**Testing:**
- [x] Unit tests: conversation history truncation algorithm
- [x] Unit tests: scope enforcement — WHERE clause always binds correct `course_id`
- [x] Unit tests: rate limit counter increment and rejection logic
- [x] Integration tests: full RAG pipeline (mocked embeddings + mocked LLM) → response returned
- [x] Integration tests: student not enrolled → 403 on assistant endpoint
- [x] Integration tests: student of course A cannot receive results from course B chunks (boundary test)
- [x] Integration tests: rate limit enforced after 20 requests within the rolling hour window

---

#### Sprint 9B — SSE Streaming & Citations ✅

**Goal:** LLM responses stream token-by-token to the client via SSE; each response includes citations linking back to the source lesson.

**Backend:**
- [x] SSE streaming endpoint: `GET /api/v1/assistant/conversations/{id}/stream`
- [x] `LLMClient.stream()` — calls `litellm.acompletion(stream=True)`; yields content deltas; circuit breaker checked at entry
- [x] Citation extraction: `build_citations()` deduplicates retrieved chunks by `lesson_id`, preserves retrieval rank order
- [x] SSE event protocol: `data: {"token": "..."}` per delta → `event: citations` with JSON source array → `event: done`
- [x] Both message turns committed atomically after stream closes; `try/finally` guarantees `citations` + `done` events even on mid-stream error
- [x] `sse-starlette>=2.1` added as a dependency
- [x] 376 tests passing at completion

**Testing:**
- [x] Unit tests: `build_citations` — deduplication, retrieval order, missing title fallback, transcript source, empty input
- [x] Integration tests: token events arrive in correct order; concatenated text matches full response
- [x] Integration tests: `citations` event present with correct `lesson_id`
- [x] Integration tests: `done` is the final event
- [x] Integration tests: both DB message rows saved after stream completes
- [x] Integration tests: wrong-owner conversation → 404; unenrolled student → 404

---

### Phase 4 — Real-Time & Social ⏳

#### Sprint 10A — Discussion Core ✅

**Goal:** Enrolled students can create, read, edit, and soft-delete lesson-scoped discussion posts with stable pagination and ownership rules.

**Functional Requirements:**
- [x] Each lesson has a dedicated discussion thread; a post may be either a top-level thread starter or a reply to another post in the same lesson
- [x] Only authenticated, verified users with access to the lesson can read or create discussion posts for that lesson
- [x] Students can edit only their own posts; admins can view all posts and will receive moderation capabilities in Sprint 10B
- [x] Deleting a post is always a soft-delete; the post remains in-place in the thread with tombstone content so reply context is preserved
- [x] Discussion list responses include author summary, timestamps, reply metadata, and cursor pagination fields required by the client
- [x] Thread ordering is deterministic: top-level posts newest-first, replies oldest-first within each parent thread unless the client requests otherwise

**Non-Functional Requirements:**
- [x] Cursor pagination must be stable under concurrent inserts and must not skip or duplicate rows across page boundaries
- [x] All read/write authorization checks are server-enforced; no trust in client-supplied ownership or lesson access
- [x] Listing a lesson thread must avoid N+1 query patterns for author lookups and reply counts
- [x] Soft-delete behavior must be reversible only via direct DB intervention or a future moderation tool; the public API exposes no hard-delete path
- [x] Hot-path discussion queries must be index-backed on at least `lesson_id`, `parent_id`, and `created_at`
- [x] All endpoints must continue using the standard JSON envelope and existing module/router patterns already used across the API

**Backend:**
- [x] Migrations: `discussion_posts` with self-referential `parent_id`, `deleted_at`, `edited_at`, and author/lesson foreign keys
- [x] New module: `app/modules/discussions/{router,service,schemas}.py`
- [x] `POST /api/v1/lessons/{id}/discussions` — create top-level post or reply
- [x] `GET /api/v1/lessons/{id}/discussions` — paginated thread fetch with cursor metadata
- [x] `PATCH /api/v1/discussions/{id}` — edit post body (own post only)
- [x] `DELETE /api/v1/discussions/{id}` — soft-delete post and replace body with tombstone text
- [x] Include the discussions router in `app/main.py`

**Testing:**
- [x] Unit tests: cursor encoding/decoding and deterministic ordering rules
- [x] Unit tests: soft-delete content replacement and reply-preservation logic
- [x] Integration tests: enrolled student can create top-level post and reply
- [x] Integration tests: non-enrolled student cannot read or write lesson discussions
- [x] Integration tests: edit own post succeeds; edit another user's post returns 403
- [x] Integration tests: soft-delete leaves replies visible and preserves thread shape

---

#### Sprint 10B — Discussion Moderation & Social Interactions ✅

**Goal:** Discussion threads become operable at scale with voting, flagging, moderation tools, and mention parsing.

**Functional Requirements:**
- [x] Users can upvote a discussion post once; repeating the action toggles the upvote off
- [x] Users can flag a post with a reason code and optional moderator note context
- [x] Users cannot upvote or flag their own posts
- [x] Admins can review flagged posts in a moderation queue filtered by status, reason, and creation date
- [x] Admins can resolve a flag with a resolution outcome such as `dismissed`, `content_removed`, or `warned`
- [x] Post content is scanned for `@username` mentions and normalized into a structured mention list for downstream notification hooks

**Non-Functional Requirements:**
- [x] Duplicate upvotes and duplicate open flags by the same user on the same post must be prevented with DB constraints
- [x] Moderation operations must leave an audit trail including resolver, resolution timestamp, and resolution note
- [x] Mention parsing must be deterministic, case-insensitive for matching, and tolerant of punctuation boundaries
- [x] Moderation queue queries must be index-backed on `status`, `created_at`, and `post_id`
- [x] Upvote and flag endpoints must be safe under concurrent requests from the same user
- [x] Social interaction features must not change the behavior of the core thread listing contract shipped in Sprint 10A

**Backend:**
- [x] Migrations: `discussion_post_votes` and `discussion_flags`
- [x] `POST /api/v1/discussions/{id}/upvote` — toggle upvote
- [x] `POST /api/v1/discussions/{id}/flag` — create or update an open moderation flag
- [x] `GET /api/v1/admin/moderation/flags` — paginated flagged-post queue
- [x] `POST /api/v1/admin/moderation/flags/{id}/resolve` — resolve moderation item
- [x] Mention parsing utility shared by discussions and notifications
- [x] Aggregated vote counts and current-user vote state included in discussion DTOs

**Testing:**
- [x] Unit tests: mention parsing (`@username` extraction), punctuation handling, duplicate mention collapse
- [x] Unit tests: upvote toggle and duplicate-open-flag protection
- [x] Integration tests: flag post → appears in moderation queue
- [x] Integration tests: admin resolves flag → queue status updates correctly
- [x] Integration tests: author cannot upvote or flag own post
- [x] Integration tests: vote totals and current-user vote state returned correctly in thread payloads

---

#### Sprint 10C — Notification Core ✅

**Goal:** The platform stores in-app notifications and user preferences as first-class domain objects before adding delivery channels.

**Functional Requirements:**
- [x] Notification records exist for at least these event types: discussion reply, mention, grade published, certificate issued
- [x] Each notification stores recipient, type, title/body copy, actor summary, deep-link target, read state, and event metadata payload
- [x] `GET /api/v1/notifications` returns a paginated notification feed for the current user, newest-first
- [x] `GET /api/v1/notifications` also returns unread count metadata without requiring a second API call
- [x] `POST /api/v1/notifications/read-all` marks all unread notifications for the current user as read
- [x] `PATCH /api/v1/notification-prefs` updates per-type channel preferences at least for `in_app` and `email`
- [x] Discussion replies, mentions, grade publishes, and certificate issuance create persisted notifications

**Non-Functional Requirements:**
- [x] Notification creation must not block the originating request with network I/O; this sprint persists DB state only and defers delivery to Sprint 10D
- [x] Notification feed ordering must be deterministic for equal timestamps by using a secondary key such as notification ID
- [x] Unread-count queries must be index-backed on `recipient_id` and `read_at`
- [x] Preference updates must be partial and idempotent; omitted fields do not reset other preference values
- [x] Notification type names must be explicit enums so downstream email and realtime delivery cannot rely on free-form strings
- [x] The persisted notification row is the source of truth; clients must be able to rebuild state from polling alone

**Backend:**
- [x] Migrations: `users.username`, `notifications`, `notification_prefs`
- [x] New module: `app/modules/notifications/{router,service,schemas}.py`
- [x] Notification factory/helper invoked from discussion reply, mention, grade publish, and certificate issuance code paths
- [x] `GET /api/v1/notifications` — paginated list plus unread count in `meta`
- [x] `POST /api/v1/notifications/read-all` — mark all notifications read for current user
- [x] `PATCH /api/v1/notification-prefs` — update notification channel preferences
- [x] Shared enum/constants for notification types and delivery channels

**Testing:**
- [x] Unit tests: notification payload builder and enum validation
- [x] Unit tests: unread-count calculation and partial preference merge behavior
- [x] Integration tests: post reply → author receives in-app notification row
- [x] Integration tests: `@mention` in a discussion post creates a mention notification for the targeted user
- [x] Integration tests: `read-all` marks only the current user's notifications as read
- [x] Integration tests: notification feed returns correct unread count and newest-first ordering

---

#### Sprint 10D — Notification Delivery & Realtime

**Goal:** Persisted notifications are delivered through email and realtime in-app streams without changing the polling contract from Sprint 10C.

**Functional Requirements:**
- [x] Notification email tasks are enqueued for supported event types when the recipient's preference allows email delivery
- [x] Realtime in-app delivery is provided through SSE on a dedicated notification stream endpoint
- [x] The SSE stream emits only notifications belonging to the authenticated user
- [x] Clients can reconnect and continue from persisted state by combining the stream with `GET /api/v1/notifications`
- [x] Discussion reply, mention, grade published, and certificate issued are all wired as delivery-producing events by sprint end
- [x] Email templates include actor, event summary, and deep-link target back into the product

**Non-Functional Requirements:**
- [x] SSE is the primary realtime transport for Phase 4; WebSockets are explicitly deferred unless a two-way use case appears
- [x] Delivery must be at-least-once, while the notification table remains the correctness layer for eventual reconciliation
- [x] Email delivery tasks must be retryable and idempotent enough to avoid duplicate sends in the common single-retry case
- [x] Realtime delivery must degrade gracefully: if the stream is disconnected, polling still exposes the full notification history
- [x] Notification producers must not fail the originating request if downstream email delivery is temporarily unavailable
- [x] The SSE endpoint must follow the event framing conventions already established by the assistant streaming endpoint

**Backend:**
- [x] Celery tasks for `send_notification_email(notification_id)` with preference checks and duplicate-send guard
- [x] `GET /api/v1/notifications/stream` — SSE stream for realtime delivery
- [x] Redis-backed pub/sub or equivalent lightweight fanout signal to wake connected SSE listeners
- [x] Email templates for each supported notification type
- [x] `notification_deliveries` status rows for queued, sent, failed, and skipped email delivery attempts
- [x] Hook grade-published and certificate-issued flows into notification creation plus delivery

**Testing:**
- [x] Unit tests: channel preference gating and email-template rendering
- [x] Integration tests: notification prefs opt-out → email not enqueued for that type
- [x] Integration tests: SSE stream only emits notifications for the owning user
- [x] Integration tests: disconnected client can recover missed items by polling the notification list endpoint
- [x] Integration tests: grade published and certificate issued both create persisted notifications and enqueue delivery
- [x] Integration tests: delivery-task retry does not duplicate the same notification in the DB feed

---

#### Sprint 11A — Batches Core

**Goal:** Courses can be organized into cohorts with explicit membership, schedule metadata, and admin management workflows.

**Functional Requirements:**
- [ ] Admins can create, update, archive, and list batches for a course
- [ ] A batch stores title, course, timezone, start date, end date, enrollment window, capacity, and status
- [ ] Admins can add and remove students from a batch through batch enrollment records
- [ ] Students can belong to at most one active batch per course unless an explicit override is added later
- [ ] Batch membership is visible to admins and to the enrolled student through authenticated endpoints
- [ ] Batch enrollment requires an underlying course enrollment or creates one as part of the same admin workflow, depending on final policy chosen during implementation

**Non-Functional Requirements:**
- [ ] All batch dates must be stored in UTC with a separate canonical IANA timezone field for display and scheduling logic
- [ ] Capacity enforcement must be transactional so concurrent enrollment writes cannot overbook a batch
- [ ] Active-batch uniqueness per student/course must be enforced at the DB layer where practical
- [ ] Archived batches become read-only to normal management flows while remaining visible for reporting
- [ ] Batch list and membership queries must be index-backed on `course_id`, `status`, and `user_id`
- [ ] The batch model must be extensible enough to support future cohort dashboards and scoped announcements without schema churn

**Backend:**
- [ ] Migrations: `batches`, `batch_enrollments`
- [ ] New module: `app/modules/batches/{router,service,schemas}.py`
- [ ] Full CRUD for batches
- [ ] Full CRUD for batch enrollments
- [ ] Admin endpoints for listing batch members and batch summaries
- [ ] Student-facing endpoint for listing the current user's batch memberships, if needed by the frontend during this phase

**Testing:**
- [ ] Unit tests: capacity enforcement and active-batch uniqueness rules
- [ ] Unit tests: timezone normalization and batch status transition validation
- [ ] Integration tests: admin creates batch and enrolls students successfully
- [ ] Integration tests: student cannot self-enroll into a batch through admin-only endpoints
- [ ] Integration tests: archived batch rejects new membership writes
- [ ] Integration tests: user cannot be added twice to the same active batch

---

#### Sprint 11B — Live Sessions & Calendar

**Goal:** Batch-linked live sessions can be scheduled, surfaced to students, exported to iCal, and reminded automatically.

**Functional Requirements:**
- [ ] Admins can create, update, cancel, and list live sessions under a batch
- [ ] A live session stores title, description, scheduled start/end, timezone, provider, join URL, optional recording URL, and status
- [ ] `GET /api/v1/users/me/calendar` returns all upcoming sessions across the current user's enrolled batches
- [ ] `GET /api/v1/users/me/calendar.ics` exports the same upcoming sessions as a valid iCalendar feed
- [ ] Live session reminder tasks are scheduled for one hour before the session start time
- [ ] Session edits or cancellations update or suppress pending reminders as appropriate

**Non-Functional Requirements:**
- [ ] All scheduling calculations use UTC internally; timezone conversion is only for input validation and serialized output
- [ ] iCalendar output must be valid RFC 5545 and import cleanly into Google Calendar and Apple Calendar
- [ ] Reminder scheduling must be idempotent so repeated edits do not produce duplicate reminder tasks
- [ ] Calendar endpoints must return only sessions from batches the current user is authorized to see
- [ ] Canceled sessions remain queryable for admins but are excluded from normal student upcoming-session views
- [ ] Join links are treated as protected data and are never exposed through public unauthenticated endpoints

**Backend:**
- [ ] Migrations: `live_sessions`
- [ ] `POST /api/v1/batches/{id}/live-sessions` — create session
- [ ] `PATCH /api/v1/live-sessions/{id}` and `DELETE /api/v1/live-sessions/{id}` — update or cancel session
- [ ] `GET /api/v1/users/me/calendar` — aggregated upcoming-session JSON feed
- [ ] `GET /api/v1/users/me/calendar.ics` — iCal export
- [ ] Celery tasks for live-session reminders and task-rescheduling on session mutation

**Testing:**
- [ ] Unit tests: iCal generation format validity
- [ ] Unit tests: reminder scheduling and rescheduling logic
- [ ] Integration tests: create live session → reminder task scheduled at correct time
- [ ] Integration tests: session update moves the reminder to the new start time
- [ ] Integration tests: canceled session no longer appears in the student's upcoming calendar feed
- [ ] Integration tests: calendar endpoint returns only sessions from enrolled batches

---

#### Sprint 11C — Attendance & Batch Reporting

**Goal:** Live sessions become operationally complete with attendance capture and admin reporting for each cohort.

**Functional Requirements:**
- [ ] Attendance can be marked for a live session by the student, the admin, or both depending on the finalized policy; the stored status must support at least `present`, `absent`, and `late`
- [ ] `POST /api/v1/live-sessions/{id}/attendance` records or updates attendance for an authorized user
- [ ] `GET /api/v1/admin/batches/{id}/attendance` returns a batch attendance report across sessions and students
- [ ] Attendance reports include session summary totals, per-student attendance breakdown, and batch-level completion percentages
- [ ] Admins can filter attendance reports by session, student, and attendance status
- [ ] Attendance writes must remain possible after the session ends so staff can backfill missing records

**Non-Functional Requirements:**
- [ ] Only one attendance row may exist per `(session_id, user_id)` pair
- [ ] Attendance writes must be idempotent so retries or repeated check-ins do not create duplicates
- [ ] Reporting queries must be efficient enough for batches with hundreds of learners and dozens of sessions
- [ ] Attendance changes must preserve `updated_at` semantics so late backfills remain auditable
- [ ] Student-level attendance visibility must respect existing course/batch authorization boundaries
- [ ] Report responses must be shaped for direct frontend consumption without requiring N extra lookups per row

**Backend:**
- [ ] Migrations: `session_attendance`
- [ ] `POST /api/v1/live-sessions/{id}/attendance` — create/update attendance
- [ ] `GET /api/v1/admin/batches/{id}/attendance` — batch attendance report
- [ ] Attendance aggregation helpers in the batches or live-sessions service layer
- [ ] Optional CSV export is deferred; JSON reporting is the required deliverable for this sprint

**Testing:**
- [ ] Unit tests: attendance status transitions and aggregate percentage calculations
- [ ] Unit tests: idempotent upsert behavior for repeated attendance writes
- [ ] Integration tests: mark attendance twice for the same user/session updates the existing row
- [ ] Integration tests: admin attendance report matches underlying session attendance rows
- [ ] Integration tests: unauthorized user cannot mark attendance for another student's session
- [ ] Integration tests: reports correctly exclude students outside the batch

---

### Phase 5 — Platform Hardening ⏳

#### Sprint 12 — Observability, Security & Performance

**Goal:** Production-ready platform with full observability, security audit complete, performance benchmarks met.

- [ ] OpenTelemetry instrumentation on all API routes (trace ID, latency, status)
- [ ] Sentry integration (backend + web + mobile)
- [ ] Structured JSON logging with correlation IDs
- [ ] Rate limiting: per-IP (auth endpoints), per-user (AI endpoints, submission endpoints)
- [ ] Security headers: CSP, HSTS, X-Content-Type-Options, X-Frame-Options
- [ ] Dependency audit: `pip-audit` in CI; no high-severity vulnerabilities
- [ ] OWASP scan against staging environment
- [ ] Load test: 10k simulated concurrent users with k6; verify p95 < 500ms
- [ ] Database: add missing indexes; run `EXPLAIN ANALYZE` on all hot-path queries
- [ ] PgBouncer connection pooling configured
- [ ] Audit log: all admin actions write to `audit_logs`
- [ ] GDPR: `GET /api/v1/users/me/export` (data export) and `DELETE /api/v1/users/me` (account deletion)
- [ ] Virus scan: wire S3/R2 event → scanning service for `assignment_submissions`; update `scan_status` `pending` → `clean` or `quarantined` (deferred from Sprint 4)
- [ ] Full E2E test suite run against staging; all Playwright journeys green

---

### Cross-Cutting Track — Async Infrastructure Hardening

> Recommended before sustained AI/media usage or a move from roughly 100 users toward 10,000. RabbitMQ is already in use as the dedicated Celery broker; this track focuses on queue isolation, worker topology, and observability.

#### Sprint A1 — Queue Isolation & Worker Topology

**Goal:** Prevent long-running AI/media work from delaying auth email and other latency-sensitive jobs.

**Backend:**
- [ ] Define named Celery queues via `task_routes`: `critical`, `bulk_email`, `ai`, `media`, `indexing`
- [ ] Route verification and password-reset email tasks to `critical`
- [ ] Route announcement fan-out to `bulk_email`
- [ ] Route AI feedback and AI usage logging to `ai`
- [ ] Route transcript generation and certificate PDF jobs to `media`
- [ ] Route RAG indexing to `indexing`
- [ ] Split the single `worker` service into multiple worker processes in `docker-compose.yml` and production deploy config
- [ ] Assign queue-specific concurrency, prefetch, and time-limit defaults per worker pool
- [ ] Keep `critical` capacity reserved even when `media` and `ai` queues are backlogged
- [ ] Convert announcement fan-out from one task with a large recipient list into one-email-per-task or small fixed-size batches

**Reliability:**
- [ ] Audit each task for idempotency under at-least-once delivery
- [ ] Add duplicate-send guards for email and other user-visible side effects
- [ ] Set `ignore_result=True` on fire-and-forget tasks that are never polled by clients

**Testing:**
- [ ] Integration tests prove each trigger enqueues to the intended queue
- [ ] Failure test proves a long-running `media` task does not block `critical` email delivery
- [ ] Load test mixed workloads with separate worker pools and record queue wait time by queue

#### Sprint A2 — Dedicated Broker & Config Separation ✅

**Goal:** Isolate Celery transport from app-side Redis usage and remove shared-broker risk.

**Backend / Infra:**
- [x] Introduce separate `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` settings
- [x] Keep `REDIS_URL` for quota enforcement and cache/state only
- [x] Deploy RabbitMQ 3.13 as the dedicated Celery broker (AMQP via `amqp://`)
- [x] Update local Compose and env vars for API plus all worker pools
- [x] Add broker connection retry and dead-letter exchange config

**Observability:**
- [ ] Add Flower or equivalent queue dashboard in non-prod and staging
- [ ] Expose queue depth, task runtime, retry count, and publish-failure metrics
- [ ] Add alerts for `critical` queue age, repeated retries, and dead worker pools

**Testing:**
- [ ] Smoke test publish and consume across all queues after broker restarts
- [ ] Verify redelivery behavior for idempotent tasks after worker termination
- [ ] Benchmark enqueue and consume throughput under mixed `critical`, `ai`, and `media` traffic

#### Sprint A3 — Scheduling, Retries & Operational Hardening

**Goal:** Make async processing safe under retries, duplicate delivery, and higher concurrency.

**Backend:**
- [ ] Add explicit retry policies per task class: short-latency, bulk fan-out, and long-running jobs
- [ ] Add dead-letter or failed-task handling for poison messages
- [ ] Add per-task soft and hard time limits where appropriate
- [ ] Add scheduled-task support (`celery beat` or DB-backed scheduler) for reminders and delayed work
- [ ] Replace large in-message payloads with row IDs or batch IDs where possible
- [ ] Store job execution metadata for support/debugging on user-visible async flows
- [ ] Review all side-effecting tasks for safe replay semantics

**Testing:**
- [ ] Chaos tests: kill worker mid-task, restart broker, replay duplicate deliveries
- [ ] Load test a 10k-user workload profile with mixed email, AI, transcript, and indexing traffic
- [ ] Write an operational runbook for replaying failed jobs, draining queues, and scaling worker pools safely

**Acceptance criteria:**
- [ ] `critical` jobs maintain low queue wait time during transcript and indexing backlogs
- [ ] Worker pools can be scaled independently by queue without redeploying the API
- [ ] Broker or worker restarts do not create duplicate user-visible side effects in replay tests
