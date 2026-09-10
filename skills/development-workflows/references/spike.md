# Spike — Validation Experiments

Run throwaway experiments to validate a technical approach before committing to a full implementation.

## When to Spike

- Unknown technical approach (new library, new API, new pattern)
- Performance uncertainty (will this library handle 10K req/s?)
- Architecture decision (should we use WebSockets or SSE?)
- Learning a new tool before using it in the real project

## The Spike Protocol

1. **Set the question** — one specific question the spike must answer
2. **Create a spike branch:** `git checkout -b spike/<topic>`
3. **Write the minimum code** to answer the question (skip tests, error handling, docs)
4. **Run the experiment** and collect results
5. **Document findings** — summarize what you learned, the answer, and any surprises
6. **Discard the branch** — never merge a spike into main

## Naming Convention

```
git checkout -b spike/router-benchmark
git checkout -b spike/webgpu-feasibility
```

If no git repo, use a temp directory: `cd $(mktemp -d)`

## Output Format

After completing the spike, write a brief summary:

**What I wanted to know:** <the spike question>
**What I did:** <quick description of the experiment>
**Result:** <the answer — yes/no/it depends>
**Notable findings:** <surprises, edge cases, limitations>
**Recommendation:** <should we proceed with this approach?>
