"""
Database utilities for the Taproot Assets extension.
Provides transaction management and connection pooling.
"""
import asyncio
import functools
import time
import random
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, Optional, TypeVar, cast
from loguru import logger

from sqlalchemy.ext.asyncio import AsyncConnection

from .db import db

# Use a semaphore instead of a lock to allow multiple concurrent transactions
# but limit the total number to prevent overloading the database
_transaction_semaphore = asyncio.Semaphore(5)  # Allow up to 5 concurrent transactions

# Type variable for generic function return types
T = TypeVar('T')

class ConnectionPoolManager:
    """
    Manages SQLAlchemy connection pools for better performance and reliability.
    
    This class enhances SQLAlchemy's built-in connection pooling with additional
    monitoring and management capabilities.
    """
    def __init__(self, database):
        """
        Initialize the connection pool manager.
        
        Args:
            database: The Database instance to manage
        """
        self.db = database
        self.stats = {
            'connections_created': 0,
            'connections_reused': 0,
            'transactions_started': 0,
            'transactions_committed': 0,
            'transactions_rolled_back': 0,
            'last_reset': time.time()
        }
        
        # SQLAlchemy already has connection pooling configured
        # We're just adding monitoring and management on top
        logger.info("Connection pool manager initialized")
    
    def _increment_stat(self, stat_name: str) -> None:
        """Increment a specific statistic counter."""
        if stat_name in self.stats:
            self.stats[stat_name] += 1


# Create a singleton instance of the connection pool manager
connection_pool = ConnectionPoolManager(db)


@asynccontextmanager
async def transaction(conn=None, max_retries=3, retry_delay=0.1):
    """
    Transaction context manager for atomic operations with retry capability.
    
    This context manager ensures that multiple database operations are executed
    within a single transaction, with proper commit and rollback handling.
    It uses a semaphore to limit concurrent transactions and implements
    exponential backoff retry logic for handling contention.
    
    Args:
        conn: Optional existing connection to reuse
        max_retries: Maximum number of retry attempts for the transaction
        retry_delay: Initial delay between retries (will increase exponentially)
        
    Yields:
        A database connection with an active transaction
        
    Example:
        ```python
        async with transaction() as conn:
            # All operations here are in a single transaction
            await conn.execute("INSERT INTO...")
            await conn.execute("UPDATE...")
            # Auto-commits on exit if no exceptions
        ```
    """
    connection_pool._increment_stat('transactions_started')
    
    # If we're reusing a connection, we don't need to acquire the semaphore
    # as it should have been acquired by the parent transaction
    need_semaphore = conn is None
    
    # Track if we acquired the semaphore so we know whether to release it
    semaphore_acquired = False
    
    # Implement retry logic with exponential backoff
    retry_count = 0
    current_delay = retry_delay
    
    while True:
        try:
            # Acquire the semaphore if needed
            if need_semaphore:
                await _transaction_semaphore.acquire()
                semaphore_acquired = True
                logger.debug(f"Transaction semaphore acquired (available: {_transaction_semaphore._value})")
            
            if conn is not None:
                # Reuse the existing connection
                connection_pool._increment_stat('connections_reused')
                try:
                    yield conn
                    connection_pool._increment_stat('transactions_committed')
                    break  # Success, exit the retry loop
                except Exception as e:
                    connection_pool._increment_stat('transactions_rolled_back')
                    logger.error(f"Transaction failed (reused connection): {str(e)}")
                    raise
            else:
                # Get a new connection with a transaction
                async with db.connect() as new_conn:
                    connection_pool._increment_stat('connections_created')
                    try:
                        yield new_conn
                        # The connection context manager will commit automatically
                        connection_pool._increment_stat('transactions_committed')
                        break  # Success, exit the retry loop
                    except Exception as e:
                        # The connection context manager will rollback automatically
                        connection_pool._increment_stat('transactions_rolled_back')
                        
                        # Check if this is a database lock error that we should retry
                        error_str = str(e).lower()
                        if ("database is locked" in error_str or 
                            "deadlock detected" in error_str or 
                            "could not serialize access" in error_str):
                            
                            retry_count += 1
                            if retry_count <= max_retries:
                                # Release the semaphore before retrying
                                if semaphore_acquired:
                                    _transaction_semaphore.release()
                                    semaphore_acquired = False
                                    logger.debug(f"Transaction semaphore released for retry (available: {_transaction_semaphore._value})")
                                
                                # Add some randomness to avoid all retries happening at the same time
                                jitter = random.uniform(0, 0.1)
                                wait_time = current_delay + jitter
                                
                                logger.warning(f"Database contention detected, retrying in {wait_time:.2f}s (attempt {retry_count}/{max_retries})")
                                await asyncio.sleep(wait_time)
                                
                                # Exponential backoff
                                current_delay *= 2
                                continue
                            else:
                                logger.error(f"Max retries ({max_retries}) exceeded for transaction")
                        
                        # Either not a retryable error or max retries exceeded
                        logger.error(f"Transaction failed (new connection): {str(e)}")
                        raise
        
        except Exception as outer_e:
            # Handle any exceptions that weren't caught in the inner try/except
            if retry_count < max_retries:
                retry_count += 1
                logger.warning(f"Transaction error, retrying ({retry_count}/{max_retries}): {str(outer_e)}")
                await asyncio.sleep(current_delay)
                current_delay *= 2
                continue
            raise
        
        finally:
            # Always release the semaphore if we acquired it
            if semaphore_acquired:
                _transaction_semaphore.release()
                logger.debug(f"Transaction semaphore released (available: {_transaction_semaphore._value})")
                semaphore_acquired = False


def with_transaction(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to wrap a function in a transaction.
    
    This decorator ensures that the decorated function is executed within
    a transaction, with proper commit and rollback handling.
    
    Args:
        func: The async function to wrap in a transaction
        
    Returns:
        Wrapped function that executes within a transaction
        
    Example:
        ```python
        @with_transaction
        async def update_user_balance(user_id, amount, conn=None):
            # All operations here are in a single transaction
            balance = await get_balance(user_id, conn=conn)
            balance.amount += amount
            await update_balance(balance, conn=conn)
            await record_transaction(user_id, amount, conn=conn)
        ```
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # Check if a connection was provided
        conn = kwargs.get('conn')
        
        if conn is not None:
            # If a connection was provided, just call the function
            return await func(*args, **kwargs)
        else:
            # Otherwise, create a transaction and call the function
            async with transaction() as new_conn:
                # Add the connection to the kwargs
                kwargs['conn'] = new_conn
                return await func(*args, **kwargs)
    
    return wrapper
