"""
Tests for Subsidy Access Policy Assignment Allocation view(s).
"""
from unittest import mock
from uuid import uuid4

import ddt
from django.core.cache import cache as django_cache
from rest_framework import status
from rest_framework.reverse import reverse

from enterprise_access.apps.content_assignments.constants import LearnerContentAssignmentStateChoices
from enterprise_access.apps.content_assignments.tests.factories import (
    AssignmentConfigurationFactory,
    LearnerContentAssignmentFactory
)
from enterprise_access.apps.core.constants import (
    SYSTEM_ENTERPRISE_ADMIN_ROLE,
    SYSTEM_ENTERPRISE_LEARNER_ROLE,
    SYSTEM_ENTERPRISE_OPERATOR_ROLE
)
from enterprise_access.apps.subsidy_access_policy.constants import (
    REASON_CONTENT_NOT_IN_CATALOG,
    REASON_NOT_ENOUGH_VALUE_IN_SUBSIDY,
    REASON_POLICY_EXPIRED,
    REASON_POLICY_SPEND_LIMIT_REACHED,
    REASON_SUBSIDY_EXPIRED,
    MissingSubsidyAccessReasonUserMessages
)
from enterprise_access.apps.subsidy_access_policy.models import AssignedLearnerCreditAccessPolicy
from enterprise_access.apps.subsidy_access_policy.tests.factories import AssignedLearnerCreditAccessPolicyFactory
from test_utils import APITest, APITestWithMocks

SUBSIDY_ACCESS_POLICY_LIST_ENDPOINT = reverse('api:v1:subsidy-access-policies-list')

TEST_ENTERPRISE_UUID = uuid4()
OTHER_TEST_ENTERPRISE_UUID = uuid4()


def _allocation_url(policy_uuid):
    return reverse(
        "api:v1:policy-allocation-allocate",
        kwargs={"policy_uuid": policy_uuid},
    )


