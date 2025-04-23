from loguru import logger

async def m001_initial(db):
    """
    Initial database migration for the Taproot Assets extension.
    """
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS taproot_assets.settings (
            id TEXT PRIMARY KEY,
            tapd_host TEXT NOT NULL,
            tapd_network TEXT NOT NULL,
            tapd_tls_cert_path TEXT NOT NULL,
            tapd_macaroon_path TEXT NOT NULL,
            tapd_macaroon_hex TEXT,
            lnd_macaroon_path TEXT NOT NULL,
            lnd_macaroon_hex TEXT,
            default_sat_fee INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS taproot_assets.assets (
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
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS taproot_assets.invoices (
            id TEXT PRIMARY KEY,
            payment_hash TEXT NOT NULL,
            payment_request TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            asset_amount INTEGER NOT NULL,
            satoshi_amount INTEGER NOT NULL DEFAULT 1,
            memo TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            user_id TEXT NOT NULL,
            wallet_id TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            paid_at TIMESTAMP
        );
        """
    )


async def m002_add_sat_fee_column(db):
    """
    Migration to add default_sat_fee column to settings table if it doesn't exist.
    """
    try:
        # Check if the column exists - without schema prefix for SQLite
        columns = await db.fetchall(
            "SELECT name FROM pragma_table_info('settings')"
        )
        column_names = [col["name"] for col in columns]

        # Add column if it doesn't exist - without schema prefix for SQLite
        if "default_sat_fee" not in column_names:
            await db.execute(
                """
                ALTER TABLE settings
                ADD COLUMN default_sat_fee INTEGER NOT NULL DEFAULT 1;
                """
            )
            logger.info("Added default_sat_fee column to settings table")
        else:
            logger.debug("default_sat_fee column already exists in settings table")
    except Exception as e:
        logger.warning(f"Error in migration m002_add_sat_fee_column: {str(e)}")


async def m003_create_fee_transactions_table(db):
    """
    Migration to create a table for tracking sat fee transactions.
    """
    try:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS taproot_assets.fee_transactions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                wallet_id TEXT NOT NULL,
                asset_payment_hash TEXT NOT NULL,
                fee_amount_msat INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        logger.info("Created taproot_assets.fee_transactions table")
    except Exception as e:
        logger.warning(f"Error in migration m003_create_fee_transactions_table: {str(e)}")


async def m004_create_payments_table(db):
    """
    Migration to create a table for tracking sent payments of Taproot Assets.
    """
    try:
        # Create the payments table with indices
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS taproot_assets.payments (
                id TEXT PRIMARY KEY,
                payment_hash TEXT NOT NULL,
                payment_request TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                asset_amount INTEGER NOT NULL,
                fee_sats INTEGER NOT NULL DEFAULT 0,
                memo TEXT,
                status TEXT NOT NULL DEFAULT 'completed',
                user_id TEXT NOT NULL,
                wallet_id TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                preimage TEXT
            );
            """
        )
        
        # Add index on payment_hash for faster lookups - without schema prefix
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS payments_payment_hash_idx 
            ON payments (payment_hash);
            """
        )
        
        # Add index on user_id for faster user-specific queries - without schema prefix
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS payments_user_id_idx 
            ON payments (user_id);
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
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS taproot_assets.asset_balances (
                id TEXT PRIMARY KEY,
                wallet_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                balance INTEGER NOT NULL DEFAULT 0,
                last_payment_hash TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(wallet_id, asset_id)
            );
            """
        )

        # Create indexes without schema prefix for SQLite
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS asset_balances_wallet_id_idx
            ON asset_balances (wallet_id);
            """
        )

        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS asset_balances_asset_id_idx
            ON asset_balances (asset_id);
            """
        )

        # Create transaction history table
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS taproot_assets.asset_transactions (
                id TEXT PRIMARY KEY,
                wallet_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                payment_hash TEXT,
                amount INTEGER NOT NULL,
                fee INTEGER DEFAULT 0,
                memo TEXT,
                type TEXT NOT NULL,  -- 'credit', 'debit'
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        logger.info("Created asset_balances and asset_transactions tables")
    except Exception as e:
        logger.warning(f"Error in migration m005_create_asset_balances_table: {str(e)}")
