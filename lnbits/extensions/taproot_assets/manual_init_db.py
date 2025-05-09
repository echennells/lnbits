#!/usr/bin/env python3
"""
Manual database initialization script for the Taproot Assets extension.
This script creates the necessary database tables if they don't exist.
"""

import asyncio
import os
import sqlite3

# The path to the database file
DB_PATH = "/home/ubuntu/fresh/lnbits/data/ext_taproot_assets.sqlite3"

# SQL statements to create the tables

CREATE_ASSETS_TABLE = """
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    type TEXT NOT NULL,
    amount TEXT NOT NULL,
    genesis_point TEXT NOT NULL,
    meta_hash TEXT NOT NULL,
    version TEXT NOT NULL,
    is_spent BOOLEAN NOT NULL,
    script_key TEXT NOT NULL,
    channel_info TEXT,
    user_id TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT (strftime('%s', 'now')),
    updated_at TIMESTAMP NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

CREATE_INVOICES_TABLE = """
CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    payment_hash TEXT NOT NULL,
    payment_request TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    asset_amount INTEGER NOT NULL,
    satoshi_amount INTEGER NOT NULL,
    description TEXT,
    status TEXT NOT NULL,
    user_id TEXT NOT NULL,
    wallet_id TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT (strftime('%s', 'now')),
    expires_at TIMESTAMP,
    paid_at TIMESTAMP,
    buy_quote TEXT
);
"""

def init_db():
    """Initialize the database with the required tables."""
    print(f"Initializing database at {DB_PATH}")
    
    # Create the database directory if it doesn't exist
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    # Connect to the database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create the tables
    print("Creating assets table...")
    cursor.execute(CREATE_ASSETS_TABLE)
    
    print("Creating invoices table...")
    cursor.execute(CREATE_INVOICES_TABLE)
    
    # Commit the changes and close the connection
    conn.commit()
    conn.close()
    
    print("Database initialization complete!")

if __name__ == "__main__":
    init_db()
