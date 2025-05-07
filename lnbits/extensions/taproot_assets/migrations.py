from loguru import logger
from .db import get_table_name

async def m001_initial(db):
    """
    Initial database migration for the Taproot Assets extension.
    Creates required tables except for settings which are now handled via environment variables.
    """
    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {get_table_name("assets")} (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            type TEXT NOT NULL,
            amount TEXT NOT NULL,
            genesis_point TEXT NOT NULL,
            meta_hash TEXT NOT NULL,
            version TEXT NOT NULL,
            is_spent BOOLEAN NOT NULL DEFAULT FALSE,
            script_key TEXT NOT NULL,
            channel_info TEXT, -- JSON encoded channel info
            user_id TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now},
            updated_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now}
        );
        """
    )

    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {get_table_name("invoices")} (
            id TEXT PRIMARY KEY,
            payment_hash TEXT NOT NULL,
            payment_request TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            asset_amount {db.big_int} NOT NULL,
            satoshi_amount {db.big_int} NOT NULL DEFAULT 1,
            memo TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            user_id TEXT NOT NULL,
            wallet_id TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now},
            expires_at TIMESTAMP,
            paid_at TIMESTAMP
        );
        """
    )


async def m003_create_fee_transactions_table(db):
    """
    Migration to create a table for tracking sat fee transactions.
    """
    try:
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {get_table_name("fee_transactions")} (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                wallet_id TEXT NOT NULL,
                asset_payment_hash TEXT NOT NULL,
                fee_amount_msat {db.big_int} NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now}
            );
            """
        )
        logger.info(f"Created fee_transactions table")
    except Exception as e:
        logger.warning(f"Error in migration m003_create_fee_transactions_table: {str(e)}")


async def m004_create_payments_table(db):
    """
    Migration to create a table for tracking sent payments of Taproot Assets.
    """
    try:
        # Create the payments table with indices
        payments_table = get_table_name("payments")
        
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {payments_table} (
                id TEXT PRIMARY KEY,
                payment_hash TEXT NOT NULL,
                payment_request TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                asset_amount {db.big_int} NOT NULL,
                fee_sats {db.big_int} NOT NULL DEFAULT 0,
                memo TEXT,
                status TEXT NOT NULL DEFAULT 'completed',
                user_id TEXT NOT NULL,
                wallet_id TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now},
                preimage TEXT
            );
            """
        )
        
        # Add index on payment_hash for faster lookups
        # Use table name without schema for SQLite
        index_table = payments_table.split(".")[-1] if db.type == "SQLITE" else payments_table
        
        await db.execute(
            f"""
            CREATE INDEX IF NOT EXISTS payments_payment_hash_idx 
            ON {index_table} (payment_hash);
            """
        )
        
        # Add index on user_id for faster user-specific queries
        await db.execute(
            f"""
            CREATE INDEX IF NOT EXISTS payments_user_id_idx 
            ON {index_table} (user_id);
            """
        )
        
        logger.info("Created payments table with indices")
    except Exception as e:
        # Log just the error message without a full stack trace for migrations
        logger.warning(f"Error in migration m004_create_payments_table: {str(e)}")


async def m005_create_asset_balances_table(db):
    """
    Migration to create a table for tracking user asset balances.
    """
    try:
        # Create the asset_balances table
        balances_table = get_table_name("asset_balances")
        
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {balances_table} (
                id TEXT PRIMARY KEY,
                wallet_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                balance {db.big_int} NOT NULL DEFAULT 0,
                last_payment_hash TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now},
                updated_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now},
                UNIQUE(wallet_id, asset_id)
            );
            """
        )

        # Create indexes for asset_balances
        # Use table name without schema for SQLite
        index_table = balances_table.split(".")[-1] if db.type == "SQLITE" else balances_table
        
        await db.execute(
            f"""
            CREATE INDEX IF NOT EXISTS asset_balances_wallet_id_idx
            ON {index_table} (wallet_id);
            """
        )

        await db.execute(
            f"""
            CREATE INDEX IF NOT EXISTS asset_balances_asset_id_idx
            ON {index_table} (asset_id);
            """
        )

        # Create transaction history table
        transactions_table = get_table_name("asset_transactions")
        
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {transactions_table} (
                id TEXT PRIMARY KEY,
                wallet_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                payment_hash TEXT,
                amount {db.big_int} NOT NULL,
                fee {db.big_int} DEFAULT 0,
                memo TEXT,
                type TEXT NOT NULL,  -- 'credit', 'debit'
                created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now}
            );
            """
        )

        logger.info("Created asset_balances and asset_transactions tables")
    except Exception as e:
        logger.warning(f"Error in migration m005_create_asset_balances_table: {str(e)}")


async def m006_add_asset_indexes(db):
    """
    Migration to add indexes for better query performance.
    """
    try:
        # Define tables
        assets_table = get_table_name("assets")
        invoices_table = get_table_name("invoices")
        transactions_table = get_table_name("asset_transactions")
        
        # Use table names without schema for SQLite indexes
        assets_index_table = assets_table.split(".")[-1] if db.type == "SQLITE" else assets_table
        invoices_index_table = invoices_table.split(".")[-1] if db.type == "SQLITE" else invoices_table
        transactions_index_table = transactions_table.split(".")[-1] if db.type == "SQLITE" else transactions_table
        
        # Add indexes for assets table
        await db.execute(
            f"""
            CREATE INDEX IF NOT EXISTS assets_asset_id_idx
            ON {assets_index_table} (asset_id);
            """
        )

        await db.execute(
            f"""
            CREATE INDEX IF NOT EXISTS assets_user_id_idx
            ON {assets_index_table} (user_id);
            """
        )

        # Add indexes for invoices table
        await db.execute(
            f"""
            CREATE INDEX IF NOT EXISTS invoices_payment_hash_idx
            ON {invoices_index_table} (payment_hash);
            """
        )

        await db.execute(
            f"""
            CREATE INDEX IF NOT EXISTS invoices_user_id_idx
            ON {invoices_index_table} (user_id);
            """
        )

        await db.execute(
            f"""
            CREATE INDEX IF NOT EXISTS invoices_status_idx
            ON {invoices_index_table} (status);
            """
        )

        # Add indexes for asset_transactions table
        await db.execute(
            f"""
            CREATE INDEX IF NOT EXISTS asset_transactions_wallet_id_idx
            ON {transactions_index_table} (wallet_id);
            """
        )

        await db.execute(
            f"""
            CREATE INDEX IF NOT EXISTS asset_transactions_asset_id_idx
            ON {transactions_index_table} (asset_id);
            """
        )

        await db.execute(
            f"""
            CREATE INDEX IF NOT EXISTS asset_transactions_payment_hash_idx
            ON {transactions_index_table} (payment_hash);
            """
        )

        await db.execute(
            f"""
            CREATE INDEX IF NOT EXISTS asset_transactions_created_at_idx
            ON {transactions_index_table} (created_at);
            """
        )

        logger.info("Added performance indexes for Taproot Assets tables")
    except Exception as e:
        logger.warning(f"Error in migration m006_add_asset_indexes: {str(e)}")
