# GitHub Code Review

## Prerequisites
Authenticated with GitHub. See `references/github-auth.md`.

## 1. Reviewing Local Changes (Pre-Push)

```bash
git diff --staged              # staged changes
git diff main...HEAD           # all changes vs main
git diff main...HEAD --stat    # summary
git log main..HEAD --oneline   # commits
```

**Check for common issues:**
```bash
git diff main...HEAD | grep -n "print(\|console\.log\|TODO\|FIXME\|debugger\|password\|secret\|api_key"
git diff main...HEAD --stat | sort -t'|' -k2 -rn | head -10
git diff main...HEAD | grep -n "<<<<<<\|>>>>>>\|======="
```

## 2. Reviewing a PR on GitHub

```bash
gh pr view 123
gh pr diff 123
gh pr diff 123 --name-only
```

**With curl:**
```bash
curl -s -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/$PR_NUMBER/files | python3 -c "
import sys, json
for f in json.load(sys.stdin):
    print(f\"{f['status']:10} +{f['additions']:-4} -{f['deletions']:-4}  {f['filename']}\")"
```

## 3. Leaving Comments

**General comment:**
- `gh pr comment 123 --body "..."`  
- `curl POST .../issues/$PR_NUMBER/comments`

**Inline review comment:**
```bash
HEAD_SHA=$(gh pr view 123 --json headRefOid --jq '.headRefOid')
gh api repos/$OWNER/$REPO/pulls/123/comments --method POST \
  -f body="..." -f path="src/file.py" -f commit_id="$HEAD_SHA" -f line=45 -f side="RIGHT"
```

## 4. Submit Formal Review

```bash
gh pr review 123 --approve --body "LGTM!"
gh pr review 123 --request-changes --body "See inline comments."
gh pr review 123 --comment --body "Suggestions."
```

**curl atomic review with inline comments:**
```bash
curl -s -X POST -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/pulls/$PR_NUMBER/reviews \
  -d '{"commit_id":"$HEAD_SHA","event":"COMMENT","body":"...","comments":[...]}'
```

Event values: `APPROVE`, `REQUEST_CHANGES`, `COMMENT`

## 5. Review Checklist

**Correctness:** Does code do what it claims? Edge cases? Error paths?  
**Security:** No hardcoded secrets, SQL injection, XSS? Input validation?  
**Code Quality:** Clear naming? DRY? Single responsibility?  
**Testing:** New code tested? Happy + error paths?  
**Performance:** N+1 queries? Blocking in async paths?  
**Documentation:** Public APIs documented? README updated?
