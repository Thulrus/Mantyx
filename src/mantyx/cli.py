"""
CLI entry point for Mantyx.
"""

import sys

from mantyx.app import run
from mantyx.config import get_settings


def main():
    """Main CLI entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        run()
    else:
        print("Mantyx - Python Application Orchestration Framework")
        print()
        print("Usage:")
        print("  mantyx run    Start the Mantyx server")
        print()
        print(f"Configuration:")
        settings = get_settings()
        print(f"  Base directory: {settings.base_dir}")
        print(f"  Database: {settings.effective_database_url}")
        print(f"  Server: {settings.host}:{settings.port}")


if __name__ == "__main__":
    main()
