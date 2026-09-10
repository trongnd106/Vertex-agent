---
name: nextjs-server-component-performance
description: Diagnose and fix performance bottlenecks in Next.js App Router server components — slow rendering, "Rendering..." stalls, excessive DB round trips.
---

# Next.js Server Component Performance Debugging

## The Pattern: "Rendering..." Stalls on Every Navigation

**Symptom**: Every link click (pagination, tab switch, sort toggle) shows "Rendering..." in the browser for seconds. The page is a server component with `export const dynamic = "force-dynamic"`.

## Root Cause Checklist

### 1. `force-dynamic` + Multiple Sequential DB Round Trips

Every navigation triggers a fresh server-side render. Each round trip to an external service (ES, MongoDB, API) adds latency. Common pattern:

```typescript
export const dynamic = "force-dynamic"; // ← no caching at all

// 1st round trip: ES aggregation (counts)
const aggRes = await esSearch(index, { ... });

// 2nd round trip: ES search (data)
const listRes = await esSearch(index, { ... });

// 3rd round trip: MongoDB users (for filter dropdown)
const users = await db.collection("users").find(...).toArray();

// 4th round trip: MongoDB overrides (for edit tracking)
const ovs = await db.collection("overrides").find({ _id: { $in: lawIds } }).toArray();
```

**4 network round trips** serialized before HTML arrives. If each is ~50ms: 200ms + JS sort + render time → visible "Rendering...".

**Fix strategies** (in order of preference):
- **Use React Cache** — `React.cache()` for user lists that rarely change.
- **Co-locate reads** — Use `Promise.all()` when there are no data dependencies between calls.
- **Reduce data fetched on every request** — E.g., fetch users list once and cache it.
- **Consider ISR or revalidation-based caching** instead of `force-dynamic` when data doesn't need to be perfectly fresh on every render.

### 2. Sort-by-External-Data: Fetch-All-Then-Sort-in-JS

When sorting by a field not in the primary data store (e.g., sorting ES results by a MongoDB field), the common anti-pattern is:

```typescript
const shouldFetchAll = sortBy === "lastEdit";
// Fetch UP TO 10000 docs from ES
const listRes = await esSearch(index, {
    query,
    sort: [{ lawId: "desc" }],
    from: shouldFetchAll ? 0 : 0,
    size: shouldFetchAll ? 10000 : 40,
});
// Fetch overrides for all 10000 lawIds from MongoDB
const ovs = await db.collection("overrides").find({ _id: { $in: lawIds } }).toArray();
// Sort in JS
hits.sort((a, b) => { ... });
// Paginate after sort
hits = hits.slice(startIdx, endIdx);
```

**Problems:**
- ES fetch 10K docs is expensive (hits `max_result_window` limit)
- MongoDB `$in` with 10K IDs is expensive
- JS sort of 10K items on server adds CPU time
- Pagination is broken (user sees page 1 sorted correctly, but page 2 excludes any data not in the first 10K)

**Better approaches** (ordered from best to acceptable):

1. **Denormalize sort field into primary store** (best):
   - When writing to MongoDB, also `esUpdateByLawId` to stamp `lastEditAt` and `lastEditBy` on the ES doc.
   - Then sort directly in ES: `sort: [{ lastEditAt: { order: "desc", missing: "_last" } }]`
   - No fetch-all needed. `size: 40`, `from: page * PAGE_SIZE`.
   - **Concrete pattern** — after each MongoDB write of non-ES data (e.g., `overrides` collection), stamp the corresponding ES doc:
   ```typescript
   // In each route that writes to MongoDB:
   await col.updateOne(filter, { $set: { patch, updatedBy, updatedAt } }, { upsert: true });
   // Also write back to ES so frontend can sort/filter without MongoDB query:
   try {
     await esUpdateByLawId(DOC_INDEX, lawId, {
       lastEditAt: new Date().toISOString(),
       lastEditBy: s.username,
     });
   } catch { /* best-effort */ }
   ```
   - Frontend reads `h._source.lastEditAt` and `h._source.lastEditBy` directly from ES hits, no MongoDB join needed.
   - Filter by editor: `{ term: { "lastEditBy.keyword": editorName } }`
   - Filter by date range: `{ range: { lastEditAt: { gte: startISO, lte: endISO } } }`
   - **Backfill script** for existing data: use ES `_update_by_query` with painless script, iterate MongoDB docs in batches.

2. **Use API route + client-side fetch** (acceptable):
   - Keep the ES query normal (40 docs per page).
   - Create a lightweight API: `GET /api/van-ban/last-edits?lawIds=1,2,3,...` returning only edit dates.
   - Client fetches the page + edit dates together, sorts on client.
   - Limitation: can only sort within the current page (40 items).

3. **Pre-compute sort order periodically** (band-aid):
   - A cron job flattens sort-order data into a dedicated ES field every N minutes.
   - Works for non-real-time sort needs.

### 3. Unnecessary Data Fetched on Every Request

Common: fetching the entire users list (for a filter dropdown) on every page load.

```typescript
// This runs on EVERY request to this page
const users = await db
    .collection("users")
    .find({ active: true })
    .sort({ username: 1 })
    .toArray();
```

**Fix:**
```typescript
import { cache } from "react";

const getActiveUsers = cache(async () => {
    const db = await getDb();
    return db.collection("users")
        .find({ active: true }, { projection: { username: 1 } })
        .sort({ username: 1 })
        .toArray();
});
```

### 4. Missing Indexes

`$in` queries on MongoDB `_id` are fast for small sets, but degrade with thousands of IDs. For collection `overrides` where `_id = lawId`, ensure:
- The `_id` index exists (always does by default in MongoDB).

For the ES side, check `max_result_window`:
```
GET /${INDEX}/_settings
```
If `max_result_window` is the default 10000 and the index has 128K docs, `size: 10000` returns the first 10K only — not a full dataset. Pagination won't be accurate beyond page 250 (10000/40).

## Diagnostic Queries

Measure each round trip independently:

```typescript
console.time("es-aggregation");
const aggRes = await esSearch(...);
console.timeEnd("es-aggregation");

console.time("es-search");
const listRes = await esSearch(...);
console.timeEnd("es-search");

console.time("mongo-users");
const users = await db.collection("users").find(...).toArray();
console.timeEnd("mongo-users");

console.time("mongo-overrides");
const ovs = await db.collection("overrides").find(...).toArray();
console.timeEnd("mongo-overrides");
```

For the database layer itself:
```bash
# Check MongoDB slow queries (> 100ms)
mongosh --eval "db.setProfilingLevel(1, { slowms: 100 })"
# Check ES query timing
curl -X POST "${ES_URL}/${INDEX}/_search" -H 'Content-Type: application/json' \
  -d '{"query": {...}, "profile": true}'
```

## Pitfalls

1. **`force-dynamic` is a hammer** — it disables ALL caching. Try to scope it to specific data needs with `unstable_noStore()` instead.
2. **Fetch-all limits** — ES `max_result_window` caps `from`+`size` at 10000 by default. Sorting 10K docs that are only the first 10K hits gives wrong results past page 250.
3. **MongoDB `$in` scaling** — `find({ _id: { $in: [10000 IDs] } })` is slow even with `_id` index. Break into batches of 1000 or use a different approach.
4. **Client-side "Rendering..." means server-side blocking** — the browser waits for the server component to fully resolve. Every `await` in the component tree adds to this wait. Profile with `console.time` to find the bottleneck.
