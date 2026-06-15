"""
Token bucket rate limiter using Redis.
Ensures WhatsApp API rate limits are respected.
"""
import time
import redis
from django.conf import settings


class RateLimiter:
    """
    Token bucket rate limiter implementation using Redis.

    WhatsApp Cloud API limits: ~80 messages/second for business tier.
    Default: 50 tokens/second for safety margin.
    """

    SCRIPT = """
    local key = KEYS[1]
    local max_tokens = tonumber(ARGV[1])
    local refill_rate = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])
    local requested = tonumber(ARGV[4])

    local data = redis.call('HMGET', key, 'tokens', 'last_refill')
    local tokens = tonumber(data[1]) or max_tokens
    local last_refill = tonumber(data[2]) or now

    local elapsed = now - last_refill
    tokens = math.min(max_tokens, tokens + elapsed * refill_rate)

    if tokens >= requested then
        redis.call('HMSET', key, 'tokens', tokens - requested, 'last_refill', now)
        redis.call('EXPIRE', key, 60)
        return 1
    end
    return 0
    """

    def __init__(self, max_tokens=None, refill_rate=None, key_prefix='scheduler'):
        """
        Initialize rate limiter.

        Args:
            max_tokens: Maximum tokens in bucket
            refill_rate: Tokens per second refill rate
            key_prefix: Redis key prefix
        """
        self.redis = redis.from_url(
            getattr(settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0')
        )
        self.max_tokens = max_tokens or getattr(settings, 'SCHEDULER_RATE_LIMIT_TOKENS', 50)
        self.refill_rate = refill_rate or float(self.max_tokens)
        self.key = f'{key_prefix}:rate_limit'
        self._script = None

    def _get_script(self):
        """Get or create Redis script."""
        if self._script is None:
            self._script = self.redis.register_script(self.SCRIPT)
        return self._script

    def try_acquire(self, tokens=1):
        """
        Try to acquire tokens without blocking.

        Args:
            tokens: Number of tokens to acquire

        Returns:
            True if acquired, False otherwise
        """
        script = self._get_script()
        result = script(
            keys=[self.key],
            args=[self.max_tokens, self.refill_rate, time.time(), tokens]
        )
        return result == 1

    def acquire(self, tokens=1, timeout=30.0):
        """
        Acquire tokens, blocking until available or timeout.

        Args:
            tokens: Number of tokens to acquire
            timeout: Maximum time to wait in seconds

        Returns:
            True if acquired, False if timeout
        """
        start = time.time()

        while True:
            if self.try_acquire(tokens):
                return True

            elapsed = time.time() - start
            if elapsed >= timeout:
                return False

            # Sleep a small amount before retry
            time.sleep(0.02)

    def get_status(self):
        """
        Get current rate limiter status.

        Returns:
            Dict with current tokens and last refill time
        """
        data = self.redis.hgetall(self.key)
        if not data:
            return {
                'tokens': self.max_tokens,
                'last_refill': time.time(),
                'max_tokens': self.max_tokens,
                'refill_rate': self.refill_rate
            }

        return {
            'tokens': float(data.get(b'tokens', self.max_tokens)),
            'last_refill': float(data.get(b'last_refill', time.time())),
            'max_tokens': self.max_tokens,
            'refill_rate': self.refill_rate
        }

    def reset(self):
        """Reset the rate limiter to full capacity."""
        self.redis.delete(self.key)
