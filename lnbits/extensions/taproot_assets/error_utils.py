"""
Error handling utilities for Taproot Assets extension.
Provides consistent error handling patterns across the codebase.
"""
import traceback
from typing import Dict, Any, Optional
from fastapi import HTTPException
from http import HTTPStatus
from loguru import logger

from .logging_utils import log_error, log_warning, log_debug

class TaprootAssetError(Exception):
    """Base exception class for Taproot Assets extension."""
    pass

class ErrorContext:
    """
    Context manager for standardized error handling.
    Provides consistent error handling and logging across the codebase.
    """
    
    def __init__(self, context: str, log_category: str = None):
        """
        Initialize the error context.
        
        Args:
            context: A string describing the context where this error might occur
            log_category: Optional category for logging
        """
        self.context = context
        self.log_category = log_category
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            # Log the error with context
            if self.log_category:
                log_error(self.log_category, f"Error in {self.context}: {str(exc_val)}")
            else:
                logger.error(f"Error in {self.context}: {str(exc_val)}")
                
            # Don't suppress the exception
            return False
        return True

def handle_error(context: str, error: Exception, payment_hash: Optional[str] = None) -> Dict[str, Any]:
    """
    Standardized error response generator.
    
    Args:
        context: The context where the error occurred
        error: The exception that was raised
        payment_hash: Optional payment hash for payment-related errors
        
    Returns:
        Dict containing standardized error response
    """
    error_type = type(error).__name__
    error_message = str(error)
    
    # Log the error
    log_error(context, f"{context} error ({error_type}): {error_message}")
    
    # Create standardized error response
    return {
        "success": False,
        "error": error_message,
        "context": context,
        "payment_hash": payment_hash,
        "status": "error"
    }

def raise_http_exception(
    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR,
    detail: str = "An unexpected error occurred",
    headers: Optional[Dict[str, str]] = None
) -> None:
    """
    Raise a FastAPI HTTPException with consistent formatting.
    
    Args:
        status_code: HTTP status code
        detail: Error detail message
        headers: Optional HTTP headers
        
    Raises:
        HTTPException: FastAPI HTTP exception
    """
    # Log the error before raising
    log_warning("API", f"HTTP Exception {status_code}: {detail}")
    
    # Raise the exception
    raise HTTPException(
        status_code=status_code,
        detail=detail,
        headers=headers
    )

def handle_api_error(func):
    """
    Decorator for API endpoints to standardize error handling.
    Catches exceptions and returns appropriate HTTP responses.
    
    Args:
        func: The API endpoint function to wrap
        
    Returns:
        Wrapped function with standardized error handling
    """
    import functools
    
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            # Re-raise HTTP exceptions as they're already properly formatted
            raise
        except Exception as e:
            # Get function name for better error context
            function_name = func.__name__
            
            # Log the error with traceback
            log_error("API", f"Error in {function_name}: {str(e)}")
            log_debug("API", f"Traceback: {traceback.format_exc()}")
            
            # Determine appropriate status code based on error type
            status_code = HTTPStatus.INTERNAL_SERVER_ERROR
            
            # Create user-friendly error message
            detail = f"API Error: {str(e)}"
            
            # Raise properly formatted HTTP exception
            raise_http_exception(
                status_code=status_code,
                detail=detail
            )
    
    return wrapper