@ddt.ddt
class TestSubsidyAccessPolicyAllocationView(APITestWithMocks):
    """
    Tests for the ``allocate`` view.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.enterprise_uuid = TEST_ENTERPRISE_UUID
        cls.content_key = 'course-v1:edX+edXPrivacy101+3T2020'

        # Create a pair of AssignmentConfiguration + SubsidyAccessPolicy for the main test customer.
        cls.assignment_configuration = AssignmentConfigurationFactory(
            enterprise_customer_uuid=cls.enterprise_uuid,
        )
        cls.assigned_learner_credit_policy = AssignedLearnerCreditAccessPolicyFactory(
            display_name='An assigned learner credit policy, for the test customer.',
            enterprise_customer_uuid=cls.enterprise_uuid,
            active=True,
            assignment_configuration=cls.assignment_configuration,
            spend_limit=10000 * 100,
        )

        cls.alice_assignment = LearnerContentAssignmentFactory(
            assignment_configuration=cls.assignment_configuration,
            learner_email='alice@foo.com',
            lms_user_id=None,
            content_key=cls.content_key,
            content_quantity=-123,
            state=LearnerContentAssignmentStateChoices.ERRORED,
        )
        cls.bob_assignment = LearnerContentAssignmentFactory(
            assignment_configuration=cls.assignment_configuration,
            learner_email='bob@foo.com',
            lms_user_id=None,
            content_key=cls.content_key,
            content_quantity=-456,
            state=LearnerContentAssignmentStateChoices.ALLOCATED,
        )
        cls.carol_assignment = LearnerContentAssignmentFactory(
            assignment_configuration=cls.assignment_configuration,
            learner_email='carol@foo.com',
            lms_user_id=None,
            content_key=cls.content_key,
            content_quantity=-789,
            state=LearnerContentAssignmentStateChoices.ALLOCATED,
        )

    def setUp(self):
        super().setUp()

        self.enterprise_uuid = TEST_ENTERPRISE_UUID

        self.set_jwt_cookie([{
            'system_wide_role': SYSTEM_ENTERPRISE_ADMIN_ROLE,
            'context': str(self.enterprise_uuid),
        }])
        self.addCleanup(django_cache.clear)  # clear any leftover allocation locks

    @mock.patch.object(AssignedLearnerCreditAccessPolicy, 'can_allocate', autospec=True)
    @mock.patch(
        'enterprise_access.apps.subsidy_access_policy.models.assignments_api.allocate_assignments',
        autospec=True,
    )
    def test_allocate_happy_path(self, mock_allocate, mock_can_allocate):
        """
        Tests that we can successfully call the allocate view
        and that policy-level allocation occurs.
        """
        mock_can_allocate.return_value = (True, None)
        mock_allocate.return_value = {
            'updated': [self.alice_assignment],
            'created': [self.bob_assignment],
            'no_change': [self.carol_assignment],
        }

        allocate_url = _allocation_url(self.assigned_learner_credit_policy.uuid)
        allocate_payload = {
            'learner_emails': ['alice@foo.com', 'bob@foo.com', 'carol@foo.com'],
            'content_key': self.content_key,
            'content_price_cents': 12345,
        }

        response = self.client.post(allocate_url, data=allocate_payload)

        self.assertEqual(status.HTTP_202_ACCEPTED, response.status_code)
        expected_response_payload = {
            'updated': [
                {
                    'assignment_configuration': str(self.assignment_configuration.uuid),
                    'learner_email': 'alice@foo.com',
                    'lms_user_id': None,
                    'content_key': self.content_key,
                    'content_quantity': -123,
                    'last_notification_at': None,
                    'state': LearnerContentAssignmentStateChoices.ERRORED,
                    'transaction_uuid': None,
                    'uuid': str(self.alice_assignment.uuid),
                },
            ],
            'created': [
                {
                    'assignment_configuration': str(self.assignment_configuration.uuid),
                    'learner_email': 'bob@foo.com',
                    'lms_user_id': None,
                    'content_key': self.content_key,
                    'content_quantity': -456,
                    'last_notification_at': None,
                    'state': LearnerContentAssignmentStateChoices.ALLOCATED,
                    'transaction_uuid': None,
                    'uuid': str(self.bob_assignment.uuid),
                },
            ],
            'no_change': [
                {
                    'assignment_configuration': str(self.assignment_configuration.uuid),
                    'learner_email': 'carol@foo.com',
                    'lms_user_id': None,
                    'content_key': self.content_key,
                    'content_quantity': -789,
                    'last_notification_at': None,
                    'state': LearnerContentAssignmentStateChoices.ALLOCATED,
                    'transaction_uuid': None,
                    'uuid': str(self.carol_assignment.uuid),
                },
            ],
        }
        self.assertEqual(expected_response_payload, response.json())
        mock_can_allocate.assert_called_once_with(
            self.assigned_learner_credit_policy,
            len(allocate_payload['learner_emails']),
            allocate_payload['content_key'],
            allocate_payload['content_price_cents'],
        )
        mock_allocate.assert_called_once_with(
            self.assignment_configuration,
            allocate_payload['learner_emails'],
            allocate_payload['content_key'],
            allocate_payload['content_price_cents'],
        )

    @mock.patch.object(AssignedLearnerCreditAccessPolicy, 'can_allocate', autospec=True)
    @mock.patch(
        'enterprise_access.apps.subsidy_access_policy.models.assignments_api.allocate_assignments',
        autospec=True,
    )
    @mock.patch(
        'enterprise_access.apps.api.v1.views.subsidy_access_policy.LmsApiClient',
        return_value=mock.MagicMock(),
    )
    def test_cannot_allocate(self, mock_lms_api_client, mock_allocate, mock_can_allocate):
        """
        When the policy is un-allocatable, a request to allocate results in a
        422 response and no allocation takes place.
        """
        mock_lms_api_client().get_enterprise_customer_data.return_value = {
            'slug': 'my-company',
            'admin_users': [{'email': 'admin@example.com'}],
        }
        mock_can_allocate.return_value = (False, 'some-reason')

        allocate_url = _allocation_url(self.assigned_learner_credit_policy.uuid)
        allocate_payload = {
            'learner_emails': ['alice@foo.com', 'bob@foo.com', 'carol@foo.com'],
            'content_key': self.content_key,
            'content_price_cents': 12345,
        }

        response = self.client.post(allocate_url, data=allocate_payload)

        self.assertEqual(status.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code)
        self.assertEqual(
            [
                {
                    'reason': 'some-reason',
                    'user_message': 'None',
                    'policy_uuids': [str(self.assigned_learner_credit_policy.uuid)],
                    'metadata': {'enterprise_administrators': [{'email': 'admin@example.com'}]},
                },
            ],
            response.json(),
        )
        mock_can_allocate.assert_called_once_with(
            self.assigned_learner_credit_policy,
            len(allocate_payload['learner_emails']),
            allocate_payload['content_key'],
            allocate_payload['content_price_cents'],
        )
        self.assertFalse(mock_allocate.called)

    @mock.patch.object(AssignedLearnerCreditAccessPolicy, 'can_allocate', autospec=True)
    @mock.patch(
        'enterprise_access.apps.subsidy_access_policy.models.assignments_api.allocate_assignments',
        autospec=True,
    )
    def test_cannot_allocate_negative_quantities(self, mock_allocate, mock_can_allocate):
        """
        Validate that you cannot request a negative amount of cents to allocate
        for a content key.
        """
        allocate_url = _allocation_url(self.assigned_learner_credit_policy.uuid)
        allocate_payload = {
            'learner_emails': ['alice@foo.com', 'bob@foo.com', 'carol@foo.com'],
            'content_key': self.content_key,
            'content_price_cents': -1,
        }

        response = self.client.post(allocate_url, data=allocate_payload)

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)
        self.assertEqual(
            {'content_price_cents': ['Ensure this value is greater than or equal to 0.']},
            response.json(),
        )
        self.assertFalse(mock_allocate.called)
        self.assertFalse(mock_can_allocate.called)

    @mock.patch.object(AssignedLearnerCreditAccessPolicy, 'can_allocate', autospec=True)
    @mock.patch(
        'enterprise_access.apps.subsidy_access_policy.models.assignments_api.allocate_assignments',
        autospec=True,
    )
    def test_cannot_allocate_locked(self, mock_allocate, mock_can_allocate):
        """
        When the policy is currently locked, a request to allocate should
        result in a 429 response and no allocation takes place.
        """
        mock_can_allocate.return_value = (True, None)

        allocate_url = _allocation_url(self.assigned_learner_credit_policy.uuid)
        allocate_payload = {
            'learner_emails': ['alice@foo.com', 'bob@foo.com', 'carol@foo.com'],
            'content_key': self.content_key,
            'content_price_cents': 12345,
        }

        # manually acquire a lock on our policy before the request is made
        self.assigned_learner_credit_policy.acquire_lock()

        response = self.client.post(allocate_url, data=allocate_payload)

        self.assigned_learner_credit_policy.release_lock()

        self.assertEqual(status.HTTP_429_TOO_MANY_REQUESTS, response.status_code)
        self.assertEqual(
            {'detail': 'Enrollment currently locked for this subsidy access policy.'},
            response.json(),
        )
        self.assertFalse(mock_can_allocate.called)
        self.assertFalse(mock_allocate.called)


@ddt.ddt
class TestSubsidyAccessPolicyAllocationEndToEnd(APITestWithMocks):
    """
    End-to-end tests for the ``allocate`` view, which ensure
    that expected assignment records exist due to API calls,
    and that allocation checks take existing state of assignments into account.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.enterprise_uuid = OTHER_TEST_ENTERPRISE_UUID
        cls.content_key = 'course-v1:edX+edXPrivacy101+3T2020'

        # Create a pair of AssignmentConfiguration + SubsidyAccessPolicy for the main test customer.
        cls.assignment_configuration = AssignmentConfigurationFactory(
            enterprise_customer_uuid=cls.enterprise_uuid,
        )
        cls.assigned_learner_credit_policy = AssignedLearnerCreditAccessPolicyFactory(
            display_name='An assigned learner credit policy, for the test customer.',
            enterprise_customer_uuid=cls.enterprise_uuid,
            active=True,
            assignment_configuration=cls.assignment_configuration,
            spend_limit=10000 * 100,
        )

    def setUp(self):
        super().setUp()

        self.enterprise_uuid = OTHER_TEST_ENTERPRISE_UUID

        self.set_jwt_cookie([{
            'system_wide_role': SYSTEM_ENTERPRISE_ADMIN_ROLE,
            'context': str(self.enterprise_uuid),
        }])

        # clear any leftover allocation locks
        self.addCleanup(django_cache.clear)

        # delete all assignment records for our policy between test function runs
        def delete_assignments():
            return self.assignment_configuration.assignments.all().delete()

        self.addCleanup(delete_assignments)

    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'catalog_contains_content_key', autospec=True, return_value=True
    )
    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'is_subsidy_active', new_callable=mock.PropertyMock, return_value=True,
    )
    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'subsidy_balance', autospec=True,
    )
    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'aggregates_for_policy', autospec=True,
    )
    def test_allocate_happy_path_e2e(
        self,
        mock_aggregates_for_policy,
        mock_subsidy_balance,
        mock_is_subsidy_active,
        mock_catalog_inclusion,
    ):
        """
        Tests that the allocate view does the underlying checks and creates
        assignment records as we'd expect.
        """
        mock_aggregates_for_policy.return_value = {
            'total_quantity': -100 * 100,
        }
        mock_subsidy_balance.return_value = 10000 * 100
        allocate_url = _allocation_url(self.assigned_learner_credit_policy.uuid)
        allocate_payload = {
            'learner_emails': ['new@foo.com'],
            'content_key': self.content_key,
            'content_price_cents': 123.45 * 100,  # policy limit is 100000.00 USD, so this should be well below limit
        }

        response = self.client.post(allocate_url, data=allocate_payload)

        new_allocation = self.assignment_configuration.assignments.filter(
            learner_email='new@foo.com',
            state=LearnerContentAssignmentStateChoices.ALLOCATED,
            content_key=self.content_key,
            content_quantity=-123.45 * 100,
        ).first()
        self.assertIsNotNone(new_allocation)
        expected_response_payload = {
            'updated': [],
            'created': [
                {
                    'assignment_configuration': str(self.assignment_configuration.uuid),
                    'learner_email': 'new@foo.com',
                    'lms_user_id': None,
                    'content_key': self.content_key,
                    'content_quantity': -123.45 * 100,
                    'last_notification_at': None,
                    'state': LearnerContentAssignmentStateChoices.ALLOCATED,
                    'transaction_uuid': None,
                    'uuid': str(new_allocation.uuid),
                },
            ],
            'no_change': [],
        }
        self.assertEqual(expected_response_payload, response.json())
        mock_is_subsidy_active.assert_called_once_with()  # No args for PropertyMock
        mock_catalog_inclusion.assert_called_once_with(self.assigned_learner_credit_policy, self.content_key)
        mock_aggregates_for_policy.assert_called_once_with(self.assigned_learner_credit_policy)
        mock_subsidy_balance.assert_called_once_with(self.assigned_learner_credit_policy)

    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'catalog_contains_content_key', autospec=True, return_value=False
    )
    @mock.patch(
        'enterprise_access.apps.api.v1.views.subsidy_access_policy.LmsApiClient',
        return_value=mock.MagicMock(),
    )
    def test_allocate_no_catalog_inclusion_e2e(self, mock_lms_api_client, mock_catalog_inclusion):
        """
        Test that we get a 422 when the requested content is not in the catalog.
        """
        mock_lms_api_client().get_enterprise_customer_data.return_value = {
            'slug': 'my-company',
            'admin_users': [{'email': 'admin@example.com'}],
        }

        allocate_url = _allocation_url(self.assigned_learner_credit_policy.uuid)
        allocate_payload = {
            'learner_emails': ['new@foo.com'],
            'content_key': self.content_key,
            'content_price_cents': 1,
        }

        response = self.client.post(allocate_url, data=allocate_payload)

        self.assertEqual(status.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code)
        self.assertEqual(
            [
                {
                    'reason': REASON_CONTENT_NOT_IN_CATALOG,
                    'user_message': MissingSubsidyAccessReasonUserMessages.CONTENT_NOT_IN_CATALOG,
                    'policy_uuids': [str(self.assigned_learner_credit_policy.uuid)],
                    'metadata': {'enterprise_administrators': [{'email': 'admin@example.com'}]},
                },
            ],
            response.json(),
        )
        mock_catalog_inclusion.assert_called_once_with(self.assigned_learner_credit_policy, self.content_key)

    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'catalog_contains_content_key', autospec=True, return_value=True
    )
    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'is_subsidy_active', new_callable=mock.PropertyMock, return_value=False
    )
    @mock.patch(
        'enterprise_access.apps.api.v1.views.subsidy_access_policy.LmsApiClient',
        return_value=mock.MagicMock(),
    )
    def test_allocate_inactive_subsidy_e2e(self, mock_lms_api_client, mock_is_subsidy_active, mock_catalog_inclusion):
        """
        Test that we get a 422 when the requested subsidy is inactive.
        """
        mock_lms_api_client().get_enterprise_customer_data.return_value = {
            'slug': 'my-company',
            'admin_users': [{'email': 'admin@example.com'}],
        }

        allocate_url = _allocation_url(self.assigned_learner_credit_policy.uuid)
        allocate_payload = {
            'learner_emails': ['new@foo.com'],
            'content_key': self.content_key,
            'content_price_cents': 1,
        }

        response = self.client.post(allocate_url, data=allocate_payload)

        self.assertEqual(status.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code)
        self.assertEqual(
            [
                {
                    'reason': REASON_SUBSIDY_EXPIRED,
                    'user_message': MissingSubsidyAccessReasonUserMessages.ORGANIZATION_EXPIRED_FUNDS,
                    'policy_uuids': [str(self.assigned_learner_credit_policy.uuid)],
                    'metadata': {'enterprise_administrators': [{'email': 'admin@example.com'}]},
                },
            ],
            response.json(),
        )
        mock_catalog_inclusion.assert_called_once_with(self.assigned_learner_credit_policy, self.content_key)
        mock_is_subsidy_active.assert_called_once_with()  # No args for PropertyMock

    @mock.patch(
        'enterprise_access.apps.api.v1.views.subsidy_access_policy.LmsApiClient',
        return_value=mock.MagicMock(),
    )
    def test_allocate_policy_expired_e2e(self, mock_lms_api_client):
        """
        Test that we get a 422 when the requested policy is inactive
        """
        assignment_configuration = AssignmentConfigurationFactory(
            enterprise_customer_uuid=self.enterprise_uuid,
        )
        inactive_policy = AssignedLearnerCreditAccessPolicyFactory(
            display_name='An assigned learner credit policy, for the test customer.',
            enterprise_customer_uuid=self.enterprise_uuid,
            active=False,
            assignment_configuration=assignment_configuration,
            spend_limit=10,
        )
        mock_lms_api_client().get_enterprise_customer_data.return_value = {
            'slug': 'my-company',
            'admin_users': [{'email': 'admin@example.com'}],
        }

        allocate_url = _allocation_url(inactive_policy.uuid)
        allocate_payload = {
            'learner_emails': ['new@foo.com'],
            'content_key': self.content_key,
            'content_price_cents': 1,
        }

        response = self.client.post(allocate_url, data=allocate_payload)

        self.assertEqual(status.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code)
        self.assertEqual(
            [
                {
                    'reason': REASON_POLICY_EXPIRED,
                    'user_message': MissingSubsidyAccessReasonUserMessages.ORGANIZATION_NO_FUNDS,
                    'policy_uuids': [str(inactive_policy.uuid)],
                    'metadata': {'enterprise_administrators': [{'email': 'admin@example.com'}]},
                },
            ],
            response.json(),
        )

    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'subsidy_balance', autospec=True,
    )
    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'aggregates_for_policy', autospec=True,
    )
    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'catalog_contains_content_key', autospec=True, return_value=True
    )
    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'is_subsidy_active', new_callable=mock.PropertyMock, return_value=True
    )
    @mock.patch(
        'enterprise_access.apps.api.v1.views.subsidy_access_policy.LmsApiClient',
        return_value=mock.MagicMock(),
    )
    def test_allocate_too_much_subsidy_spend_e2e(
        self,
        mock_lms_api_client,
        mock_is_subsidy_active,
        mock_catalog_inclusion,
        mock_aggregates_for_policy,
        mock_subsidy_balance,
    ):
        """
        Test that we get a 422 when allocating the requested amount would
        exceed the remaining balance of the related subsidy/ledger.
        """
        mock_lms_api_client().get_enterprise_customer_data.return_value = {
            'slug': 'my-company',
            'admin_users': [{'email': 'admin@example.com'}],
        }

        subsidy_balance = 300
        mock_subsidy_balance.return_value = subsidy_balance
        mock_aggregates_for_policy.return_value = {
            'total_quantity': (subsidy_balance - 1) * -1,
        }

        allocate_url = _allocation_url(self.assigned_learner_credit_policy.uuid)
        allocate_payload = {
            'learner_emails': ['new@foo.com'],
            'content_key': self.content_key,
            'content_price_cents': 2,
        }

        response = self.client.post(allocate_url, data=allocate_payload)

        self.assertEqual(status.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code)
        self.assertEqual(
            [
                {
                    'reason': REASON_NOT_ENOUGH_VALUE_IN_SUBSIDY,
                    'user_message': MissingSubsidyAccessReasonUserMessages.ORGANIZATION_NO_FUNDS,
                    'policy_uuids': [str(self.assigned_learner_credit_policy.uuid)],
                    'metadata': {'enterprise_administrators': [{'email': 'admin@example.com'}]},
                },
            ],
            response.json(),
        )
        mock_catalog_inclusion.assert_called_once_with(self.assigned_learner_credit_policy, self.content_key)
        mock_is_subsidy_active.assert_called_once_with()  # No args for PropertyMock
        mock_subsidy_balance.assert_called_once_with(self.assigned_learner_credit_policy)
        mock_aggregates_for_policy.assert_called_once_with(self.assigned_learner_credit_policy)

    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'subsidy_balance', autospec=True,
    )
    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'aggregates_for_policy', autospec=True,
    )
    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'catalog_contains_content_key', autospec=True, return_value=True
    )
    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'is_subsidy_active', new_callable=mock.PropertyMock, return_value=True
    )
    @mock.patch(
        'enterprise_access.apps.api.v1.views.subsidy_access_policy.LmsApiClient',
        return_value=mock.MagicMock(),
    )
    def test_allocate_too_much_existing_allocation_e2e(
        self,
        mock_lms_api_client,
        mock_is_subsidy_active,  # pylint: disable=unused-argument
        mock_catalog_inclusion,  # pylint: disable=unused-argument
        mock_aggregates_for_policy,
        mock_subsidy_balance,
    ):
        """
        Test that we get a 422 when allocating the requested amount would
        exceed the remaining balance of the related subsidy/ledger when
        more than 0 allocated assignments already exist for the policy.
        """
        mock_lms_api_client().get_enterprise_customer_data.return_value = {
            'slug': 'my-company',
            'admin_users': [{'email': 'admin@example.com'}],
        }

        subsidy_balance = 300
        mock_subsidy_balance.return_value = subsidy_balance
        mock_aggregates_for_policy.return_value = {
            'total_quantity': (subsidy_balance - 2) * -1,
        }

        allocate_url = _allocation_url(self.assigned_learner_credit_policy.uuid)
        allocate_payload = {
            'learner_emails': ['new@foo.com'],
            'content_key': self.content_key,
            'content_price_cents': 1,
        }

        ok_response = self.client.post(allocate_url, data=allocate_payload)

        # The spend alone, with no existing allocations, plus
        # one more cent should be fine to allocate.
        self.assertEqual(status.HTTP_202_ACCEPTED, ok_response.status_code)

        # We should be right at the subsidy balance now,
        # the next allocation request should fail.
        allocate_payload = {
            'learner_emails': ['blue@foo.com'],
            'content_key': self.content_key,
            'content_price_cents': 1,
        }
        response = self.client.post(allocate_url, data=allocate_payload)

        self.assertEqual(status.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code)
        self.assertEqual(
            [
                {
                    'reason': REASON_NOT_ENOUGH_VALUE_IN_SUBSIDY,
                    'user_message': MissingSubsidyAccessReasonUserMessages.ORGANIZATION_NO_FUNDS,
                    'policy_uuids': [str(self.assigned_learner_credit_policy.uuid)],
                    'metadata': {'enterprise_administrators': [{'email': 'admin@example.com'}]},
                },
            ],
            response.json(),
        )

    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'subsidy_balance', autospec=True,
    )
    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'aggregates_for_policy', autospec=True,
    )
    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'catalog_contains_content_key', autospec=True, return_value=True
    )
    @mock.patch.object(
        AssignedLearnerCreditAccessPolicy, 'is_subsidy_active', new_callable=mock.PropertyMock, return_value=True
    )
    @mock.patch(
        'enterprise_access.apps.api.v1.views.subsidy_access_policy.LmsApiClient',
        return_value=mock.MagicMock(),
    )
    def test_allocate_policy_spend_limit_exceeded_e2e(
        self,
        mock_lms_api_client,
        mock_is_subsidy_active,  # pylint: disable=unused-argument
        mock_catalog_inclusion,  # pylint: disable=unused-argument
        mock_aggregates_for_policy,
        mock_subsidy_balance,
    ):
        """
        Test that we get a 422 when allocating the requested amount would
        exceed the spend limit of the policy (but pass every other check).
        """
        mock_lms_api_client().get_enterprise_customer_data.return_value = {
            'slug': 'my-company',
            'admin_users': [{'email': 'admin@example.com'}],
        }

        subsidy_balance = 15000 * 100
        mock_subsidy_balance.return_value = subsidy_balance
        mock_aggregates_for_policy.return_value = {
            'total_quantity': 0,
        }

        allocate_url = _allocation_url(self.assigned_learner_credit_policy.uuid)
        allocate_payload = {
            'learner_emails': ['new@foo.com'],
            'content_key': self.content_key,
            'content_price_cents': (
                self.assigned_learner_credit_policy.spend_limit + 10
            ),
        }

        response = self.client.post(allocate_url, data=allocate_payload)

        self.assertEqual(status.HTTP_422_UNPROCESSABLE_ENTITY, response.status_code)
        self.assertEqual(
            [
                {
                    'reason': REASON_POLICY_SPEND_LIMIT_REACHED,
                    'user_message': MissingSubsidyAccessReasonUserMessages.ORGANIZATION_NO_FUNDS,
                    'policy_uuids': [str(self.assigned_learner_credit_policy.uuid)],
                    'metadata': {'enterprise_administrators': [{'email': 'admin@example.com'}]},
                },
            ],
            response.json(),
        )


