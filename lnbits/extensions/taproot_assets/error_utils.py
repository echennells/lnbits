"""
Standardized error handling utilities for the Taproot Assets extension.
Provides consistent error handling patterns and utilities.
"""
import functools
from http import HTTPStatus
from typing import Dict, Any, Optional, Tuple, Union, Callable, TypeVar, Awaitable, cast, Type

import grpc
from fastapi import HTTPException, Request, Response
from loguru import logger

from .models import ApiResponse, ErrorDetail
from .logging_utils import (
    log_error, log_debug, log_info, log_warning, log_critical,
    log_exception, API, GENERAL
)

# Define a type variable for the decorated function
F = TypeVar('F', bound=Callable[..., Awaitable[Any]])


# Base exception class for Taproot Assets extension
class TaprootAssetError(Exception):
    """Base exception class for Taproot Assets extension."""
    def __init__(
        self, 
        message: str, 
        code: str = "GENERAL_ERROR", 
        http_status: int = 500,
        context: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.code = code
        self.http_status = http_status
        self.context = context or {}
        super().__init__(message)


# Specific error types
class AssetNotFoundError(TaprootAssetError):
    """Raised when an asset is not found."""
    def __init__(self, asset_id: str):
        super().__init__(
            message=f"Asset not found: {asset_id}",
            code="ASSET_NOT_FOUND",
            http_status=404,
            context={"asset_id": asset_id}
        )


class InsufficientBalanceError(TaprootAssetError):
    """Raised when there is insufficient balance for an operation."""
    def __init__(self, asset_id: str, required: int, available: int):
        super().__init__(
            message=f"Insufficient balance for asset {asset_id}",
            code="INSUFFICIENT_BALANCE",
            http_status=400,
            context={
                "asset_id": asset_id,
                "required": required,
                "available": available
            }
        )


class InvalidInvoiceError(TaprootAssetError):
    """Raised when an invoice is invalid."""
    def __init__(self, reason: str):
        super().__init__(
            message=f"Invalid invoice: {reason}",
            code="INVALID_INVOICE",
            http_status=400,
            context={"reason": reason}
        )


class ChannelError(TaprootAssetError):
    """Raised when there is an issue with a channel."""
    def __init__(self, message: str, channel_id: Optional[str] = None):
        context = {"channel_id": channel_id} if channel_id else {}
        super().__init__(
            message=message,
            code="CHANNEL_ERROR",
            http_status=503,
            context=context
        )


class InternalPaymentError(TaprootAssetError):
    """Raised when there is an issue with an internal payment."""
    def __init__(self, payment_hash: str):
        super().__init__(
            message="This invoice belongs to another user on this node. Please use the internal payment flow.",
            code="INTERNAL_PAYMENT_REQUIRED",
            http_status=400,
            context={"payment_hash": payment_hash}
        )


class SelfPaymentError(TaprootAssetError):
    """Raised when there is an issue with a self-payment."""
    def __init__(self, payment_hash: str):
        super().__init__(
            message="Self-payments are not allowed through the regular payment flow. Use the internal-payment endpoint.",
            code="SELF_PAYMENT_ERROR",
            http_status=400,
            context={"payment_hash": payment_hash}
        )


class MissingParameterError(TaprootAssetError):
    """Raised when a required parameter is missing."""
    def __init__(self, parameter: str):
        super().__init__(
            message=f"Missing required parameter: {parameter}",
            code="MISSING_PARAMETER",
            http_status=400,
            context={"parameter": parameter}
        )


class TapdCommunicationError(TaprootAssetError):
    """Raised when there is an issue communicating with the Taproot Assets daemon."""
    def __init__(self, message: str, grpc_code: Optional[str] = None):
        context = {"grpc_code": grpc_code} if grpc_code else {}
        super().__init__(
            message=f"Error communicating with Taproot Assets daemon: {message}",
            code="TAPD_COMMUNICATION_ERROR",
            http_status=503,
            context=context
        )


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
    
    # Log the gRPC error
    log_error(API, f"gRPC error in {context}: {e.code()}: {e.details()}")
    
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
    log_error(API, f"HTTP error {status_code}: {detail}")
    raise HTTPException(status_code=status_code, detail=detail)


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
        except TaprootAssetError as e:
            # Handle custom Taproot Asset errors
            details = ErrorDetail(
                code=e.code,
                source="taproot_assets",
                context=e.context
            )
            
            # Return standardized error response
            return ApiResponse.error_response(
                message=e.message,
                details=details,
                status_code=e.http_status
            )
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
            log_exception(API, e, context=func.__name__)
            
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


class ErrorContext:
    """
    Context manager for standardized error handling.
    
    Example:
        with ErrorContext("process_payment", PAYMENT):
            # Your code here
            # Automatically handles and transforms exceptions
    """
    
    def __init__(self, operation: str, component: str):
        """
        Initialize the error context.
        
        Args:
            operation: Description of the operation being performed
            component: The component identifier (use constants from logging_utils)
        """
        self.operation = operation
        self.component = component
        
    def __enter__(self):
        """Enter the context."""
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Handle exceptions and transform them into appropriate error types."""
        if exc_type is None:
            return True
            
        if isinstance(exc_val, TaprootAssetError):
            # Already a custom error, just log it
            log_error(self.component, str(exc_val))
            return False
            
        if isinstance(exc_val, grpc.aio.AioRpcError):
            # Handle gRPC errors
            error_message, status_code = handle_grpc_error(exc_val, self.operation)
            log_error(self.component, f"gRPC error in {self.operation}: {error_message}")
            raise TapdCommunicationError(error_message, str(exc_val.code()))
            
        # Handle other exceptions
        log_exception(self.component, exc_val, f"Error in {self.operation}")
        raise TaprootAssetError(f"Error in {self.operation}: {str(exc_val)}")
