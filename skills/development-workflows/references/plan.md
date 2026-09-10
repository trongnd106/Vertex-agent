# Plan — Writing Actionable Plans

Write detailed, actionable plans before starting complex work.

## When to Plan

- Complex features with multiple files/modules
- Refactoring across the codebase
- Any task where scope creep is likely
- Architecture changes affecting multiple subsystems

## The Plan Template

Write to `.hermes/plans/<topic>.md`:

```markdown
# Plan: <Topic>

## Goal
<One sentence about what we're building>

## Files to Change
- `src/auth/login.py` — add OAuth refresh flow
- `src/auth/token.py` — new file, JWT token management
- `tests/test_auth.py` — add refresh flow tests

## Steps (in order)
1. **Add token refresh model** — `src/auth/token.py`
   - `Token.refresh()` method
   - Handles expiry, concurrency guard
2. **Wire into login flow** — `src/auth/login.py`
   - Call `Token.refresh()` on 401
   - Retry original request
3. **Add tests** — `tests/test_auth.py`
   - Test refresh with valid token
   - Test refresh with expired token
   - Test concurrent refresh guard

## Risks
- Rate limiting on upstream auth provider
- Token race condition under high concurrency (mitigated by lock)

## Acceptance Criteria
- [ ] Login succeeds after token expiry without user-visible delay
- [ ] No duplicate refresh requests under load
- [ ] Tests pass
```

## Rules

1. **Planning only — no execution.** Don't implement in the plan.
2. **Be specific.** Each step should reference exact file paths.
3. **List risks and edge cases** before starting.
4. **Commit the plan** before beginning work.
5. **Update the plan** if you discover new requirements during implementation.
