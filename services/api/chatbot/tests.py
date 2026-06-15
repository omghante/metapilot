from django.test import TestCase, Client
from django.urls import reverse
from users.models import User
from tenants.models import Tenant
from chatbot.service import PlatformChatbotService
import json

class ChatbotServiceTests(TestCase):
    def setUp(self):
        self.service = PlatformChatbotService()

    def test_is_platform_question(self):
        self.assertTrue(self.service.is_platform_question("How do I create a campaign?"))
        self.assertTrue(self.service.is_platform_question("whatsapp api setup"))
        self.assertFalse(self.service.is_platform_question("tell me a joke"))

    def test_get_response_matching_content(self):
        # "campaign" should match some content in content.json
        response = self.service.get_response("How to create campaign?")
        self.assertIsNotNone(response)
        self.assertIn("campaign", response.lower())

class ChatbotAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.tenant = Tenant.objects.create(name="Test Tenant", domain="test")
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpassword",
            tenant=self.tenant
        )
        self.client.force_login(self.user)

    def test_chatbot_test_endpoint(self):
        url = reverse('chatbot-test')
        data = {
            "message": "How do I create a new campaign?",
            "tenant_name": "Test Tenant"
        }
        response = self.client.post(url, data=json.dumps(data), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])

    def test_chatbot_check_endpoint(self):
        url = reverse('chatbot-check')
        data = {"message": "How do I create a new campaign?"}
        response = self.client.post(url, data=json.dumps(data), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['is_platform_question'])
