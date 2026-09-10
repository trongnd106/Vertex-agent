# Codebase Inspection with pygount

## Prerequisites
```bash
pip install pygount
```

## Basic Summary
```bash
cd /path/to/repo
pygount --format=summary --folders-to-skip=".git,node_modules,venv,.venv,__pycache__,.cache,dist,build,.next,.tox,.eggs" .
```

Folder exclusions by project type:
- Python: `--folders-to-skip=".git,venv,.venv,__pycache__,.cache,dist,build,.tox,.eggs,.mypy_cache"`
- JS/TS: `--folders-to-skip=".git,node_modules,dist,build,.next,.cache,.turbo,coverage"`

## Filter by Language
```bash
pygount --suffix=py --format=summary .
pygount --suffix=py,yaml,yml --format=summary .
```

## Output Formats
- `--format=summary` — table: Language, Files, Code, Comment, %
- `--format=json` — programmatic access

## Column Interpretation
- **Language**: detected language (also `__empty__`, `__binary__`, `__generated__`, `__duplicate__`, `__unknown__`)
- **Code**: executable lines; **Comment**: doc/comment lines
- Markdown shows 0 Code lines (all content treated as comments)

## Pitfalls
1. Always exclude .git, node_modules, venv or it can take minutes
2. Markdown shows 0 code lines by design
3. For large monorepos, use `--suffix` to target specific languages
