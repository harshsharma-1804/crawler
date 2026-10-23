"""Retry handler with exponential backoff and circuit breaker."""
import asyncio
import random
from typing import Callable, TypeVar, Optional
from functools import wraps
from dataclasses import dataclass

T = TypeVar('T')


@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    retryable_exceptions: tuple = (Exception,)
    on_retry: Optional[Callable] = None


class RetryHandler:
    """Async retry handler with exponential backoff."""
    
    def __init__(self, config: RetryConfig = None):
        self.config = config or RetryConfig()
    
    async def execute(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute function with retry logic."""
        last_exception = None
        
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                return await func(*args, **kwargs)
            except self.config.retryable_exceptions as e:
                last_exception = e
                
                if attempt == self.config.max_attempts:
                    break
                
                # Calculate delay with jitter
                delay = min(
                    self.config.base_delay * (self.config.exponential_base ** (attempt - 1)),
                    self.config.max_delay
                )
                jitter = random.uniform(0, delay * 0.1)
                await asyncio.sleep(delay + jitter)
                
                if self.config.on_retry:
                    await self.config.on_retry(attempt, e)
        
        raise last_exception


def with_retry(config: RetryConfig = None):
    """Decorator for adding retry logic to async functions."""
    handler = RetryHandler(config)
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await handler.execute(func, *args, **kwargs)
        return wrapper
    return decorator


class CircuitBreaker:
    """Circuit breaker pattern for preventing cascade failures."""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open
    
    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Call function with circuit breaker protection."""
        if self.state == "open":
            if asyncio.get_event_loop().time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
            else:
                raise CircuitBreakerOpen("Circuit breaker is open")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e
    
    def _on_success(self):
        """Handle successful call."""
        self.failures = 0
        self.state = "closed"
    
    def _on_failure(self):
        """Handle failed call."""
        self.failures += 1
        self.last_failure_time = asyncio.get_event_loop().time()
        
        if self.failures >= self.failure_threshold:
            self.state = "open"
    
    def is_open(self) -> bool:
        """Check if circuit breaker is open."""
        return self.state == "open"


class CircuitBreakerOpen(Exception):
    """Exception raised when circuit breaker is open."""
    pass