@ddt.ddt
class TestAssignmentConfigurationUnauthorizedCRUD(APITest):
    """
    Tests Authentication and Permission checking for AssignmentConfiguration CRUD views.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.enterprise_uuid = TEST_ENTERPRISE_UUID

        # Create a pair of AssignmentConfiguration + SubsidyAccessPolicy for the main test customer.
        cls.assignment_configuration = AssignmentConfigurationFactory(
            enterprise_customer_uuid=cls.enterprise_uuid,
        )
        cls.assigned_learner_credit_policy = AssignedLearnerCreditAccessPolicyFactory(
            display_name='An assigned learner credit policy, for the test customer.',
            enterprise_customer_uuid=cls.enterprise_uuid,
            active=True,
            assignment_configuration=cls.assignment_configuration,
            spend_limit=1000000,
        )

    @ddt.data(
        # A role that's not mapped to any feature perms will get you a 403.
        (
            {'system_wide_role': 'some-other-role', 'context': str(TEST_ENTERPRISE_UUID)},
            status.HTTP_403_FORBIDDEN,
        ),
        # A good learner role, AND in the correct context/customer STILL gets you a 403.
        # Allocation APIs are inaccessible to all learners.
        (
            {'system_wide_role': SYSTEM_ENTERPRISE_LEARNER_ROLE, 'context': str(TEST_ENTERPRISE_UUID)},
            status.HTTP_403_FORBIDDEN,
        ),
        # A good admin role, but in a context/customer we're not aware of, gets you a 403.
        (
            {'system_wide_role': SYSTEM_ENTERPRISE_ADMIN_ROLE, 'context': str(uuid4())},
            status.HTTP_403_FORBIDDEN,
        ),
        # An operator role, but in a context/customer we're not aware of, gets you a 403.
        (
            {'system_wide_role': SYSTEM_ENTERPRISE_OPERATOR_ROLE, 'context': str(uuid4())},
            status.HTTP_403_FORBIDDEN,
        ),
        # No JWT based auth, no soup for you.
        (
            None,
            status.HTTP_401_UNAUTHORIZED,
        ),
    )
    @ddt.unpack
    def test_allocation_view_unauthorized_forbidden(self, role_context_dict, expected_response_code):
        """
        Tests that we get expected 40x responses for the allocation view
        """
        # Set the JWT-based auth that we'll use for every request
        if role_context_dict:
            self.set_jwt_cookie([role_context_dict])

        allocate_url = _allocation_url(self.assigned_learner_credit_policy.uuid)
        allocate_payload = {
            'learner_emails': ['alice@foo.com', 'bob@foo.com'],
            'content_key': 'the-content-key',
            'content_price_cents': 12345,
        }

        response = self.client.post(allocate_url, data=allocate_payload)

        assert response.status_code == expected_response_code
