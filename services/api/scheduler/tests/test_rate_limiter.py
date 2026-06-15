"""
Unit tests for rate limiter.
"""
from django.test import TestCase
from unittest.mock import patch, MagicMock


class RateLimiterTestCase(TestCase):
    """Test cases for RateLimiter."""

    @patch('scheduler.services.rate_limiter.redis.from_url')
    def test_try_acquire_succeeds_when_tokens_available(self, mock_redis_from_url):
        """Test that try_acquire succeeds when tokens are available."""
        from scheduler.services.rate_limiter import RateLimiter

        mock_redis = MagicMock()
        mock_script = MagicMock()
        mock_script.return_value = 1  # Success
        mock_redis.register_script.return_value = mock_script
        mock_redis_from_url.return_value = mock_redis

        limiter = RateLimiter(max_tokens=50)
        result = limiter.try_acquire()

        self.assertTrue(result)

    @patch('scheduler.services.rate_limiter.redis.from_url')
    def test_try_acquire_fails_when_no_tokens(self, mock_redis_from_url):
        """Test that try_acquire fails when no tokens available."""
        from scheduler.services.rate_limiter import RateLimiter

        mock_redis = MagicMock()
        mock_script = MagicMock()
        mock_script.return_value = 0  # Failed
        mock_redis.register_script.return_value = mock_script
        mock_redis_from_url.return_value = mock_redis

        limiter = RateLimiter(max_tokens=50)
        result = limiter.try_acquire()

        self.assertFalse(result)

    @patch('scheduler.services.rate_limiter.redis.from_url')
    def test_get_status_returns_defaults_when_empty(self, mock_redis_from_url):
        """Test get_status returns defaults when Redis key is empty."""
        from scheduler.services.rate_limiter import RateLimiter

        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {}
        mock_redis_from_url.return_value = mock_redis

        limiter = RateLimiter(max_tokens=50, refill_rate=50.0)
        status = limiter.get_status()

        self.assertEqual(status['max_tokens'], 50)
        self.assertEqual(status['refill_rate'], 50.0)
        self.assertEqual(status['tokens'], 50)

    @patch('scheduler.services.rate_limiter.redis.from_url')
    def test_reset_deletes_key(self, mock_redis_from_url):
        """Test that reset deletes the Redis key."""
        from scheduler.services.rate_limiter import RateLimiter

        mock_redis = MagicMock()
        mock_redis_from_url.return_value = mock_redis

        limiter = RateLimiter(max_tokens=50, key_prefix='test')
        limiter.reset()

        mock_redis.delete.assert_called_once_with('test:rate_limit')
