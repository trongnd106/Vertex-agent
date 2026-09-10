# Full-Stack Project Scaffolding

When the user asks to build a complete full-stack application from scratch (e.g., NestJS + NextJS), use this rapid scaffolding approach.

## Workflow

1. **Todo list first** — break the request into discrete tracked steps via `todo()`. Each API endpoint or major feature gets its own todo item. This prevents scope creep and gives the user progress visibility.

2. **Create directory structure immediately** — `mkdir -p backend/src/{controllers,services,modules,dto,interfaces}` and `frontend/src/app/components` before writing any files.

3. **Write files bottom-up** — interfaces → services → controllers → modules → app module → main.ts. Dependency order: define types before consumers.

4. **For each file, use `write_file`** — not `terminal` with heredocs. `write_file` gives lint feedback and is easier to debug when something breaks.

5. **Build and fix iteratively** — after writing all code, run the build:
   ```
   cd backend && npm install && npx nest build
   cd frontend && npm install && npx next build
   ```
   Then fix any TypeScript errors. Expect 1-3 compilation errors on first build due to API mismatches in library types (see Pitfalls below for common fixes).

## Frontend Setup

- Use `create-next-app@latest` with TypeScript, Tailwind, App Router
- Use Mantine UI for fast tab-based layouts:
  - `npm install @mantine/core @mantine/hooks @mantine/notifications @mantine/dropzone @tabler/icons-react axios`
  - **PostCSS config required**: create `postcss.config.cjs` with `postcss-preset-mantine` + `postcss-simple-vars` with breakpoint variables
  - **Layout**: wrap `<MantineProvider>` + `<Notifications>` in the root `layout.tsx` (client component via `'use client'`)
  - Import Mantine CSS files in layout: `@mantine/core/styles.css`, `@mantine/notifications/styles.css`, `@mantine/dropzone/styles.css`
- Create a single `lib/api.ts` with typed API client functions per feature
- One tab component per API feature, mounted via `<Tabs>` on the main page

## Deliverables

Every scaffolding session should produce:
- Functional backend (builds + serves)
- Functional frontend (builds + pages render)
- `docker-compose.yml` for production deployment
- `README.md` with setup instructions
- `.env.example` and `.gitignore`
- Optional: `setup.sh` convenience script

## Pitfalls

- **LibreOffice must be installed** for docx↔pdf conversion and .doc extraction. Docker images must include it explicitly.
- **poppler-utils** must be installed for PDF split/merge (pdfseparate, pdfunite). Not included in standard Node images.
- **Don't skip npm install before build** — TypeScript errors about missing modules are false alarms before install.
- **multer 1.x is vulnerable** — `npm install` will warn about it. Use `multer` 2.x or skip multer for raw file handling. For NestJS, the `@nestjs/platform-express` `FileInterceptor` works with multer 2.x.
- **NestJS file upload boilerplate** — always use `uuidv4()` for stored filenames to avoid collisions, set `fileFilter` to validate extensions, and cap `fileSize` at 50MB for document processing. Add both `.doc` (MIME `application/msword`) and `.docx` to accepted types. Store uploads in an `uploads/` directory created via `fs.mkdirSync` at controller init.
- **TypeScript `downlevelIteration`** — when looping over `Set` or `Map` in older tsconfig targets, add `"downlevelIteration": true` to `compilerOptions` in `tsconfig.json`, or set `"target": "ES2021"`.
- **`docx` library v8 `Paragraph` API** — does NOT accept `text` + `bold` at the top level. Use `children: [new TextRun({ text, bold })]` instead. Table cells and heading paragraphs both need this pattern.
