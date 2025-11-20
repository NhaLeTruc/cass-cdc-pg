# Git Hooks Enforcement Guide

This document describes the automated enforcement mechanisms for code quality, security, and project organization.

## Overview

Three critical requirements are enforced automatically via pre-commit hooks:

1. **Markdown File Location**: All `.md` files (except `README.md` and `CLAUDE.md`) must be in `docs/` directory
2. **Credential Prevention**: No hardcoded passwords, API keys, or secrets can be committed
3. **Code Linting**: All code must pass linting checks before commits

## Installation

### First-Time Setup

```bash
# Install pre-commit framework
pip install pre-commit

# Install the git hooks
pre-commit install

# (Optional) Test hooks without committing
pre-commit run --all-files
```

### Verify Installation

```bash
# Check that hooks are installed
pre-commit --version

# List installed hooks
cat .git/hooks/pre-commit
```

---

## Enforcement Mechanism 1: Markdown File Location

### Rule

All `.md` files MUST be in `docs/` directory, with only two exceptions:
- `README.md` (root directory)
- `CLAUDE.md` (root directory)
- Files in `.specify/` directory (framework documentation)
- Files in `specs/` directory (feature specifications)

### How It Works

The `enforce_md_location.py` hook runs before every commit and checks:
1. Scans all staged `.md` files
2. Verifies they are in allowed locations
3. Blocks commit if violations found

### Example Violation

```bash
git add my-notes.md
git commit -m "Add notes"

# OUTPUT:
# ❌ ERROR: Markdown files must be in docs/ directory
#    (except README.md and CLAUDE.md in root)
#
# Violations found:
#   - my-notes.md
#
# 💡 Solution:
#   Move these files to docs/ directory:
#     git mv my-notes.md docs/my-notes.md
#
#   Then retry your commit.
```

### Correct Usage

```bash
# Create or move .md files to docs/
git mv my-notes.md docs/my-notes.md
git add docs/my-notes.md
git commit -m "Add notes"  # ✅ SUCCESS
```

### Allowed Locations

| Location | Allowed | Reason |
|----------|---------|--------|
| `README.md` | ✅ Yes | Project overview |
| `CLAUDE.md` | ✅ Yes | AI agent context |
| `docs/*.md` | ✅ Yes | Target location |
| `.specify/**/*.md` | ✅ Yes | Framework docs |
| `specs/**/*.md` | ✅ Yes | Feature specs |
| `my-file.md` (root) | ❌ No | Must be in docs/ |
| `src/notes.md` | ❌ No | Must be in docs/ |

---

## Enforcement Mechanism 2: Credential Prevention

### Rule

NO hardcoded credentials, passwords, API keys, tokens, or secrets can be committed to Git.

### How It Works

Two layers of protection:

1. **detect-secrets** (industry-standard tool):
   - Scans for 20+ types of secrets (AWS keys, JWT tokens, private keys, etc.)
   - Uses entropy detection for unknown secret patterns
   - Maintains baseline of known false positives

2. **check_credentials.py** (custom hook):
   - Checks for common credential patterns in code
   - Detects database URLs with embedded credentials
   - Validates safe patterns (environment variables, Vault references)

### Example Violations

```python
# ❌ BLOCKED - Hardcoded password
password = "my_secret_password"

# ❌ BLOCKED - API key in code
api_key = "sk-1234567890abcdef"

# ❌ BLOCKED - Database URL with credentials
db_url = "postgresql://user:password@localhost:5432/db"

# ❌ BLOCKED - AWS access key
aws_access_key = "AKIAIOSFODNN7EXAMPLE"

# ❌ BLOCKED - Private key
private_key = """
-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA...
-----END RSA PRIVATE KEY-----
"""
```

### Correct Alternatives

```python
# ✅ ALLOWED - Environment variable
password = os.getenv("DB_PASSWORD")

# ✅ ALLOWED - Vault integration
password = vault_client.get_secret("postgres/password")

# ✅ ALLOWED - Configuration file (must be in .gitignore)
password = config["database"]["password"]

# ✅ ALLOWED - Placeholder for examples
password = "changeme"  # This is a safe placeholder
password = "<your-password-here>"  # Template

# ✅ ALLOWED - Test/example values
password = "test"  # For test environments
password = "example"  # For documentation
```

### If Hook Blocks Valid Code

If the hook incorrectly flags valid code (false positive):

1. **For detect-secrets**:
   ```bash
   # Update baseline to whitelist the line
   detect-secrets scan --baseline .secrets.baseline
   ```

2. **For custom check**:
   - Use environment variables instead: `os.getenv('VAR')`
   - Reference Vault: `vault_client.get_secret()`
   - Add comment to clarify: `# password from environment`

### Testing Credential Detection

```bash
# Test if credentials would be detected
echo 'password = "secret123"' > test.py
pre-commit run check-credentials --files test.py

# Should output: ❌ ERROR: Hardcoded credentials detected!
```

---

## Enforcement Mechanism 3: Code Linting

### Rule

All code MUST pass linting checks before commits. This includes:
- **Black**: Code formatting (line length 100)
- **Ruff**: Fast Python linter (replaces flake8, isort, pyupgrade)
- **mypy**: Static type checking
- **Bandit**: Security linting
- **Hadolint**: Dockerfile linting
- **Shellcheck**: Shell script linting

### How It Works

1. **Black** auto-formats Python code to consistent style
2. **Ruff** checks for:
   - Unused imports
   - Undefined variables
   - Syntax errors
   - Code complexity
   - Best practice violations
