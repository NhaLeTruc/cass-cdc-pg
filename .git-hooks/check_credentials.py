#!/usr/bin/env python3
"""
Pre-commit hook to detect hardcoded credentials in code.
Prevents committing passwords, API keys, tokens, and other secrets.
"""

import re
import sys
from pathlib import Path

# Patterns that indicate potential credentials
CREDENTIAL_PATTERNS = [
    # Generic secrets
    (r'password\s*=\s*["\'][^"\']{3,}["\']', "hardcoded password"),
    (r'passwd\s*=\s*["\'][^"\']{3,}["\']', "hardcoded password"),
    (r'pwd\s*=\s*["\'][^"\']{3,}["\']', "hardcoded password"),
    (r'secret\s*=\s*["\'][^"\']{3,}["\']', "hardcoded secret"),
    (r'api_key\s*=\s*["\'][^"\']{3,}["\']', "hardcoded API key"),
    (r'apikey\s*=\s*["\'][^"\']{3,}["\']', "hardcoded API key"),
    (r'token\s*=\s*["\'][^"\']{3,}["\']', "hardcoded token"),
    (r'access_token\s*=\s*["\'][^"\']{3,}["\']', "hardcoded access token"),

    # AWS credentials
    (r'AKIA[0-9A-Z]{16}', "AWS access key"),
    (r'aws_secret_access_key\s*=\s*["\'][^"\']{20,}["\']', "AWS secret key"),

    # Database connection strings with embedded credentials
    (r'://[^:]+:[^@]+@', "database URL with credentials"),
    (r'postgresql://.*:.*@', "PostgreSQL URL with credentials"),
    (r'mongodb://.*:.*@', "MongoDB URL with credentials"),

    # Private keys
    (r'-----BEGIN (RSA |DSA )?PRIVATE KEY-----', "private key"),
    (r'-----BEGIN OPENSSH PRIVATE KEY-----', "OpenSSH private key"),

    # Generic base64 secrets (32+ chars)
    (r'["\'][A-Za-z0-9+/]{32,}={0,2}["\']', "potential base64 encoded secret"),

    # JWT tokens
    (r'eyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*', "JWT token"),
]

# Patterns that are safe (exclude false positives)
SAFE_PATTERNS = [
    r'password\s*=\s*["\']changeme["\']',  # Placeholder
    r'password\s*=\s*["\']password["\']',  # Placeholder
    r'password\s*=\s*["\']<.*>["\']',      # Template
    r'password\s*=\s*["\']example["\']',   # Example
    r'password\s*=\s*["\']test["\']',      # Test value
    r'password\s*=\s*os\.getenv',          # From environment
    r'password\s*=\s*os\.environ',         # From environment
    r'password.*\$\{.*\}',                 # Template variable
    r'password.*VAULT',                    # From Vault
    r'password.*SECRET',                   # From secret manager
]


def is_safe_match(line: str) -> bool:
    """Check if the line matches a safe pattern (false positive)."""
    for pattern in SAFE_PATTERNS:
        if re.search(pattern, line, re.IGNORECASE):
            return True
    return False


def check_file(filepath: str) -> list[tuple[int, str, str]]:
    """
    Check a file for credential patterns.
    Returns list of (line_number, line_content, violation_type).
    """
    violations = []

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, start=1):
                # Skip if it's a safe pattern
                if is_safe_match(line):
                    continue

                # Check against credential patterns
                for pattern, violation_type in CREDENTIAL_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        violations.append((line_num, line.strip(), violation_type))
                        break  # Only report first match per line

    except UnicodeDecodeError:
        # Skip binary files
        pass
    except Exception as e:
        print(f"⚠️  Warning: Could not read {filepath}: {e}", file=sys.stderr)

    return violations


def main(filenames: list[str]) -> int:
    """
    Check files for hardcoded credentials.
    Returns 0 if no credentials found, 1 otherwise.
    """
    all_violations = {}

    for filename in filenames:
        violations = check_file(filename)
        if violations:
            all_violations[filename] = violations

    if all_violations:
        print("❌ ERROR: Hardcoded credentials detected!\n")
        print("⚠️  SECURITY RISK: Never commit passwords, API keys, or secrets to Git.\n")

        for filepath, violations in all_violations.items():
            print(f"📄 {filepath}:")
            for line_num, line_content, violation_type in violations:
                print(f"   Line {line_num}: {violation_type}")
                print(f"   > {line_content}")
            print()

        print("💡 Solutions:")
        print("  1. Use environment variables:")
        print("     password = os.getenv('DB_PASSWORD')")
        print("  2. Use HashiCorp Vault:")
        print("     password = vault_client.get_secret('postgres/password')")
        print("  3. Use configuration files (add to .gitignore):")
        print("     password = config['database']['password']")
        print("  4. For test/example values, use placeholders:")
        print("     password = 'changeme'  # This is allowed")
        print("\n  Remove the credentials and retry your commit.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
