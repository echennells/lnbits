from lnbits.db import Connection


async def m001_initial(db: Connection):
    """
    Initial taproot_assets tables.
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
            lnd_macaroon_hex TEXT
        );
        """
    )

    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS taproot_assets.assets (
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
            created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now},
            updated_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now}
        );
        """
    )

    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS taproot_assets.invoices (
            id TEXT PRIMARY KEY,
            payment_hash TEXT NOT NULL,
            payment_request TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            asset_amount INTEGER NOT NULL,
            satoshi_amount INTEGER NOT NULL,
            memo TEXT,
            status TEXT NOT NULL,
            user_id TEXT NOT NULL,
            wallet_id TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now},
            expires_at TIMESTAMP,
            paid_at TIMESTAMP,
            buy_quote TEXT
        );
        """
    )
