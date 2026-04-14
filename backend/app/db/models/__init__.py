"""Re-exports all ORM model classes for convenient single-import access."""

from app.db.models.ai import AIUsageBudget, AIUsageLog
from app.db.models.announcement import Announcement
from app.db.models.assignment import Assignment, AssignmentSubmission
from app.db.models.certificate import Certificate, CertificateRequest
from app.db.models.coupon import Coupon
from app.db.models.course import Category, Chapter, Course, Lesson, LessonResource, LessonTranscript
from app.db.models.enrollment import Enrollment, LessonProgress, UserBookmark, UserNote
from app.db.models.oauth_account import OAuthAccount
from app.db.models.payment import Payment
from app.db.models.quiz import Quiz, QuizFeedback, QuizQuestion, QuizSubmission
from app.db.models.session import Session
from app.db.models.user import User, UserProfile

__all__ = [
    "User",
    "UserProfile",
    "Session",
    "OAuthAccount",
    "Category",
    "Course",
    "Chapter",
    "Lesson",
    "LessonResource",
    "LessonTranscript",
    "Enrollment",
    "LessonProgress",
    "UserNote",
    "UserBookmark",
    "Quiz",
    "QuizFeedback",
    "QuizQuestion",
    "QuizSubmission",
    "Assignment",
    "AssignmentSubmission",
    "Payment",
    "Coupon",
    "Certificate",
    "CertificateRequest",
    "Announcement",
    "AIUsageLog",
    "AIUsageBudget",
]
