#!/usr/bin/env python3
"""
Migration script to add update tracking fields to App model.

Run this script to safely add the new fields to existing installations.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from sqlalchemy import text

from mantyx.database import get_db, init_db


def migrate():
    """Add update tracking fields to apps table."""
    print("Starting migration: add update tracking fields...")

    # Initialize database
    init_db()

    with get_db() as session:
        # Check if columns already exist
        result = session.execute(text("PRAGMA table_info(apps)"))
        columns = {row[1] for row in result}

        migrations_needed = []

        if "last_updated_at" not in columns:
            migrations_needed.append("ALTER TABLE apps ADD COLUMN last_updated_at DATETIME")

        if "update_count" not in columns:
            migrations_needed.append("ALTER TABLE apps ADD COLUMN update_count INTEGER DEFAULT 0")

        if not migrations_needed:
            print("✓ All columns already exist. No migration needed.")
            return

        # Apply migrations
        for migration in migrations_needed:
            print(f"Executing: {migration}")
            session.execute(text(migration))

        session.commit()
        print(f"✓ Successfully added {len(migrations_needed)} column(s)")


if __name__ == "__main__":
    try:
        migrate()
        print("\n✓ Migration completed successfully!")
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        sys.exit(1)
