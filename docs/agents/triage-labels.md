# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the "Label in our tracker" column to match whatever vocabulary you actually use.

## Supplementary Labels

### Types
- `epic`: High-level initiatives tracking multiple child issues.
- `enhancement`: New features or behavioral expansions.
- `refactor`: Structural and code simplifications without behavioral regressions.
- `bug`: Defects or regressions.
- `documentation`: Guides, specs, and architectural documentation.

### Functional Areas
- `area:agent`: Agent runtime, system prompts, personas, and toolsets.
- `area:ui`: Frontend components, CSS design tokens, and user ergonomics.
- `area:jobs`: Databricks Lakeflow jobs, cron triggers, and scheduled turns.
- `area:storage`: Lakebase Postgres schemas, state persistence, and workspace storage.
