# Mantyx Database Migrations

This directory contains database migration scripts that are automatically run during deployment.

## How Migrations Work

1. **Automatic in Development**: When you run Mantyx locally, SQLAlchemy's `create_all()` automatically adds new columns/tables
2. **Automatic on Deploy**: The `deploy.sh` script automatically runs all migration scripts in this folder before restarting the service
3. **Idempotent**: All migrations check if changes are already applied before running

## Current Migrations

### add_update_fields.py

**Added**: 2026-01-18  
**Purpose**: Add update tracking fields to the App model

- Adds `last_updated_at` column (tracks when app was last updated)
- Adds `update_count` column (counts number of updates)

## Creating New Migrations

When you add new database fields or make schema changes:

1. **Update the model** in `src/mantyx/models/`
2. **Create a migration script** in this directory:

   ```python
   #!/usr/bin/env python3
   """Migration description."""

   import sys
   from pathlib import Path
   from sqlalchemy import text

   # Add project root to path
   project_root = Path(__file__).parent.parent
   sys.path.insert(0, str(project_root / "src"))

   from mantyx.database import get_db, init_db

   def migrate():
       """Apply migration."""
       print("Starting migration: your_migration_name...")
       init_db()

       with get_db() as session:
           # Check if changes already applied
           result = session.execute(text("PRAGMA table_info(your_table)"))
           columns = {row[1] for row in result}

           if "new_column" not in columns:
               session.execute(text(
                   "ALTER TABLE your_table ADD COLUMN new_column TYPE DEFAULT value"
               ))
               session.commit()
               print("✓ Migration applied")
           else:
               print("✓ Already applied")

   if __name__ == "__main__":
       try:
           migrate()
       except Exception as e:
           print(f"✗ Migration failed: {e}")
           sys.exit(1)
   ```

3. **Test locally**:

   ```bash
   .venv/bin/python migrations/your_migration.py
   ```

4. **Deploy**: The migration will run automatically on your server

## Migration Best Practices

✅ **DO**:

- Make migrations idempotent (safe to run multiple times)
- Check if changes already exist before applying
- Provide clear success/failure messages
- Use transactions where possible

❌ **DON'T**:

- Delete or modify existing migrations
- Make destructive changes without backups
- Assume specific data exists

## SQLAlchemy Auto-migration

For most simple additions (new columns, new tables), you don't need manual migrations:

- SQLAlchemy's `Base.metadata.create_all()` handles new columns automatically
- Use manual migrations for:
  - Data transformations
  - Column renames/deletions
  - Complex schema changes
  - Setting non-null defaults on existing data

## Troubleshooting

**Migration fails on server?**

```bash
# SSH to server and check logs
ssh user@server
cd /path/to/mantyx
MANTYX_BASE_DIR=./mantyx_data .venv/bin/python migrations/migration_name.py
```

**Need to rollback?**

- Migrations don't have automatic rollback
- Use your backups: `mantyx_data/backups/`
- Or manually revert database changes
