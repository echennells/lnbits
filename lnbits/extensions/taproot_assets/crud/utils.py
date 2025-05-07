"""
Common database utilities for Taproot Assets CRUD operations.
"""
from typing import Any, Dict, List, Optional, Type, TypeVar, Union, Callable
from datetime import datetime
from pydantic import BaseModel

from lnbits.db import Database
from ..db import db, get_table_name
from ..db_utils import transaction

T = TypeVar('T', bound=BaseModel)

async def get_record_by_id(table: str, id: str, model_class: Type[T], conn=None) -> Optional[T]:
    """
    Get a record by ID from any table.
    
    Args:
        table: The table name (without prefix)
        id: The ID of the record to get
        model_class: The Pydantic model class to use for the result
        conn: Optional database connection to reuse
        
    Returns:
        The model instance if found, None otherwise
    """
    return await (conn or db).fetchone(
        f"SELECT * FROM {get_table_name(table)} WHERE id = :id",
        {"id": id},
        model_class
    )

async def get_record_by_field(
    table: str, 
    field: str, 
    value: Any, 
    model_class: Type[T], 
    conn=None
) -> Optional[T]:
    """
    Get a record by any field from any table.
    
    Args:
        table: The table name (without prefix)
        field: The field name to filter by
        value: The value to filter for
        model_class: The Pydantic model class to use for the result
        conn: Optional database connection to reuse
        
    Returns:
        The model instance if found, None otherwise
    """
    return await (conn or db).fetchone(
        f"SELECT * FROM {get_table_name(table)} WHERE {field} = :{field}",
        {field: value},
        model_class
    )

async def get_records_by_field(
    table: str, 
    field: str, 
    value: Any, 
    model_class: Type[T], 
    limit: int = 100,
    conn=None
) -> List[T]:
    """
    Get all records matching a field value from any table.
    
    Args:
        table: The table name (without prefix)
        field: The field name to filter by
        value: The value to filter for
        model_class: The Pydantic model class to use for the result
        limit: Maximum number of records to return
        conn: Optional database connection to reuse
        
    Returns:
        List of model instances
    """
    return await (conn or db).fetchall(
        f"""
        SELECT * FROM {get_table_name(table)} 
        WHERE {field} = :{field} 
        ORDER BY created_at DESC 
        LIMIT :limit
        """,
        {field: value, "limit": limit},
        model_class
    )

async def get_records_by_user(
    table: str, 
    user_id: str, 
    model_class: Type[T], 
    conn=None
) -> List[T]:
    """
    Get all records for a user from any table.
    
    Args:
        table: The table name (without prefix)
        user_id: The user ID to filter by
        model_class: The Pydantic model class to use for the result
        conn: Optional database connection to reuse
        
    Returns:
        List of model instances
    """
    return await get_records_by_field(table, "user_id", user_id, model_class, conn=conn)

async def execute_transaction(operations: Callable):
    """
    Execute multiple operations in a transaction.
    
    This function is deprecated in favor of using the transaction context manager
    or the with_transaction decorator from db_utils.py.
    
    Args:
        operations: A function that takes a database connection and performs operations
        
    Returns:
        The result of the operations function
    """
    async with transaction() as conn:
        return await operations(conn)