3. **mypy** validates type hints and catches type errors
4. **Bandit** scans for security issues (SQL injection, hardcoded passwords, etc.)
5. **Hadolint** lints Dockerfiles for best practices
6. **Shellcheck** checks shell scripts for bugs and anti-patterns

### Example Violations

```python
# ❌ BLOCKED - Unused import (Ruff)
import os  # Not used anywhere

# ❌ BLOCKED - Line too long (Black)
very_long_variable_name = "This is a very long string that exceeds the 100 character line length limit and should be broken"

# ❌ BLOCKED - Undefined variable (Ruff)
print(undefined_variable)

# ❌ BLOCKED - Missing type hints (mypy in strict mode)
def process_data(data):  # No type hints
    return data

# ❌ BLOCKED - SQL injection risk (Bandit)
query = f"SELECT * FROM users WHERE id = {user_id}"  # Use parameterized queries!
```

### Auto-Fixes

Many issues are **automatically fixed** by pre-commit:

```bash
git add file.py
git commit -m "Update code"

# OUTPUT:
# black....................................................................Passed
# ruff.....................................................................Fixed
# - Fixed 3 issues (removed unused imports, sorted imports)
#
# Files were modified by this hook. Verify changes and re-stage:
#   git add file.py
#   git commit -m "Update code"
```

### Manual Fixes Required

Some issues need manual fixing:

```bash
# OUTPUT:
# mypy.....................................................................Failed
# - src/services/event_processor.py:42: error: Missing return statement
# - src/services/validator.py:15: error: Argument 1 has incompatible type
#
# Fix these issues and retry your commit.
```

### Bypass Linting (NOT RECOMMENDED)

In rare cases where you need to bypass hooks:

```bash
# Skip all hooks (DANGEROUS - use sparingly!)
git commit --no-verify -m "Emergency fix"

# Better: Skip specific hooks
SKIP=mypy git commit -m "WIP: type hints incomplete"
```

**⚠️ WARNING**: Bypassing hooks defeats the purpose of quality enforcement. Only use in emergencies.

### Configuration Files

Linting behavior is configured in:

| Tool | Config File | Purpose |
|------|-------------|---------|
| Black | `pyproject.toml` | Code formatting rules |
| Ruff | `.ruff.toml` | Linting rules and exclusions |
| mypy | `mypy.ini` | Type checking strictness |
| Bandit | `pyproject.toml` | Security scan rules |
| pre-commit | `.pre-commit-config.yaml` | Hook orchestration |

---

## Additional Safety Checks

The pre-commit configuration includes several other checks:

### File Quality
- ✅ Trim trailing whitespace
- ✅ Fix end-of-file (ensure newline)
- ✅ Check YAML/JSON/TOML syntax
- ✅ Detect merge conflicts
- ✅ Prevent large files (>500KB)
- ✅ Check mixed line endings

### Branch Protection
- ✅ Prevent direct commits to `main`/`master` branches
  ```bash
  # This will be blocked:
  git checkout main
  git commit -m "Fix"

  # ERROR: Committing to main is not allowed.
  # Create a feature branch instead:
  git checkout -b fix/my-fix
  ```

---

## Troubleshooting

### Hook Not Running

```bash
# Reinstall hooks
pre-commit uninstall
pre-commit install

# Verify installation
ls -la .git/hooks/pre-commit
```

### Hook Failing to Execute

```bash
# Check Python environment
python --version  # Should be 3.11+

# Check hook scripts are executable
chmod +x .git-hooks/*.py

# Run hook manually to see error
python .git-hooks/enforce_md_location.py file.md
```

### Update Hook Dependencies

```bash
# Update to latest hook versions
pre-commit autoupdate

# Clean and reinstall
pre-commit clean
pre-commit install --install-hooks
```

### Skip Hooks for Specific Files

Add to `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/psf/black
  rev: 23.12.1
  hooks:
    - id: black
      exclude: '^(path/to/legacy/code/|generated/)'
```

---

## CI/CD Integration

Pre-commit hooks also run in CI/CD:

```yaml
# .github/workflows/ci.yml
- name: Run pre-commit checks
  run: |
    pip install pre-commit
    pre-commit run --all-files --show-diff-on-failure
```

This ensures:
1. Developers who bypass hooks locally are caught in CI
2. Consistent code quality across all contributors
3. Failed CI prevents merging bad code

---

## Summary

| Requirement | Enforcement | Auto-Fix | Bypass |
|-------------|-------------|----------|--------|
| .md files in docs/ | Pre-commit hook | No | --no-verify |
| No credentials | detect-secrets + custom | No | --no-verify |
| Code linting (Black) | Pre-commit hook | Yes | --no-verify |
| Code linting (Ruff) | Pre-commit hook | Partial | --no-verify |
| Type checking (mypy) | Pre-commit hook | No | --no-verify |
| Security (Bandit) | Pre-commit hook | No | --no-verify |

**Best Practice**: Never use `--no-verify` except in genuine emergencies. The hooks exist to protect code quality and security.

---

## Getting Help

If hooks block legitimate changes:

1. **Read the error message** - it usually contains the solution
2. **Check this documentation** - most issues are explained above
3. **Review configuration** - check `.pre-commit-config.yaml` and tool configs
4. **Ask for help** - open an issue with the full error message

---

**Version**: 1.0.0
**Last Updated**: 2025-11-20
