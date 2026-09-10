# GitHub Repository Management

## Cloning
```bash
git clone https://github.com/owner/repo.git
git clone --depth 1 https://github.com/owner/repo.git
git clone --branch develop https://github.com/owner/repo.git
gh repo clone owner/repo
```

## Creating Repos

**gh:** `gh repo create my-project --public --clone`
**curl:**
```bash
curl -s -X POST -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/user/repos \
  -d '{"name":"my-project","private":false,"auto_init":true}'
```

## Forking
```bash
gh repo fork owner/repo --clone
# Then add upstream:
git remote add upstream https://github.com/owner/repo.git
git fetch upstream && git merge upstream/main
```

## Repo Settings

| Action | gh | curl |
|--------|-----|------|
| Edit description | `gh repo edit --description "..."` | `PATCH /repos/{o}/{r}` |
| Visibility | `gh repo edit --visibility public` | `PATCH /repos/{o}/{r}` |
| Topics | `gh repo edit --add-topic "ml,python"` | `PUT /repos/{o}/{r}/topics` |

## Branch Protection
```bash
curl -s -X PUT -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/$OWNER/$REPO/branches/main/protection \
  -d '{"required_status_checks":{"strict":true,"contexts":["ci/test"]},"required_pull_request_reviews":{"required_approving_review_count":1}}'
```

## GitHub Actions
```bash
gh workflow list
gh run list --limit 10
gh run view <RUN_ID> --log-failed
gh run rerun <RUN_ID> --failed
```

## Secrets
`gh secret set API_KEY --body "value"` is dramatically simpler than API.
For API, secrets require libsodium-based encryption with repo's public key.

## Releases
```bash
gh release create v1.0.0 --title "v1.0.0" --generate-notes
gh release create v2.0.0-rc1 --draft --prerelease
gh release list
```

## Gists
```bash
gh gist create script.py --public --desc "Description"
```
