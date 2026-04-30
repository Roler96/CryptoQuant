"""Main entry point for python -m cryptoquant."""

import sys
from pathlib import Path

# Add parent directory to path to find cli module
sys.path.insert(0, str(Path(__file__).parent.parent))

from cli.main import main

if __name__ == "__main__":
    sys.exit(main())
