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

# This is the database schema for the Taproot Assets extension
# The actual tables are created in the migrations.py file

# Define the database schema version
async def get_schema_version(db: Connection) -> int:
    """Get the current schema version."""
    row = await db.fetchone("SELECT version FROM dbversions WHERE db = ?", ("taproot_assets",))
    return row[0] if row else 0

# Connect function that will be used during the migration process
# This needs to return the database instance itself, which already has the proper async context manager
def connect():
    """Connect to the database."""
    return db
