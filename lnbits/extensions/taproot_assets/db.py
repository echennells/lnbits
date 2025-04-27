"""
Database module for the Taproot Assets extension.
"""
from contextlib import asynccontextmanager
from lnbits.db import Connection, Database

# Create a database instance for the extension
db = Database("ext_taproot_assets")

# Add a custom reuse_conn method to our db instance
@asynccontextmanager
async def reuse_conn(conn):
    """
    Reuse an existing connection instead of creating a new one.
    This helps avoid nested transactions that can cause locking issues.
    """
    yield conn

# Monkey patch the method onto our db instance if it doesn't already exist
if not hasattr(db, 'reuse_conn'):
    db.reuse_conn = reuse_conn

# Helper function to get proper table name with schema only when needed
def get_table_name(base_name):
    """
    Get the properly formatted table name based on database type.
    
    Args:
        base_name: The base table name without schema
        
    Returns:
        str: Full table name with schema prefix if needed
    """
    if db.type in ["POSTGRES", "COCKROACH"]:
        return f"{db.schema}.{base_name}"
    else:  # SQLite
        return base_name

# Connect function that will be used during the migration process
# This needs to return the database instance itself, which already has the proper async context manager
def connect():
    """Connect to the database."""
    return db
