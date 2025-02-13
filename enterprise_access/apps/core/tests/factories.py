"""
Factoryboy factories.
"""
from uuid import uuid4

import factory
from faker import Faker

from enterprise_access.apps.core.models import User

USER_PASSWORD = 'password'

FAKER = Faker()


class UserFactory(factory.django.DjangoModelFactory):
    """
    Test factory for the `User` model.
    """
    id = factory.Sequence(lambda n: n + 1)
    # make this pretty random to avoid flaky tests.
    username = factory.Sequence(lambda n: f'fake-username-{n}-{str(uuid4())[:8]}')
    password = factory.PostGenerationMethodCall('set_password', USER_PASSWORD)
    email = factory.Faker('email')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    is_active = True
    is_staff = False
    is_superuser = False
    lms_user_id = factory.LazyAttribute(lambda x: FAKER.pyint())

    class Meta:
        model = User
