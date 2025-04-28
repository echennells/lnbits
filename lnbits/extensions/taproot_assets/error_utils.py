"""
Standardized error handling utilities for the Taproot Assets extension.
"""
import functools
from http import HTTPStatus
from typing import Dict, Any, Optional, Tuple, Union, Callable, TypeVar, Awaitable, cast

import grpc
from fastapi import HTTPException, Request, Response
from loguru import logger

from .models import ApiResponse, ErrorDetail

# Define a type variable for the decorated function
F = TypeVar('F', bound=Callable[..., Awaitable[Any]])


def format_error_response(error_message: str, error_details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Format a standardized error response.
    
    Args:
        error_message: Human-readable error message
        error_details: Optional dictionary with additional error details
        
    Returns:
        Dict containing the formatted error response
    """
    response = {
        "success": False,
        "error": error_message
    }
    
    if error_details:
        response["details"] = error_details
        
    return response


def handle_grpc_error(e: grpc.aio.AioRpcError, context: str = "") -> Tuple[str, int]:
    """
    Handle gRPC errors and return a user-friendly error message and appropriate status code.
    
    Args:
        e: The gRPC error
        context: Optional context string for the error
        
    Returns:
        Tuple containing (error_message, http_status_code)
    """
    error_details = e.details().lower()
    status_code = 500  # Default to internal server error
    
    # Context prefix for better error message clarity
    prefix = f"{context}: " if context else ""
    
    # Channel-related errors
    if "multiple asset channels found" in error_details and "please specify the peer pubkey" in error_details:
        return (f"{prefix}Multiple channels found for this asset. Please select a specific channel.", 400)
    elif "no asset channel found for asset" in error_details:
        return (f"{prefix}Channel appears to be offline or unavailable. Please refresh and try again.", 503)
    elif "no asset channel balance found" in error_details:
        return (f"{prefix}Insufficient channel balance for this asset. Please refresh and try again.", 400)
    elif "peer" in error_details and "channel" in error_details:
        return (f"{prefix}Channel with peer appears to be offline. Please refresh and try again.", 503)
    
    # Payment-related errors
    elif "self-payments not allowed" in error_details:
        return (f"{prefix}This invoice belongs to another user on this node. Please use the internal payment flow.", 400)
    elif "invalid payment request" in error_details:
        return (f"{prefix}Invalid payment request format.", 400)
    
    # Map gRPC error codes to HTTP status codes
    grpc_code = e.code()
    if grpc_code == grpc.StatusCode.NOT_FOUND:
        status_code = 404
    elif grpc_code == grpc.StatusCode.ALREADY_EXISTS:
        status_code = 409
    elif grpc_code == grpc.StatusCode.INVALID_ARGUMENT:
        status_code = 400
    elif grpc_code == grpc.StatusCode.FAILED_PRECONDITION:
        status_code = 412
    elif grpc_code == grpc.StatusCode.PERMISSION_DENIED:
        status_code = 403
    elif grpc_code == grpc.StatusCode.UNAUTHENTICATED:
        status_code = 401
    elif grpc_code == grpc.StatusCode.UNAVAILABLE:
        status_code = 503
    
    # Fallback for other gRPC errors
    return (f"{prefix}Error communicating with Taproot Assets daemon: {e.details()}", status_code)


def raise_http_exception(status_code: int, detail: str) -> None:
    """
    Raise an HTTPException with the given status code and detail.
    This is a helper to standardize HTTP exception handling.
    
    Args:
        status_code: HTTP status code
        detail: Detail message
        
    Raises:
        HTTPException: With the given status code and detail
    """
    logger.error(f"HTTP error {status_code}: {detail}")
    raise HTTPException(status_code=status_code, detail=detail)


def log_error(error: Exception, context: str = "", level: str = "error") -> None:
    """
    Log an error with consistent formatting.
    
    Args:
        error: The exception to log
        context: Optional context string for the error
        level: Log level (debug, info, warning, error, critical)
    """
    prefix = f"{context}: " if context else ""
    message = f"{prefix}{str(error)}"
    
    if level == "debug":
        logger.debug(message)
    elif level == "info":
        logger.info(message)
    elif level == "warning":
        logger.warning(message)
    elif level == "critical":
        logger.critical(message)
    else:
        logger.error(message)


def handle_api_error(func: F) -> F:
    """
    Decorator for consistent API error handling.
    
    This decorator wraps API endpoint functions to provide standardized error handling.
    It catches exceptions, formats them appropriately, and returns consistent error responses.
    
    Args:
        func: The API endpoint function to decorate
        
    Returns:
        The decorated function
    """
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            # Call the original function
            return await func(*args, **kwargs)
        except grpc.aio.AioRpcError as e:
            # Handle gRPC errors
            error_message, status_code = handle_grpc_error(e, context=func.__name__)
            
            # Create error details
            details = ErrorDetail(
                code="GRPC_ERROR",
                source="taproot_daemon",
                context={"grpc_code": str(e.code())}
            )
            
            # Return standardized error response
            return ApiResponse.error_response(
                message=error_message,
                details=details,
                status_code=status_code
            )
        except HTTPException as e:
            # Pass through FastAPI HTTP exceptions
            raise e
        except Exception as e:
            # Handle unexpected errors
            log_error(e, context=func.__name__)
            
            # Create error details
            details = ErrorDetail(
                code="INTERNAL_ERROR",
                source="taproot_assets",
                context={"error_type": type(e).__name__}
            )
            
            # Return standardized error response
            return ApiResponse.error_response(
                message=f"An unexpected error occurred: {str(e)}",
                details=details,
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR
            )
    
    return cast(F, wrapper)
