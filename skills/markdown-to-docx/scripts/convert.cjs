#!/usr/bin/env node
/**
 * markdown-to-docx converter
 * Usage: node convert.js input.md output.docx [--theme default|professional|minimal|vibrant]
 *
 * Converts Markdown to a beautifully styled .docx file.
 * Supports: headings, bold, italic, strikethrough, inline code, code blocks,
 *           unordered/ordered lists (nested), blockquotes, tables, horizontal rules,
 *           hyperlinks, and images (local files).
 */

const fs = require("fs");
const path = require("path");

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat, ExternalHyperlink,
  HeadingLevel, BorderStyle, WidthType, ShadingType, VerticalAlign,
  PageNumberElement, ImageRun, UnderlineType, TabStopType,
} = require("docx");

// ─── CLI args ────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const inputFile  = args[0];
const outputFile = args[1] || "output.docx";
const themeArg   = (args.find(a => a.startsWith("--theme=")) || "").replace("--theme=", "") || "professional";

if (!inputFile) {
  console.error("Usage: node convert.js <input.md> [output.docx] [--theme=default|professional|minimal|vibrant]");
  process.exit(1);
}

const markdownText = fs.readFileSync(inputFile, "utf8");
const inputDir     = path.dirname(path.resolve(inputFile));

// ─── Themes ──────────────────────────────────────────────────────────────────
const THEMES = {
  professional: {
    accent:      "1F4E79",  // navy blue
    accent2:     "2E75B6",  // mid blue
    headingFont: "Calibri",
    bodyFont:    "Calibri",
    codeFont:    "Courier New",
    h1Size: 36, h2Size: 30, h3Size: 26, bodySize: 22,
    tableFill:   "1F4E79", tableText: "FFFFFF",
    altFill:     "EBF3FB", borderColor: "BFCFE8",
    quoteBar:    "2E75B6", quoteFill: "EBF3FB",
    codeFill:    "F2F2F2",
  },
  default: {
    accent:      "2E4057",
    accent2:     "48A9A6",
    headingFont: "Arial",
    bodyFont:    "Arial",
    codeFont:    "Courier New",
    h1Size: 36, h2Size: 30, h3Size: 26, bodySize: 22,
    tableFill:   "2E4057", tableText: "FFFFFF",
    altFill:     "E8F4F4", borderColor: "C0D8D8",
    quoteBar:    "48A9A6", quoteFill: "F0FAFA",
    codeFill:    "F5F5F5",
  },
  minimal: {
    accent:      "333333",
    accent2:     "666666",
    headingFont: "Georgia",
    bodyFont:    "Georgia",
    codeFont:    "Courier New",
    h1Size: 38, h2Size: 30, h3Size: 26, bodySize: 22,
    tableFill:   "333333", tableText: "FFFFFF",
    altFill:     "F7F7F7", borderColor: "DDDDDD",
    quoteBar:    "AAAAAA", quoteFill: "F9F9F9",
    codeFill:    "F4F4F4",
  },
  vibrant: {
    accent:      "6B21A8",  // purple
    accent2:     "EC4899",  // pink
    headingFont: "Calibri",
    bodyFont:    "Calibri",
    codeFont:    "Courier New",
    h1Size: 38, h2Size: 30, h3Size: 26, bodySize: 22,
    tableFill:   "6B21A8", tableText: "FFFFFF",
    altFill:     "FAF0FF", borderColor: "DDB8F5",
    quoteBar:    "EC4899", quoteFill: "FFF0F8",
    codeFill:    "F5F0FF",
  },
};

const T = THEMES[themeArg] || THEMES.professional;

