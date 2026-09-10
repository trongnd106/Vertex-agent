---
name: development-workflows
description: "Systematic software development practices: brainstroming, spike, planning, TDD, code review, debugging, completion workflows — full lifecycle from idea to merged PR."
version: 2.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [TDD, Planning, Spike, Code-Review, Debugging, Methodology, Workflow, Brainstorming, Git-Worktree, Branch-Completion, Verification]
    related_skills: [github-pr-workflow]
---

# Development Workflows — Full Software Development Lifecycle

Systematic methodologies for software development: from initial exploration and brainstorming through planning, implementation, testing, review, verification, branch completion, and merge. This umbrella skill covers the **entire SDLC as practiced by Hermes Agent** — use it whenever the task involves creating, modifying, verifying, or shipping software.

## How This Umbrella Works

Each lifecycle phase has a dedicated reference file. Load only the one(s) relevant to your current phase — don't load them all. The main SKILL.md gives you the pipeline overview and cross-phase guidance.

## Full Lifecycle Pipeline

```
Brainstorming → Write Plan → (Setup Worktree) → Execute → (Per-task: TDD + Code Review) → Verify → Finish Branch → (Review PR feedback) → Merge
```

| Phase | Reference | When to Use |
|-------|-----------|-------------|
| Brainstorming | `references/brainstorming.md` | Before any creative work — explore intent, requirements, design before implementation |
| Spike (validation) | `references/spike.md` | Throwaway experiments to validate an idea before committing |
| Write Plan | `references/writing-plans.md` | You have a spec/requirements for a multi-step task, before touching code |
| Setup Worktree | `references/using-git-worktrees.md` | Starting feature work needing isolation from current workspace |
| Execute in-session (subagents) | `references/subagent-driven-development.md` | Executing implementation plan with independent tasks — dispatch subagents per task |
| Execute in separate session | `references/executing-plans.md` | Executing a written implementation plan in a separate session with review checkpoints |
| Dispatching parallel agents | `references/dispatching-parallel-agents.md` | 2+ independent tasks with no shared state or sequential dependencies |
| TDD (test-first) | `references/test-driven-development.md` | Implementing any feature or bugfix — RED-GREEN-REFACTOR, tests before code |
| Request code review | `references/requesting-code-review.md` | After completing tasks, before merge — dispatch a reviewer subagent |
| Receive code review | `references/receiving-code-review.md` | Receiving code review feedback; verify before implementing |
| Debugging | `references/systematic-debugging.md` | Any bug, test failure, or unexpected behavior — 4-phase root cause investigation |
| Codebase reconnaissance | SKILL.md — "Codebase Architecture Reconnaissance" section | Understanding an unfamiliar project: architecture, data sources, conventions, git history |
| Verification gate | `references/verification-before-completion.md` | Before claiming work is complete, fixed, or passing |
| Finish branch | `references/finishing-a-development-branch.md` | Implementation complete, all tests pass — decide merge, PR, or cleanup |

Additional references (per-project patterns, not lifecycle phases):
- Debugging Tools (hands-on): `references/debugging-tools.md` — debugpy and Node --inspect commands
- Kubernetes Service Log Chain Tracing: `references/kubernetes-service-log-chain-tracing.md` — trace HTTP failures through multi-container microservice pipelines by reading logs backwards
- Full-Stack Scaffolding: `references/full-stack-scaffolding.md` — rapid NestJS+NextJS projects
- Cross-Repo Feature Analysis: `references/cross-repo-feature-analysis.md` — analyze a feature and evaluate portability
- Model Integration Audit: `references/model-integration-audit.md` — audit whether a model is supported
- DeepSeek-Viettel Integration: `references/deepseek-viettel-integration.md` — server quirks
- Next.js Server Component Performance: `references/nextjs-server-component-performance.md` — diagnose "Rendering..." stalls from multiple DB round trips, fetch-all-then-sort patterns, and `force-dynamic` misuse in server components
- Java Microservice Log-to-Code Debugging: `references/java-microservice-log-to-code-debugging.md` — after kubernetes-service-log-chain-tracing identifies the failing pod, trace the exact code path (exception handling patterns, NPE data flow through MapStruct mappers, URL routing logic, config profile awareness) to find the root cause

## Cross-Phase Guidance

### How Brainstorming, Plans, and Execution Fit Together

The canonical pipeline is: **Brainstorming → Write Plan → Execute → Verify → Finish**.

1. **Brainstorming**: Explore requirements, propose approaches, get user approval on design. Output: `docs/superpowers/specs/<topic>-design.md`.
2. **Write Plan**: Break spec into bite-sized implementation tasks with exact file paths. Output: `docs/superpowers/plans/<topic>.md`.
3. **Execute** (subagent-driven-development or executing-plans): Implement task by task with TDD + code review per task.
4. **Verify**: Run fresh tests, confirm claims with evidence.
5. **Finish Branch**: Present merge/PR/cleanup options, execute choice.

