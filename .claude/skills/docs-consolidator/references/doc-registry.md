# Document Registry

Each doc has ONE purpose. Information belongs in the doc that owns that domain.

| File | Purpose | Owns |
|------|---------|------|
| `docs/CLAUDE.md` | Orientation for Claude Code sessions: conventions, commands, gotchas, quick-reference | Session workflow, quality standards, commands, principles, common tasks, mistakes to avoid |
| `docs/PRD.md` | Product requirements: user stories, feature specs, business rules | Requirements (functional IDs), user stories, success criteria, non-goals, glossary |
| `docs/ARCHITECTURE.md` | System design: components, data flow, storage, concurrency, deployment | Component interfaces, data flow diagrams, concurrency model, error handling, schemas, config, deployment, dependencies, file structure, testing strategy |
| `docs/TASKS.md` | Development tasks and progress tracking | Milestones, task checklists, progress summary |

## Overlap Rules

- Architecture details (diagrams, component interfaces, schemas, data flow) → `ARCHITECTURE.md`, not PRD or CLAUDE.md
- Product requirements (feature specs, user stories, success criteria) → `PRD.md`, not ARCHITECTURE
- Task tracking (milestones, checklists, progress) → `TASKS.md`, not other docs
- Session orientation (workflow, commands, quick-reference interfaces, gotchas) → `CLAUDE.md`, kept lean with pointers to other docs
