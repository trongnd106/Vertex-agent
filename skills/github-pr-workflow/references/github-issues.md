# GitHub Issues Management

## Viewing Issues

**gh:** `gh issue list`, `gh issue list --label "bug"`, `gh issue view 42`

**curl:**
```bash
curl -s -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/$OWNER/$REPO/issues?state=open&per_page=20"
```

## Creating Issues

**gh:**
```bash
gh issue create --title "Bug title" --body "## Description\n..." --label "bug" --assignee "username"
```

**curl:**
```bash
curl -s -X POST -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/issues \
  -d '{"title": "...", "body": "...", "labels": ["bug"], "assignees": ["username"]}'
```

## Managing Issues

| Action | gh | curl |
|--------|-----|------|
| Add labels | `gh issue edit N --add-label "bug"` | `POST .../issues/N/labels` |
| Remove labels | `gh issue edit N --remove-label "x"` | `DELETE .../issues/N/labels/x` |
| Assignee | `gh issue edit N --add-assignee user` | `POST .../issues/N/assignees` |
| Comment | `gh issue comment N --body "..."` | `POST .../issues/N/comments` |
| Close | `gh issue close N` | `PATCH .../issues/N` with `{"state":"closed"}` |
| Reopen | `gh issue reopen N` | `PATCH .../issues/N` with `{"state":"open"}` |

## Issue Templates

**Bug Report:**
```markdown
## Bug Description | ## Steps to Reproduce | ## Expected Behavior | ## Actual Behavior | ## Environment
```

**Feature Request:**
```markdown
## Feature Description | ## Motivation | ## Proposed Solution | ## Alternatives Considered
```

## Triage Workflow
1. List untriaged: `gh issue list --label "needs-triage"`
2. Read and categorize each issue
3. Apply labels and priority
4. Assign if owner is clear
5. Comment with triage notes

## Linking Issues to PRs
Keywords in PR body: `Closes #42`, `Fixes #42`, `Resolves #42`
Branch from issue: `gh issue develop 42 --checkout`
