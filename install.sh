#!/usr/bin/env bash
# ==============================================================================
# lazy-read: One-Line Installer for macOS & Linux
# https://github.com/kuihaphanich2542-prog/lazy-read
# ==============================================================================

set -e

REPO_URL="https://github.com/kuihaphanich2542-prog/lazy-read.git"
INSTALL_DIR="${HOME}/.agents/skills/lazy-read"
BIN_DIR="${HOME}/.local/bin"

echo "=== [1/4] Checking Python 3 Environment ==="

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 not found. Initiating automated installation..."
    OS="$(uname -s)"
    case "${OS}" in
        Darwin*)
            if command -v brew >/dev/null 2>&1; then
                echo "Installing Python 3 via Homebrew..."
                brew install python3
            else
                echo "Downloading official Python 3 installer for macOS..."
                PKG_URL="https://www.python.org/ftp/python/3.12.7/python-3.12.7-macos11.pkg"
                TEMP_PKG="/tmp/python-3.12.7-macos11.pkg"
                curl -fsSL "${PKG_URL}" -o "${TEMP_PKG}"
                echo "Installing Python package (requires administrator password)..."
                sudo installer -pkg "${TEMP_PKG}" -target /
                rm -f "${TEMP_PKG}"
            fi
            ;;
        Linux*)
            if command -v apt-get >/dev/null 2>&1; then
                sudo apt-get update && sudo apt-get install -y python3 python3-pip
            elif command -v dnf >/dev/null 2>&1; then
                sudo dnf install -y python3
            elif command -v pacman >/dev/null 2>&1; then
                sudo pacman -Sy --noconfirm python
            else
                echo "Error: Unknown Linux distribution. Please install Python 3 manually."
                exit 1
            fi
            ;;
        *)
            echo "Error: Unsupported operating system: ${OS}"
            exit 1
            ;;
    esac
fi

PYTHON_BIN="$(command -v python3)"
PY_VER="$("${PYTHON_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "Python 3 is ready: ${PYTHON_BIN} (v${PY_VER})"

echo "=== [2/4] Installing lazy-read Skill ==="

mkdir -p "$(dirname "${INSTALL_DIR}")"

if [ -d "${INSTALL_DIR}/.git" ]; then
    echo "Updating existing installation at ${INSTALL_DIR}..."
    git -C "${INSTALL_DIR}" pull --quiet origin main
else
    rm -rf "${INSTALL_DIR}"
    echo "Cloning repository to ${INSTALL_DIR}..."
    git clone --quiet "${REPO_URL}" "${INSTALL_DIR}"
fi

# Link to other popular AI Agent skill directories if present
for AGENT_SKILLS in "${HOME}/.gemini/antigravity-cli/skills" "${HOME}/.claude/skills"; do
    if [ -d "${AGENT_SKILLS}" ]; then
        mkdir -p "${AGENT_SKILLS}"
        rm -rf "${AGENT_SKILLS}/lazy-read"
        ln -sf "${INSTALL_DIR}" "${AGENT_SKILLS}/lazy-read"
        echo "Linked skill to: ${AGENT_SKILLS}/lazy-read"
    fi
done

echo "=== [3/4] Creating Global CLI Shortcut ==="

mkdir -p "${BIN_DIR}"
WRAPPER="${BIN_DIR}/lazy-read"

cat <<'EOF' > "${WRAPPER}"
#!/usr/bin/env bash
SKILL_DIR="${HOME}/.agents/skills/lazy-read"
CMD="$1"

if [ -z "${CMD}" ] || [ "${CMD}" = "--help" ] || [ "${CMD}" = "-h" ]; then
    echo "lazy-read v1.7.1 — Read the map first, then slice"
    echo ""
    echo "Usage:"
    echo "  lazy-read map <repo> [flags]        # Codebase skeleton map"
    echo "  lazy-read inspect <repo> <syms...>  # Precise symbol slice"
    echo "  lazy-read find <repo> <query>       # Function-level error/text lookup"
    echo "  lazy-read trace <repo> --file <t>   # Leaf-frame stack trace mapper"
    echo "  lazy-read history <repo> <sym>      # Scoped function git diff"
    echo "  lazy-read outline <doc>             # Section outline (MD/DOCX/PDF)"
    echo "  lazy-read schema <table>            # Tabular schema & aggregations"
    exit 0
fi

shift

case "${CMD}" in
    map|inspect|slice|search|find|trace|history)
        python3 "${SKILL_DIR}/scripts/codemap.py" "${CMD}" "$@"
        ;;
    outline)
        python3 "${SKILL_DIR}/scripts/docmap.py" outline "$@"
        ;;
    doc-slice)
        python3 "${SKILL_DIR}/scripts/docmap.py" slice "$@"
        ;;
    doc-search)
        python3 "${SKILL_DIR}/scripts/docmap.py" search "$@"
        ;;
    schema)
        python3 "${SKILL_DIR}/scripts/tablemap.py" schema "$@"
        ;;
    agg)
        python3 "${SKILL_DIR}/scripts/tablemap.py" agg "$@"
        ;;
    table-slice)
        python3 "${SKILL_DIR}/scripts/tablemap.py" slice "$@"
        ;;
    table-find)
        python3 "${SKILL_DIR}/scripts/tablemap.py" find "$@"
        ;;
    *)
        echo "Unknown command: ${CMD}. Run 'lazy-read --help' for usage."
        exit 1
        ;;
esac
EOF

chmod +x "${WRAPPER}"
echo "CLI wrapper created at ${WRAPPER}"

echo "=== [4/4] Verifying Installation ==="
python3 "${INSTALL_DIR}/scripts/codemap.py" --help >/dev/null 2>&1
echo "Verification check passed: 100% operational."

echo ""
echo "============================================================"
echo " lazy-read v1.7.1 installed successfully!"
echo " Skill path: ${INSTALL_DIR}"
echo " CLI wrapper: ${WRAPPER}"
echo ""
echo " If '${BIN_DIR}' is not in your PATH, add this to your ~/.zshrc or ~/.bashrc:"
echo "   export PATH=\"\${HOME}/.local/bin:\${PATH}\""
echo "============================================================"
