"""
Standardized logging utilities for the Taproot Assets extension.
Provides consistent logging patterns and utilities.
"""
from typing import Any, Dict, Optional
from loguru import logger

# Component prefixes for consistent logging
WALLET = "WALLET"
NODE = "NODE"
PAYMENT = "PAYMENT"
INVOICE = "INVOICE"
ASSET = "ASSET"
TRANSFER = "TRANSFER"
WEBSOCKET = "WS"
SETTINGS = "SETTINGS"
API = "API"
DB = "DB"
GENERAL = "GENERAL"
FACTORY = "FACTORY"  # Added for the TaprootAssetsFactory
PARSER = "PARSER"   # Added for the TaprootParserClient

# Log level mapping for reference
LOG_LEVELS = {
    "debug": 10,
    "info": 20,
    "warning": 30,
    "error": 40,
    "critical": 50
}


def log_debug(component: str, message: str, **kwargs) -> None:
    """
    Log a debug message with standard formatting.
    
    Args:
        component: The component identifier (use constants from this module)
        message: The message to log
        **kwargs: Additional parameters to pass to the logger
    """
    logger.debug(f"[{component}] {message}", **kwargs)


def log_info(component: str, message: str, **kwargs) -> None:
    """
    Log an info message with standard formatting.
    
    Args:
        component: The component identifier (use constants from this module)
        message: The message to log
        **kwargs: Additional parameters to pass to the logger
    """
    logger.info(f"[{component}] {message}", **kwargs)


def log_warning(component: str, message: str, **kwargs) -> None:
    """
    Log a warning message with standard formatting.
    
    Args:
        component: The component identifier (use constants from this module)
        message: The message to log
        **kwargs: Additional parameters to pass to the logger
    """
    logger.warning(f"[{component}] {message}", **kwargs)


def log_error(component: str, message: str, exc_info: bool = False, **kwargs) -> None:
    """
    Log an error message with standard formatting.
    
    Args:
        component: The component identifier (use constants from this module)
        message: The message to log
        exc_info: Whether to include exception info in the log
        **kwargs: Additional parameters to pass to the logger
    """
    logger.error(f"[{component}] {message}", exc_info=exc_info, **kwargs)


def log_critical(component: str, message: str, exc_info: bool = False, **kwargs) -> None:
    """
    Log a critical message with standard formatting.
    
    Args:
        component: The component identifier (use constants from this module)
        message: The message to log
        exc_info: Whether to include exception info in the log
        **kwargs: Additional parameters to pass to the logger
    """
    logger.critical(f"[{component}] {message}", exc_info=exc_info, **kwargs)


def log_exception(component: str, exception: Exception, context: str = "", level: str = "error") -> None:
    """
    Log an exception with consistent formatting.
    
    Args:
        component: The component identifier (use constants from this module)
        exception: The exception to log
        context: Optional context string for the error
        level: Log level (debug, info, warning, error, critical)
    """
    context_prefix = f"{context}: " if context else ""
    message = f"{context_prefix}{str(exception)}"
    
    if level == "debug":
        log_debug(component, message)
    elif level == "info":
        log_info(component, message)
    elif level == "warning":
        log_warning(component, message)
    elif level == "critical":
        log_critical(component, message, exc_info=True)
    else:
        log_error(component, message, exc_info=True)


class LogContext:
    """
    Context manager for standardized logging within a component.
    
    Example:
        with LogContext(PAYMENT, "processing invoice"):
            # Your code here
            # Automatically logs start and completion/error
    """
    
    def __init__(self, component: str, operation: str, log_level: str = "debug"):
        """
        Initialize the logging context.
        
        Args:
            component: The component identifier (use constants from this module)
            operation: Description of the operation being performed
            log_level: The log level to use for start/complete messages
        """
        self.component = component
        self.operation = operation
        self.log_level = log_level
        
    def __enter__(self):
        """Log the start of the operation."""
        if self.log_level == "debug":
            log_debug(self.component, f"Starting {self.operation}")
        elif self.log_level == "info":
            log_info(self.component, f"Starting {self.operation}")
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Log the completion or error of the operation."""
        if exc_val:
            log_exception(self.component, exc_val, f"Error in {self.operation}")
            return False
        
        if self.log_level == "debug":
            log_debug(self.component, f"Completed {self.operation}")
        elif self.log_level == "info":
            log_info(self.component, f"Completed {self.operation}")
        return True
