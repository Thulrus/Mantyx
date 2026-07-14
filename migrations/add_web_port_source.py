#!/usr/bin/env python3
"""Migration script to add web_port_source tracking field to App model.

Run this script to safely add the new field to existing installations.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from sqlalchemy import text

from mantyx.database import get_db, init_db


def migrate():
    """Add web_port_source column to apps table."""
    print("Starting migration: add web_port_source field...")

    # Initialize database
    init_db()

    with get_db() as session:
        result = session.execute(text("PRAGMA table_info(apps)"))
        columns = {row[1] for row in result}

        if "web_port_source" not in columns:
            session.execute(text("ALTER TABLE apps ADD COLUMN web_port_source VARCHAR(20)"))

            # Any app that already has a web_url/web_port set was populated by hand
            # (auto-detection didn't exist before this migration) — mark it "manual"
            # so the new port monitor never overwrites a value a user already configured.
            session.execute(
                text(
                    "UPDATE apps SET web_port_source = 'manual' "
                    "WHERE web_url IS NOT NULL OR web_port IS NOT NULL"
                )
            )

            session.commit()
            print("✓ Added web_port_source column and backfilled existing values as 'manual'")
        else:
            print("✓ Already applied")


if __name__ == "__main__":
    try:
        migrate()
        print("\n✓ Migration completed successfully!")
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        sys.exit(1)