### When to Use Subagents vs In-Session Execution

| Situation | Use |
|-----------|-----|
| Tasks are independent, you have subagents | `references/subagent-driven-development.md` — fresh per-task subagent |
| Tasks are tightly coupled or session must continue | Execute directly in session with TDD |
| Separate parallel session requested | `references/executing-plans.md` |
| 2+ independent failure investigations | `references/dispatching-parallel-agents.md` |

### Code Review: Requesting vs Receiving

- **Requesting** (before merge or between tasks): You have made changes, need a reviewer to catch issues. Dispatch a reviewer subagent. See `references/requesting-code-review.md`.
- **Receiving** (after getting feedback): Someone else reviewed your work. Verify each suggestion before implementing — don't performatively agree. See `references/receiving-code-review.md`.

### The Verification Gate

Before claiming *anything* is complete, fixed, or passing: run the full command fresh, read the full output, confirm exit code and failure count. Evidence before assertions, always. See `references/verification-before-completion.md`.

## Codebase Architecture Reconnaissance

Use this pattern when asked to understand an unfamiliar project: what it does, its data sources, its conventions, and its current state (git history).

### Workflow

1. **Discover project structure** — `search_files(target="files", pattern="*")` to understand layout. Look for key orientation files:
   - `README.md`, `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md` — project conventions
   - `.env.example`, `docker-compose.yml` — infrastructure dependencies
   - `package.json`, `pyproject.toml`, `go.mod` — tech stack

2. **Trace data flow** — find where database/API connections are established:
   - Search for env var usage patterns (`process.env.*`, `os.getenv`) to find connection strings
   - Find the actual DB client/connection file and read it: what databases, what indices/collections, auth method
   - Distinguish **data sources** (where content lives) from **operational stores** (users, audit, config) — they often differ

3. **Follow the file dependency chain** — start from infrastructure layer (DB, config) and work outward to page/UI code. For Next.js: `lib/` → `components/` → `app/` (pages + API routes)

4. **Read git history** for project evolution — `git log --oneline --all` shows:
   - Commit conventions (prefix like `feat(TASK-xxx):`, `fix:`, `docs:`)
   - Branch structure (main/master, PRs)
   - Feature chronology — groups of related commits reveal development phases

5. **Understand project conventions** from `CLAUDE.md` or equivalent — these encode:
   - How to bump versions, where changelogs live
   - Commit message format
   - Technical rules (e.g. "never hard-code credentials", "public pages must survive DB outage")

6. **For startup/deployment errors** — trace the error back to config:
   - `ECONNREFUSED` on localhost:9200 → Elasticsearch not running or wrong URL
   - `MongoNetworkError` → MongoDB not running or wrong URI
   - **Check `.env.example` for defaults**, then check if `.env.local` exists with overrides
   - For Next.js Turbopack: errors appear on server + client (duplicate stack traces in console)

### Output

Concisely state: what the project is (tech stack + purpose), the data sources (which DB and what each stores), project conventions and how tasks are organized, and what's been done (from git). When there's a startup error, state the root cause clearly — one line of diagnosis, no speculation.

### Pitfalls

1. **Hard-coding assumption** — just because code shows `localhost:9200` as default doesn't mean that's the _actual_ running config. Check `.env.local`.
2. **Conflating DBs** — CMS projects often have separate read-only data DB (ES) and write DB (Mongo). Don't treat them as interchangeable.
3. **Missing the CLAUDE.md** — if the project has one, it's the single best source of conventions. Always check first.
4. **Stopping at file count** — the number of files tells you little. Follow the dependency chain from infrastructure outward.
5. **Not reading git history** — git log is the fastest way to see what's been built and in what order. On a project with organized commit prefixes, chronological groups reveal phases instantly.

## Common Pitfalls

1. **Skipping the plan step** on complex tasks leads to scope creep and rework.
2. **TDD without refactor step** creates messy but passing code — every cycle must end with refactor.
3. **Spike findings not documented** — always summarize before destroying the branch.
4. **Code review only after pushing** — review before push catches more.
5. **Half-understood bugs** — Phase 3 (understanding mechanism) is the most skipped but most critical debugging step.
6. **Performative agreement on review feedback** — verify before implementing; push back with technical reasoning when wrong.
7. **Claiming completion without fresh verification** — evidence before assertions, always.
8. **Skipping TDD because "it's simple"** — simple code breaks too; a test takes 30 seconds.
9. **No worktree isolation** — modifying a working checkout directly risks breaking ongoing work; use worktrees or the platform's native isolation.
10. **Over-linking task dependencies** — "finally check X" does not mean X depends on implementation if X is static config/docs discovery.
