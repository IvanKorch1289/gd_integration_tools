from aiocircuitbreaker import CircuitBreakerError, circuit
from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware


__all__ = ("CircuitBreakerMiddleware",)


# Circuit Breaker configuration
@circuit(
    failure_threshold=3,  # Number of failures before the circuit opens
    recovery_timeout=10,  # Time in seconds to wait before attempting recovery
    expected_exception=HTTPException,  # Exception type to consider as a failure
)
async def protected_call_next(request: Request, call_next):
    """
    Protected function that wraps the call_next middleware with a circuit breaker.

    Args:
        request (Request): The incoming HTTP request.
        call_next (Callable): The next middleware or endpoint handler.

    Returns:
        Response: The HTTP response from the next middleware or endpoint.

    Raises:
        HTTPException: If the circuit breaker is open or an error occurs.
    """
    return await call_next(request)


class CircuitBreakerMiddleware(BaseHTTPMiddleware):
    """
    Middleware to integrate a Circuit Breaker pattern into FastAPI.

    This middleware wraps the request handling logic with a circuit breaker
    to prevent cascading failures and improve system resilience.
    """

    async def dispatch(self, request: Request, call_next):
        """
        Dispatch the request through the circuit breaker.

        Args:
            request (Request): The incoming HTTP request.
            call_next (Callable): The next middleware or endpoint handler.

        Returns:
            Response: The HTTP response from the next middleware or endpoint.

        Raises:
            HTTPException: If the circuit breaker is open or an error occurs.
        """
        try:
            # Wrap the call_next function with the circuit breaker
            response = await protected_call_next(request, call_next)
            return response
        except CircuitBreakerError:
            # If the circuit breaker is open, return a 503 Service Unavailable response
            raise HTTPException(
                status_code=503,
                detail="Service temporarily unavailable due to high failure rate.",
            )
