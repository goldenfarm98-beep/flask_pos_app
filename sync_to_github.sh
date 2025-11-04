#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/goldenfarm98-beep/flask_pos_app"
DEFAULT_BRANCH="main"
COMMIT_MSG="${1:-"Auto-sync: $(date +'%Y-%m-%d %H:%M:%S %Z')"}"

echo "🔄 Starting sync..."
cd "$(dirname "$0")"

# Pastikan ini repo git
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "❌ Bukan di dalam repository Git. Jalankan skrip ini dari folder root project."
  exit 1
fi

# Set identitas git kalau belum ada
git config user.name >/dev/null 2>&1 || git config user.name "Ahmad Sugiarto"
git config user.email >/dev/null 2>&1 || git config user.email "ahmad@example.com"

# Pastikan branch aktif
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD || echo "$DEFAULT_BRANCH")"
if [[ "$CURRENT_BRANCH" == "HEAD" ]]; then
  git checkout -B "$DEFAULT_BRANCH"
  CURRENT_BRANCH="$DEFAULT_BRANCH"
fi

# Pastikan remote origin
if git remote get-url origin >/dev/null 2>&1; then
  ORIGIN_URL="$(git remote get-url origin)"
  if [[ "$ORIGIN_URL" != "$REPO_URL" ]]; then
    echo "ℹ️  Update origin: $ORIGIN_URL -> $REPO_URL"
    git remote set-url origin "$REPO_URL"
  fi
else
  echo "ℹ️  Tambah remote origin: $REPO_URL"
  git remote add origin "$REPO_URL"
fi

# Opsional: gunakan PAT bila tersedia (untuk push non-interaktif)
if [[ -n "${GITHUB_USER:-}" && -n "${GITHUB_TOKEN:-}" ]]; then
  PUSH_URL="https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/goldenfarm98-beep/flask_pos_app"
  git remote set-url --push origin "$PUSH_URL"
  echo "🔐 Push menggunakan PAT"
fi

# Stage semua perubahan (menghormati .gitignore)
git add -A

if git diff --cached --quiet; then
  echo "✅ Tidak ada perubahan baru untuk di-commit."
else
  echo "📝 Commit: $COMMIT_MSG"
  git commit -m "$COMMIT_MSG"
fi

# Pull --rebase bila upstream sudah ada
if git rev-parse --abbrev-ref --symbolic-full-name "@{u}" >/dev/null 2>&1; then
  echo "⬇️  git pull --rebase"
  git pull --rebase --autostash --no-edit || {
    echo "❌ Konflik saat rebase. Selesaikan konflik lalu jalankan ulang."
    exit 1
  }
  echo "⬆️  git push"
  git push origin "$CURRENT_BRANCH"
else
  echo "⬆️  Push pertama (set upstream)"
  git push -u origin "$CURRENT_BRANCH"
fi

echo "🎉 Selesai."
git status -sb