// ─── Markdown tokeniser ───────────────────────────────────────────────────────
// Returns an array of block tokens.
function tokenise(md) {
  const lines  = md.replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let i = 0;

  while (i < lines.length) {
    const raw = lines[i];

    // --- Fenced code block
    if (/^(`{3,}|~{3,})/.test(raw)) {
      const fence = raw.match(/^(`{3,}|~{3,})/)[1];
      const lang  = raw.slice(fence.length).trim();
      const code  = [];
      i++;
      while (i < lines.length && !lines[i].startsWith(fence)) {
        code.push(lines[i]);
        i++;
      }
      blocks.push({ type: "code", lang, text: code.join("\n") });
      i++;
      continue;
    }

    // --- Horizontal rule
    if (/^([-*_])\s*\1\s*\1[\s\1]*$/.test(raw.trim()) && raw.trim().length >= 3) {
      blocks.push({ type: "hr" });
      i++; continue;
    }

    // --- ATX Heading
    const hm = raw.match(/^(#{1,6})\s+(.*)/);
    if (hm) {
      blocks.push({ type: "heading", level: hm[1].length, text: hm[2].trim() });
      i++; continue;
    }

    // --- Setext headings
    if (i + 1 < lines.length) {
      if (/^=+\s*$/.test(lines[i + 1]) && raw.trim()) {
        blocks.push({ type: "heading", level: 1, text: raw.trim() });
        i += 2; continue;
      }
      if (/^-+\s*$/.test(lines[i + 1]) && raw.trim()) {
        blocks.push({ type: "heading", level: 2, text: raw.trim() });
        i += 2; continue;
      }
    }

    // --- Blockquote
    if (/^>\s?/.test(raw)) {
      const qlines = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        qlines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      blocks.push({ type: "blockquote", text: qlines.join("\n") });
      continue;
    }

    // --- Table
    if (/^\|/.test(raw) && i + 1 < lines.length && /^\|[-:| ]+\|/.test(lines[i + 1])) {
      const rows = [];
      while (i < lines.length && /^\|/.test(lines[i])) {
        const cells = lines[i].split("|").slice(1, -1).map(c => c.trim());
        rows.push(cells);
        i++;
      }
      const align = rows[1].map(c =>
        /^:-+:$/.test(c) ? "center" : /^-+:$/.test(c) ? "right" : "left"
      );
      blocks.push({ type: "table", headers: rows[0], align, rows: rows.slice(2) });
      continue;
    }

    // --- Unordered list
    if (/^(\s*)([-*+])\s+/.test(raw)) {
      const items = [];
      while (i < lines.length && /^(\s*)([-*+])\s+/.test(lines[i])) {
        const m = lines[i].match(/^(\s*)([-*+])\s+(.*)/);
        items.push({ indent: Math.floor(m[1].length / 2), text: m[3] });
        i++;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    // --- Ordered list
    if (/^\s*\d+\.\s+/.test(raw)) {
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        const m = lines[i].match(/^(\s*)\d+\.\s+(.*)/);
        items.push({ indent: Math.floor(m[1].length / 2), text: m[2] });
        i++;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    // --- Blank line / paragraph
    if (raw.trim() === "") { i++; continue; }

    // Gather paragraph lines
    const plines = [];
    while (i < lines.length && lines[i].trim() !== "" &&
           !/^(#{1,6}|\`{3}|~{3}|>|\||\s*[-*+]\s|\s*\d+\.\s)/.test(lines[i]) &&
           !/^([-*_])\s*\1\s*\1/.test(lines[i])) {
      plines.push(lines[i]);
      i++;
    }
    if (plines.length) blocks.push({ type: "paragraph", text: plines.join(" ") });
  }
  return blocks;
}

// ─── Inline parser ────────────────────────────────────────────────────────────
// Converts inline markdown to docx TextRun / ExternalHyperlink children.
function parseInline(text, baseStyle = {}) {
  const children = [];

  // Patterns: bold+italic, bold, italic, strikethrough, inline code, link, image
  const pattern = /(\*{3}|_{3})(.+?)\1|(\*{2}|_{2})(.+?)\3|(\*|_)(.+?)\5|(~~)(.+?)\7|(`+)(.+?)\9|\[([^\]]*)\]\(([^)]*)\)|!\[([^\]]*)\]\(([^)]*)\)/gs;
  let last = 0;
  let match;

  while ((match = pattern.exec(text)) !== null) {
    // Plain text before match
    if (match.index > last) {
      children.push(new TextRun({ text: text.slice(last, match.index), ...baseStyle }));
    }

    if (match[1]) { // bold+italic
      children.push(new TextRun({ text: match[2], bold: true, italics: true, ...baseStyle }));
    } else if (match[3]) { // bold
      children.push(new TextRun({ text: match[4], bold: true, ...baseStyle }));
    } else if (match[5]) { // italic
      children.push(new TextRun({ text: match[6], italics: true, ...baseStyle }));
    } else if (match[7]) { // strikethrough
      children.push(new TextRun({ text: match[8], strike: true, ...baseStyle }));
    } else if (match[9]) { // inline code
      children.push(new TextRun({
        text: match[10], font: T.codeFont,
        shading: { type: ShadingType.CLEAR, fill: T.codeFill },
        size: (baseStyle.size || T.bodySize) - 1,
      }));
    } else if (match[11] !== undefined) { // hyperlink
      children.push(
        new ExternalHyperlink({
          link: match[12],
          children: [new TextRun({
            text: match[11] || match[12],
            color: T.accent2,
            underline: { type: UnderlineType.SINGLE, color: T.accent2 },
            font: T.bodyFont,
          })],
        })
      );
    } else if (match[13] !== undefined) { // image
      const imgPath = path.resolve(inputDir, match[14]);
      if (fs.existsSync(imgPath)) {
        const imgData = fs.readFileSync(imgPath);
        const ext     = path.extname(imgPath).slice(1).toLowerCase();
        const typeMap = { jpg: "jpg", jpeg: "jpg", png: "png", gif: "gif", webp: "webp" };
        children.push(new ImageRun({ data: imgData, transformation: { width: 400, height: 300 }, type: typeMap[ext] || "png" }));
      } else {
        children.push(new TextRun({ text: `[Image: ${match[13]}]`, italics: true, color: "888888" }));
      }
    }

    last = match.index + match[0].length;
  }

  if (last < text.length) {
    children.push(new TextRun({ text: text.slice(last), ...baseStyle }));
  }

  return children.length ? children : [new TextRun({ text, ...baseStyle })];
}

// ─── Block → docx elements ────────────────────────────────────────────────────
const HEADING_LEVELS = [
  HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3,
  HeadingLevel.HEADING_4, HeadingLevel.HEADING_5, HeadingLevel.HEADING_6,
];

function headingParagraph(block) {
  const lvl   = Math.min(block.level, 6);
  const sizes = [T.h1Size, T.h2Size, T.h3Size, T.h3Size - 2, T.h3Size - 4, T.h3Size - 6];
  const sz    = sizes[lvl - 1];
  const inline = parseInline(block.text, { size: sz, font: T.headingFont, bold: true, color: lvl === 1 ? T.accent : T.accent });

  const p = new Paragraph({
    heading: HEADING_LEVELS[lvl - 1],
    spacing: { before: lvl === 1 ? 360 : 240, after: lvl === 1 ? 180 : 120 },
    children: inline,
  });
  return [p];
}

function normalParagraph(text, extraProps = {}) {
  return new Paragraph({
    spacing: { before: 60, after: 120 },
    children: parseInline(text, { size: T.bodySize, font: T.bodyFont }),
    ...extraProps,
  });
}

function codeBlock(block) {
  const lines = block.text.split("\n");
  return lines.map((line, idx) => new Paragraph({
    spacing: { before: idx === 0 ? 100 : 0, after: idx === lines.length - 1 ? 100 : 0 },
    shading: { type: ShadingType.CLEAR, fill: T.codeFill },
    border: idx === 0
      ? { top:    { style: BorderStyle.SINGLE, size: 1, color: T.borderColor },
          left:   { style: BorderStyle.SINGLE, size: 6, color: T.accent2 },
          right:  { style: BorderStyle.SINGLE, size: 1, color: T.borderColor } }
      : idx === lines.length - 1
        ? { bottom: { style: BorderStyle.SINGLE, size: 1, color: T.borderColor },
            left:   { style: BorderStyle.SINGLE, size: 6, color: T.accent2 },
            right:  { style: BorderStyle.SINGLE, size: 1, color: T.borderColor } }
        : { left:  { style: BorderStyle.SINGLE, size: 6, color: T.accent2 },
            right: { style: BorderStyle.SINGLE, size: 1, color: T.borderColor } },
    indent: { left: 360 },
    children: [new TextRun({ text: line || " ", font: T.codeFont, size: T.bodySize - 2, color: "1A1A1A" })],
  }));
}

function blockquoteParagraph(text) {
  return text.split("\n").map(line => new Paragraph({
    spacing: { before: 60, after: 60 },
    indent:  { left: 540, right: 360 },
    shading: { type: ShadingType.CLEAR, fill: T.quoteFill },
    border:  { left: { style: BorderStyle.THICK, size: 12, color: T.quoteBar } },
    children: parseInline(line, { size: T.bodySize, font: T.bodyFont, italics: true, color: "444444" }),
  }));
}

function listItems(block) {
  const isOrdered = block.type === "ol";
  return block.items.map((item, idx) => new Paragraph({
    numbering: {
      reference: isOrdered ? `ol-${block._id}` : `ul-main`,
      level: Math.min(item.indent, 2),
    },
    spacing: { before: 40, after: 40 },
    children: parseInline(item.text, { size: T.bodySize, font: T.bodyFont }),
  }));
}

function hrElement() {
  return new Paragraph({
    spacing: { before: 200, after: 200 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: T.accent2, space: 1 } },
    children: [],
  });
}

function tableElement(block) {
  const brd   = { style: BorderStyle.SINGLE, size: 1, color: T.borderColor };
  const allBorders = { top: brd, bottom: brd, left: brd, right: brd };
  const colCount = block.headers.length;
  const totalW   = 9360;
  const colW     = Math.floor(totalW / colCount);
  const colWidths = Array(colCount).fill(colW);

  const headerRow = new TableRow({
    tableHeader: true,
    children: block.headers.map((h, ci) => new TableCell({
      borders: allBorders,
      width: { size: colWidths[ci], type: WidthType.DXA },
      shading: { type: ShadingType.CLEAR, fill: T.tableFill },
      margins: { top: 80, bottom: 80, left: 140, right: 140 },
      verticalAlign: VerticalAlign.CENTER,
      children: [new Paragraph({
        children: parseInline(h, { size: T.bodySize - 1, font: T.headingFont, bold: true, color: T.tableText }),
        alignment: block.align[ci] === "center" ? AlignmentType.CENTER
                 : block.align[ci] === "right"  ? AlignmentType.RIGHT
                 : AlignmentType.LEFT,
      })],
    })),
  });

  const dataRows = block.rows.map((row, ri) => new TableRow({
    children: row.map((cell, ci) => new TableCell({
      borders: allBorders,
      width: { size: colWidths[ci], type: WidthType.DXA },
      shading: ri % 2 === 0
        ? { type: ShadingType.CLEAR, fill: "FFFFFF" }
        : { type: ShadingType.CLEAR, fill: T.altFill },
      margins: { top: 80, bottom: 80, left: 140, right: 140 },
      children: [new Paragraph({
        children: parseInline(cell, { size: T.bodySize - 1, font: T.bodyFont }),
        alignment: block.align[ci] === "center" ? AlignmentType.CENTER
                 : block.align[ci] === "right"  ? AlignmentType.RIGHT
                 : AlignmentType.LEFT,
      })],
    })),
  }));

  return new Table({
    width: { size: totalW, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [headerRow, ...dataRows],
  });
}

// ─── Build document ───────────────────────────────────────────────────────────
const blocks  = tokenise(markdownText);
const docChildren = [];

// Assign IDs to ordered lists for unique numbering references
let olCounter = 0;
blocks.forEach(b => { if (b.type === "ol") b._id = olCounter++; });

// Build numbering config
const numberingConfig = [
  {
    reference: "ul-main",
    levels: [
      { level: 0, format: LevelFormat.BULLET, text: "●", alignment: AlignmentType.LEFT,
        style: { run: { font: "Symbol", size: T.bodySize, color: T.accent2 },
                 paragraph: { indent: { left: 540, hanging: 360 } } } },
      { level: 1, format: LevelFormat.BULLET, text: "○", alignment: AlignmentType.LEFT,
        style: { run: { font: "Symbol", size: T.bodySize, color: "888888" },
                 paragraph: { indent: { left: 900, hanging: 360 } } } },
      { level: 2, format: LevelFormat.BULLET, text: "▪", alignment: AlignmentType.LEFT,
        style: { run: { font: "Symbol", size: T.bodySize, color: "AAAAAA" },
                 paragraph: { indent: { left: 1260, hanging: 360 } } } },
    ],
  },
  ...Array.from({ length: olCounter }, (_, idx) => ({
    reference: `ol-${idx}`,
    levels: [
      { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
        style: { run: { font: T.bodyFont, size: T.bodySize, bold: false },
                 paragraph: { indent: { left: 540, hanging: 360 } } } },
      { level: 1, format: LevelFormat.LOWER_LETTER, text: "%2.", alignment: AlignmentType.LEFT,
        style: { run: { font: T.bodyFont, size: T.bodySize },
                 paragraph: { indent: { left: 900, hanging: 360 } } } },
    ],
  })),
];

// Process blocks into children
for (const block of blocks) {
  switch (block.type) {
    case "heading":
      docChildren.push(...headingParagraph(block));
      break;
    case "paragraph":
      docChildren.push(normalParagraph(block.text));
      break;
    case "code":
      docChildren.push(...codeBlock(block));
      break;
    case "blockquote":
      docChildren.push(...blockquoteParagraph(block.text));
      break;
    case "ul":
    case "ol":
      docChildren.push(...listItems(block));
      break;
    case "hr":
      docChildren.push(hrElement());
      break;
    case "table": {
      const tbl = tableElement(block);
      docChildren.push(tbl);
      docChildren.push(new Paragraph({ children: [], spacing: { before: 120 } }));
      break;
    }
  }
}

// ─── Styles ───────────────────────────────────────────────────────────────────
const docStyles = {
  default: {
    document: { run: { font: T.bodyFont, size: T.bodySize, color: "1A1A1A" } },
  },
  paragraphStyles: [
    {
      id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
      run:       { size: T.h1Size, bold: true, font: T.headingFont, color: T.accent },
      paragraph: { spacing: { before: 360, after: 180 }, outlineLevel: 0,
                   border: { bottom: { style: BorderStyle.SINGLE, size: 3, color: T.accent2, space: 4 } } },
    },
    {
      id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
      run:       { size: T.h2Size, bold: true, font: T.headingFont, color: T.accent },
      paragraph: { spacing: { before: 280, after: 140 }, outlineLevel: 1 },
    },
    {
      id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
      run:       { size: T.h3Size, bold: true, font: T.headingFont, color: T.accent2 },
      paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 2 },
    },
    {
      id: "Heading4", name: "Heading 4", basedOn: "Normal", next: "Normal", quickFormat: true,
      run:       { size: T.h3Size - 2, bold: true, italics: true, font: T.headingFont, color: T.accent2 },
      paragraph: { spacing: { before: 160, after: 80 }, outlineLevel: 3 },
    },
    {
      id: "Heading5", name: "Heading 5", basedOn: "Normal", next: "Normal", quickFormat: true,
      run:       { size: T.h3Size - 4, bold: true, font: T.headingFont, color: "555555" },
      paragraph: { spacing: { before: 140, after: 60 }, outlineLevel: 4 },
    },
    {
      id: "Heading6", name: "Heading 6", basedOn: "Normal", next: "Normal", quickFormat: true,
      run:       { size: T.h3Size - 6, bold: false, italics: true, font: T.headingFont, color: "777777" },
      paragraph: { spacing: { before: 120, after: 60 }, outlineLevel: 5 },
    },
  ],
};

// ─── Header / Footer ──────────────────────────────────────────────────────────
const docHeader = new Header({
  children: [
    new Paragraph({
      children: [],
      border: { bottom: { style: BorderStyle.SINGLE, size: 2, color: T.accent2, space: 4 } },
      spacing: { before: 0, after: 80 },
    }),
  ],
});

const docFooter = new Footer({
  children: [
    new Paragraph({
      border: { top: { style: BorderStyle.SINGLE, size: 2, color: T.borderColor, space: 4 } },
      spacing: { before: 80, after: 0 },
      tabStops: [{ type: TabStopType.RIGHT, position: 9360 }],
      children: [
        new TextRun({ text: path.basename(inputFile), font: T.bodyFont, size: 16, color: "888888" }),
        new TextRun({ children: ["\t", new PageNumberElement()], font: T.bodyFont, size: 16, color: "888888" }),
      ],
    }),
  ],
});

// ─── Assemble and write ───────────────────────────────────────────────────────
const doc = new Document({
  numbering: { config: numberingConfig },
  styles:    docStyles,
  sections: [{
    properties: {
      page: {
        size:   { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    headers: { default: docHeader },
    footers: { default: docFooter },
    children: docChildren,
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outputFile, buf);
  console.log(`✅ Converted: ${inputFile} → ${outputFile} (theme: ${themeArg})`);
}).catch(err => {
  console.error("❌ Error:", err.message);
  process.exit(1);
});
