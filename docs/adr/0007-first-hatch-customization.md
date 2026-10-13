# 0007 - First‑Hatch Customization Flow

**Status**: Accepted

## Context

We need a way for new users to personalize their agent experience during the very first interaction (the “hatch”). The feature should:
- Persist a `UserProfile` in Lakebase.
- Provide an API endpoint to fetch and save the profile.
- Prefill the chat composer with a custom greeting and initial prompts.
- Enforce budget caps to avoid runaway token usage.
- Integrate seamlessly with existing turn handling and the birth‑ritual logic.

## Decision

Implement a first‑hatch flow that:
1. Introduces a new `UserProfile` shape stored in Lakebase.
2. Adds `GET /api/hatch` (status) and `POST /api/hatch` (save profile) endpoints.
3. Uses a `save_profile` tool invoked by the agent to persist the profile.
4. Updates the birth‑ritual activation logic to trigger on any matching wake‑up phrase, even mid‑session.
5. Caps the budget for `USER.md` to keep token usage bounded.
6. Provides comprehensive tests covering the new flow and edge‑cases.

## Consequences

- New API surface (`/api/hatch`) is now part of the public contract.
- Agent code now depends on Lakebase persistence for profiles.
- Documentation and ADRs must be kept up‑to‑date for future maintainers.
- No breaking changes to existing functionality; the feature is additive.

---

*Recorded on 2026‑10‑11*
