# GitHub Authentication

## Detection Flow

```bash
git --version
gh --version 2>/dev/null || echo "gh not installed"
gh auth status 2>/dev/null || echo "gh not authenticated"
git config --global credential.helper 2>/dev/null || echo "no git credential helper"
```

## Method 1: Git-Only (HTTPS with PAT)
```bash
git config --global credential.helper store
git ls-remote https://github.com/<user>/<repo>.git  # triggers credential prompt
```

## Method 2: SSH
```bash
ls -la ~/.ssh/id_*.pub 2>/dev/null || ssh-keygen -t ed25519 -C "email" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub  # add to https://github.com/settings/keys
git config --global url."git@github.com:".insteadOf "https://github.com/"
```

## Method 3: gh CLI
```bash
gh auth login                          # interactive
echo "token" | gh auth login --with-token  # headless
gh auth setup-git
```

## API Auth Detection
```bash
if command -v gh &>/dev/null && gh auth status &>/dev/null; then
  AUTH="gh"
elif [ -n "$GITHUB_TOKEN" ]; then
  AUTH="curl"
elif grep -q "github.com" ~/.git-credentials 2>/dev/null; then
  export GITHUB_TOKEN=$(grep "github.com" ~/.git-credentials | head -1 | sed 's|https://[^:]*:\([^@]*\)@.*|\1|')
  AUTH="curl"
fi
```

## Owner/Repo Extraction
```bash
REMOTE_URL=$(git remote get-url origin)
OWNER_REPO=$(echo "$REMOTE_URL" | sed -E 's|.*github\.com[:/]||; s|\.git$||')
OWNER=$(echo "$OWNER_REPO" | cut -d/ -f1)
REPO=$(echo "$OWNER_REPO" | cut -d/ -f2)
```

## Troubleshooting
- `git push` asks for password → use PAT as password
- `Permission denied` → token lacks `repo` scope
- `Authentication failed` → `git credential reject` then re-auth
- SSH via HTTPS port → add `ssh.github.com:443` to `~/.ssh/config`
- `gh: command not found` + no sudo → use git-only Method 1
