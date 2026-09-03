#!/usr/bin/env bash
# Самоустановка дома: git-крючок pre-commit в этом клоне.
# Клон у каждой сессии свой, .git/hooks в git не хранится — значит
# установка обязана быть однокомандной, иначе её пропускают.
set -eu
HOME_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$HOME_DIR/../.." && pwd)"
mkdir -p "$REPO/.git/hooks"
cat > "$REPO/.git/hooks/pre-commit" <<'HOOK'
#!/usr/bin/env bash
exec python3 "$(git rev-parse --show-toplevel)/env/Librarer/hooks/guard.py" staged
HOOK
chmod +x "$REPO/.git/hooks/pre-commit"
echo "поставлен: $REPO/.git/hooks/pre-commit → env/Librarer/hooks/guard.py staged"
python3 "$HOME_DIR/hooks/guard.py" staged || true
