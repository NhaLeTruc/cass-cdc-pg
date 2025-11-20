#!/bin/bash
#
# Setup script for Git hooks and pre-commit framework
# This script installs and configures all enforcement mechanisms
#

set -e  # Exit on error

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🔧 Setting up Git hooks for CDC pipeline project..."
echo ""

# Check Python version
echo "📋 Checking Python version..."
if ! command -v python3 &> /dev/null; then
    echo "❌ ERROR: Python 3 is not installed"
    echo "   Install Python 3.11+ and retry"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "✅ Found Python $PYTHON_VERSION"
echo ""

# Install pre-commit
echo "📦 Installing pre-commit framework..."
if ! command -v pre-commit &> /dev/null; then
    echo "   Installing via pip..."
    pip install pre-commit
else
    echo "✅ pre-commit already installed"
fi
echo ""

# Install detect-secrets
echo "📦 Installing detect-secrets..."
if ! python3 -c "import detect_secrets" 2>/dev/null; then
    echo "   Installing via pip..."
    pip install detect-secrets
else
    echo "✅ detect-secrets already installed"
fi
echo ""

# Make hook scripts executable
echo "🔐 Making hook scripts executable..."
chmod +x "$PROJECT_ROOT/.git-hooks/"*.py
echo "✅ Hook scripts are executable"
echo ""

# Install pre-commit hooks
echo "🪝 Installing pre-commit hooks to .git/hooks/..."
cd "$PROJECT_ROOT"
pre-commit install
echo "✅ Hooks installed"
echo ""

# Initialize secrets baseline if it doesn't exist
if [ ! -f "$PROJECT_ROOT/.secrets.baseline" ]; then
    echo "🔍 Creating secrets baseline..."
    detect-secrets scan --baseline "$PROJECT_ROOT/.secrets.baseline"
    echo "✅ Secrets baseline created"
else
    echo "✅ Secrets baseline already exists"
fi
echo ""

# Test hooks
echo "🧪 Testing hooks (this may take a minute)..."
if pre-commit run --all-files 2>&1 | tee /tmp/pre-commit-test.log; then
    echo "✅ All hooks passed!"
else
    echo "⚠️  Some hooks failed or auto-fixed issues"
    echo "   Review output above and fix any remaining issues"
    echo ""
    echo "   Common issues:"
    echo "   - Files need formatting (Black, Ruff) - will be auto-fixed"
    echo "   - Type errors (mypy) - need manual fixes"
    echo "   - Credentials detected - remove and retry"
fi
echo ""

# Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Git hooks setup complete!"
echo ""
echo "Enforcement mechanisms active:"
echo "  1. ✅ Markdown files must be in docs/ directory"
echo "  2. ✅ Credentials are blocked from commits"
echo "  3. ✅ Code must pass linting before commits"
echo ""
echo "Next steps:"
echo "  - Read: docs/git-hooks-enforcement.md"
echo "  - Test: Try committing a file to see hooks in action"
echo "  - Verify: git commit --dry-run"
echo ""
echo "To bypass hooks (EMERGENCY ONLY):"
echo "  git commit --no-verify"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
