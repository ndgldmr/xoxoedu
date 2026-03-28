import uuid

import factory

from app.core.security import hash_password
from app.db.models.user import User, UserProfile


class UserProfileFactory(factory.Factory):
    class Meta:
        model = UserProfile

    user_id = factory.LazyFunction(uuid.uuid4)
    display_name = factory.Sequence(lambda n: f"User {n}")
    avatar_url = None
    bio = None
    headline = None
    social_links = None
    skills = None


class UserFactory(factory.Factory):
    class Meta:
        model = User

    id = factory.LazyFunction(uuid.uuid4)
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    password_hash = factory.LazyFunction(lambda: hash_password("testpass123"))
    role = "student"
    email_verified = True
