---
name: markdown-to-docx
description: >
  Convert Markdown files to polished, beautifully formatted Word documents (.docx).
  Use this skill whenever the user wants to: convert a .md file to Word/docx, export
  markdown as a Word document, turn markdown notes/reports/READMEs into a professional
  document, or produce a styled .docx from markdown text. Triggers include phrases like
  "convert markdown to Word", "export md to docx", "make a Word doc from my markdown",
  "turn this into a Word document", or when the user pastes markdown and asks for a .docx.
  Also trigger when the user uploads a .md file and wants a Word output. Supports headings,
  bold, italic, strikethrough, inline code, code blocks, blockquotes, tables, lists (nested),
  horizontal rules, links, and local images. Four built-in themes available.
---

# Markdown → DOCX Skill

Converts Markdown to a **beautifully styled** Word document using the bundled
`scripts/convert.js` script (Node.js + `docx` npm package).

---

## Quick Start

```bash
node /path/to/skill/scripts/convert.js input.md output.docx --theme=professional
```

---

## Workflow

### Step 1 — Obtain the Markdown

| Source | Action |
|--------|--------|
| User uploads `.md` file | Find it at `/mnt/user-data/uploads/` |
| User pastes Markdown text | Write the text to a temp file: `echo "..." > /tmp/input.md` |
| User references a file by path | Read & copy it to `/tmp/input.md` |

### Step 2 — Pick a Theme

Ask the user (or infer from context) which theme they'd like:

| Theme | Vibe | Accent Colors |
|-------|------|---------------|
| `professional` | Corporate, polished | Navy blue + mid blue *(default)* |
| `default` | Clean, modern | Dark teal + aqua |
| `minimal` | Editorial, typographic | Dark grey + light grey (Georgia font) |
| `vibrant` | Bold, creative | Purple + pink |

If the user doesn't specify, use `professional`.

### Step 3 — Run the Converter

```bash
# Always use the ABSOLUTE path to the script
SKILL_DIR="$(dirname "$(realpath "$0")")"  # or hardcode the skill directory

node "$SKILL_DIR/scripts/convert.js" \
  /tmp/input.md \
  /mnt/user-data/outputs/output.docx \
  --theme=professional
```

**Important path notes:**
- Input: can be anywhere readable
- Output: place final file in `/mnt/user-data/outputs/` so the user can download it
- The script resolves image paths **relative to the input .md file's directory**

### Step 4 — Present the File

Use the `present_files` tool to share the output with the user. Mention the theme used
and offer to re-run with a different theme or custom settings.

---

## Supported Markdown Elements

| Element | Syntax | Notes |
|---------|--------|-------|
| Headings | `# H1` … `###### H6` + setext | Styled per theme; H1 gets bottom border |
| Bold | `**text**` or `__text__` | |
| Italic | `*text*` or `_text_` | |
| Bold+Italic | `***text***` | |
| Strikethrough | `~~text~~` | |
| Inline code | `` `code` `` | Monospace, shaded background |
| Fenced code blocks | ` ```lang ` … ` ``` ` | Coloured left border, shaded bg |
| Blockquotes | `> text` | Indented, left bar, italic |
| Unordered lists | `- item` or `* item` | Nested up to 3 levels |
| Ordered lists | `1. item` | Each list restarts numbering |
| Tables | `| col | col |` + separator | Header row coloured, zebra-striped rows |
| Horizontal rule | `---` / `***` / `___` | Rendered as paragraph border |
| Hyperlinks | `[text](url)` | Coloured + underlined |
| Images | `![alt](local/path.png)` | Embedded at 400×300 px (local files only) |

---

## Dependencies

- **Node.js** — available in the sandbox
- **docx** npm package — `npm install -g docx` (check first with `node -e "require('docx')"`)

If `docx` is not installed:
```bash
npm install -g docx
```

---

## Advanced: Custom Styling

If the user wants customisation beyond the four themes (different fonts, colours,
margins, etc.), edit the `THEMES` object at the top of `scripts/convert.js` or
add a new theme entry. Each theme exposes:

```
accent      – primary heading colour (hex, no #)
accent2     – secondary / link colour
headingFont – font for headings
bodyFont    – font for body text
codeFont    – monospace font
h1Size … bodySize – font sizes in half-points (24 = 12pt)
tableFill   – header row background
tableText   – header row text colour
altFill     – alternate table row background
borderColor – table/code border colour
quoteBar    – blockquote left-bar colour
quoteFill   – blockquote background
codeFill    – code block background
```

---

## Common Issues

| Symptom | Fix |
|---------|-----|
| `Cannot find module 'docx'` | Run `npm install -g docx` |
| Images not appearing | Ensure image paths in the `.md` are relative to the `.md` file location |
| Garbled characters | The script reads files as UTF-8; ensure the input is UTF-8 encoded |
| Table columns too narrow | Reduce the number of columns or use fewer/shorter column headers |

---

## Example Usage

```bash
# Convert an uploaded file with the vibrant theme
node /mnt/skills/.../scripts/convert.js \
  /mnt/user-data/uploads/report.md \
  /mnt/user-data/outputs/report.docx \
  --theme=vibrant

# Convert pasted text saved to a temp file
echo "# Hello\n\nThis is **bold** text." > /tmp/quick.md
node /mnt/skills/.../scripts/convert.js /tmp/quick.md /mnt/user-data/outputs/quick.docx
```
