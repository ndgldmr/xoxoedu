import uuid

import factory

from app.core.security import hash_password
from app.db.models.user import User


class UserFactory(factory.Factory):
    class Meta:
        model = User

    id = factory.LazyFunction(uuid.uuid4)
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    password_hash = factory.LazyFunction(lambda: hash_password("testpass123"))
    role = "student"
    email_verified = True
    display_name = factory.Sequence(lambda n: f"User {n}")
