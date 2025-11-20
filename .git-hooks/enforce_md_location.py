#!/usr/bin/env python3
"""
Pre-commit hook to enforce .md files are in docs/ directory.
Exceptions: README.md, CLAUDE.md at root, and .specify/*, specs/* directories.
"""

import sys
from pathlib import Path

# Files that ARE allowed in root or their specific directories
ALLOWED_PATTERNS = [
    "README.md",
    "CLAUDE.md",
    ".specify/**/*.md",  # Specify framework docs
    "specs/**/*.md",     # Feature specification docs
    "docs/**/*.md",      # Target location for all other .md files
]


def is_allowed(filepath: str) -> bool:
    """Check if .md file is in an allowed location."""
    path = Path(filepath)

    # Allow README.md and CLAUDE.md in root
    if path.name in ["README.md", "CLAUDE.md"] and len(path.parts) == 1:
        return True

    # Allow .md files in .specify/ directory (framework documentation)
    if ".specify" in path.parts:
        return True

    # Allow .md files in specs/ directory (feature specifications)
    if "specs" in path.parts:
        return True

    # Allow .md files in docs/ directory (target location)
    if "docs" in path.parts:
        return True

    return False


def main(filenames: list[str]) -> int:
    """
    Check that .md files are in allowed locations.
    Returns 0 if all files are in allowed locations, 1 otherwise.
    """
    violations = []

    for filename in filenames:
        if filename.endswith(".md") and not is_allowed(filename):
            violations.append(filename)

    if violations:
        print("❌ ERROR: Markdown files must be in docs/ directory")
        print("   (except README.md and CLAUDE.md in root)\n")
        print("Violations found:")
        for filepath in violations:
            print(f"  - {filepath}")
        print("\n💡 Solution:")
        print("  Move these files to docs/ directory:")
        for filepath in violations:
            suggested = f"docs/{Path(filepath).name}"
            print(f"    git mv {filepath} {suggested}")
        print("\n  Then retry your commit.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
