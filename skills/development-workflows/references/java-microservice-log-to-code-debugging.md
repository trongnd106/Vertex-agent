# Java Microservice Debugging: From Log to Code to Root Cause

Extend Kubernetes log chain tracing with **code-level validation** — after identifying which service in the chain is failing, read the source code to determine *why* and *where* the error is produced, not just *what* the error message says.

## When to Use

After `references/kubernetes-service-log-chain-tracing.md` has identified the failing pod/service. You now need to:

- Distinguish "upstream is down" from "upstream returned 500 because of data error"
- Trace a NullPointerException or generic "Internal Server Error" to the exact line of code
- Understand whether a `catch (Exception ex)` is masking the real failure
- Follow the data flow from controller → service → repository/mapper → upstream HTTP call

## The Code-Level Diagnosis Process

### Phase 1: Map Log Lines to Source Files

Every log line contains clues to the exact file and line:

| Log Clue | What to Find |
|----------|-------------|
| `at com.nlp.module.service.impl.SearchNlpServiceImpl.search(SearchNlpServiceImpl.java:66)` | The **exact** line in source code |
| `ERROR java.lang.NullPointerException` | Follow the first line of the stack trace that's in YOUR code (not Spring/JDK internals) |
| `call api %s fail` or `ERROR %s` | Look for the matching `log.info` / `log.error` call in the source |
| `response {"return_code":"500"}` | Find the `return new BaseResponse("500", ...)` line |

**The rule:** The first stack frame in YOUR package (e.g. `com.nlp.module.*`) is usually the crash point. Frames like `$$EnhancerBySpringCGLIB$$` or `$FastClassBySpringCGLIB$` are Spring AOP proxies — skip them, the next YOUR-code frame below them is the real caller.

### Phase 2: Trace the Exception Handling Pattern

Java Spring Boot services commonly use this pattern:

```java
public BaseResponse someMethod(Request request) {
    try {
        // ... actual logic ...
    } catch (Exception ex) {
        log.error("ERROR {}", ExceptionUtils.getStackTrace(ex));
    }
    return new BaseResponse("500", "Internal Server Error");
}
```

**This is dangerous because:** Every failure path returns the SAME `"500"` response. The caller cannot distinguish:
- Upstream service down (Connection refused)
- NullPointerException from bad data
- Configuration error (wrong URL, missing field)
- MongoDB connection failure

**On the debugging side,** the error IS logged locally (via `ExceptionUtils.getStackTrace(ex)`), so you MUST read that pod's log, not just the caller's log.

### Phase 3: Trace Data Flow for NPE Debugging

When the log shows `NullPointerException` at `YourMapper.java:130`, here is how to reconstruct the null chain:

**Step 1: Read the exact line in source code**
```
TrainingMapper.java:130:
    intentMap.get(item.getIntentName()).getId()
```

**Step 2: Identify which variable is null**
- `item` is the loop variable → cannot be null (it's from a non-null list)
- `item.getIntentName()` returns a String → could be null if Excel cell is blank
- `intentMap` is the Map parameter → could be empty but not null (passed from caller)
- `intentMap.get(name)` returns null when the key doesn't exist in the map → MOST LIKELY

**Step 3: Trace where the Map was built**
```java
// TrainingServiceImpl.java:263-265
Map<String, Intent> intentMap = intentRepository.findByNameIn(data.stream()
    .map(item -> item.getIntentName().trim()).distinct().collect(Collectors.toList()), botId)
    .stream()
    .collect(Collectors.toMap(Intent::getName, item -> item));
```

Key observations:
- The `.distinct()` reduces the list — some names may be merged
- The Map key is `Intent::getName` (from MongoDB field `name`)
- The lookup key is `item.getIntentName()` (from Excel file)
- **If Excel has a name that MongoDB didn't return**, `get()` returns null → NPE

**Step 4: Check for silent empty returns in repositories**

Many MongoDB repositories return empty lists on error:
```java
public List<Entity> findEntityByWordIn(List<String> words, String botId) {
    List<Entity> results = new ArrayList<>();
    try {
        results = mongoTemplate.find(...);
    } catch (Exception ex) {
        log.error("ERROR {}", ExceptionUtils.getStackTrace(ex));
    }
    return results;  // empty list on any error
}
```

This means: if MongoDB is unreachable or a query fails, the method returns an **empty list silently** (logged but not rethrown). Downstream code treats it as "no data found" when the real problem is "could not query."

**The "0 size" trap:** When logs show `find EntityGroup have 0 size` AND `find Entity have 0 size`, check:
1. Is MongoDB actually reachable? (Could be a separate failure from the HTTP error)
2. Is the query criteria correct? (wrong `bot_id` → no results)
3. Or is the data genuinely empty in this environment? (dev vs prod)

### Phase 4: Trace the URL Routing for HTTP 500

When the log shows `call api %s fail`, trace the URL construction:

```java
// SearchNlpServiceImpl.java:65-66
String url = model.getDomain(request.getBotId()) + model.getSearchUrl();
SearchNlpResponse response = restApiService.post(url, request, SearchNlpResponse.class);
```

Check the NlpModelConfig:
```java
// NlpModelConfig.java:25-32
public String getDomain(String botId){
    if (botVds.contains(botId)){    // botVds is a single ID string
        return domainVds;           // K8s internal URL or external prod URL
    }
    return domain;                  // dev localhost or external prod URL
}
```

**The `botVds.contains(botId)` check is unusual** — `contains()` on a String checks for substring match, not equality. If `botId` is a substring of `botVds` or vice versa, the routing changes. This can cause:
- A bot that should use the external domain being routed to the internal cluster URL
- Or vice versa, depending on the actual IDs

### Phase 5: Multi-Config Profile Awareness

Spring Boot supports multiple config profiles (e.g., `application.properties` vs `prod/application.properties`). These can differ significantly:

| Property | Dev (default) | Prod |
|----------|--------------|------|
| `nlp.model.domain` | `http://localhost:9301` | `https://nlp-intent.viettelai.vn` |
| `nlp.model.domain-vds` | `http://monengine...svc.cluster.local:9301` | `https://nlp-intent.viettelai.vn` |
| `nlp.model.llm-gen-url` | `http://localhost:8280/...` | NOT SET |
| `server.port` | `6868` | `9868` |

**When debugging a deployed service:**
1. Confirm which config profile is active (check env var `SPRING_PROFILES_ACTIVE`)
2. If no profile is set, the default `application.properties` is used — which may have `localhost` URLs that DON'T work in Kubernetes
3. A missing `llmGenUrl` in prod config means LLM gen calls will fail silently (caught exception, returns 500)

## Common Root Cause Patterns in This Architecture

### Pattern A: Upstream Service Down
**Log signature:** `Connect to <host>:<port> failed: Connection refused`  
**Code:** `restApiService.post(url, request, ResponseClass.class)` via `RestTemplate`  
**Fix:** Check the upstream pod (restart, check readiness probe, check selector labels match service)

### Pattern B: NullPointerException from Map lookup
**Log signature:** `ERROR java.lang.NullPointerException` at `TrainingMapper.java:130` (or similar mapper line)  
**Code:** `map.get(key).getId()` — the key is present in your list but absent from the database  
**Fix:** Add null guard before calling `.getId()` / `.getLabel()`, or use `getOrDefault()` / check `containsKey()` first  
**Prevention:** Log the missing keys so they can be detected: `log.warn("Missing intent: {}", name)`

### Pattern C: Silent try-catch swallows real error
**Log signature:** Error logged in the service's STDOUT but caller sees generic `"500"` response  
**Code:** `catch (Exception ex) { log.error(...); } return new BaseResponse("500", ...)`  
**Debugging:** The real error is in the LOCAL pod's log, not propagated to the caller. Read BOTH logs.

### Pattern D: Data mismatch between import file and database
**Log signature:** Import reads N rows successfully, finds M < N intent names in DB, then NPE  
**Root cause:** Excel contains intent names that don't exist in MongoDB for that bot_id  
**Fix:** Validate all intent names against the DB lookup before processing; skip or warn on unknown names

### Pattern D1 (subclass): Trailing whitespace in Excel cells causes false mismatch
**Log signature:** Same as Pattern D, but DB actually has all intent names (M = N after `.trim()`).
**Root cause:** Java code uses `.trim()` during `.distinct()` collection but **does not trim** during the per-row lookup. Example:
```java
// BUG: distinct+trim creates deduped key set
.map(item -> item.getIntentName().trim()).distinct()
// BUG: lookup does NOT trim — trailing space causes miss
intentMap.get(item.getIntentName())  // ← "Tên Ý định " ≠ "Tên Ý định"
```
**Detection (offline):** Verify the Excel file programmatically with Python + openpyxl to count cells with leading/trailing whitespace:
```python
import openpyxl
wb = openpyxl.load_workbook('file.xlsx')
ws = wb.active
bad = 0
for row in ws.iter_rows(min_row=2, values_only=True):
    name = str(row[2]).strip() if row[2] else ''
    if name and name != name.strip():
        bad += 1
        print(f'Row {row[0].row}: {repr(name)}')
```
**Fix:** Add `.trim()` to the lookup key in Java, or trim during Excel parsing (in `readRow()`). Defensive guard: check `if (intent == null) continue;` before dereferencing.

### Pattern D2 (subclass): `Collectors.toMap` throws on duplicate keys
**Log signature:** `IllegalStateException: Duplicate key` (NOT NPE) during import.
**Root cause:** `Collectors.toMap(keyMapper, valueMapper)` throws immediately when two stream elements produce the same key. This can happen when MongoDB returns multiple documents with the same `name` field for a `bot_id`.
```java
// CRASHES if two Intents have the same name:
.collect(Collectors.toMap(Intent::getName, item -> item));
```
**Fix:** Use the merge-function overload: `.collect(Collectors.toMap(Intent::getName, item -> item, (a, b) -> a));` or use a grouping collector if duplicates are expected.

### Pattern E: Empty repository results due to MongoDB failure
**Log signature:** `find EntityGroup have 0 size` followed by error in same request  
**Root cause:** Either (a) MongoDB is unreachable and repository returns empty list, or (b) no entities exist for that bot_id  
**Fix:** Distinguish "no data" from "can't query" — check if MongoDB connection succeeds first

## Pitfalls

1. **Don't trust "0 size" at face value** — an empty result can be a genuine query return OR a swallowed MongoDB connection failure. Check for preceding connection errors.
2. **AOP proxy frames in stack traces** — `CglibAopProxy`, `FastClassBySpringCGLIB`, `EnhancerBySpringCGLIB` are Spring AOP proxies. The real code is in the frame BEFORE or AFTER these.
3. **$FastClass vs $$Enhancer** — `$FastClass` is the caller (proxied method), `$$Enhancer` is the proxy itself. The frame BEFORE `$$Enhancer` is the real controller/service.
4. **Spring Boot profiles change everything** — `application.properties` values are NOT the production values. Always check which profile is active.
5. **Multi-threaded logs** — Thread IDs (e.g., `http-nio-6868-exec-2`) help isolate a single request's log lines from concurrent ones.
6. **`contains()` is not `equals()`** — `String.contains()` in routing logic can produce unexpected matches. In the tracing session, `botVds.contains(botId)` uses substring matching which may route incorrectly if IDs share prefixes.
7. **Excel cell whitespace is invisible in logs** — `"Tên "` and `"Tên"` look identical when printed in application logs because trailing whitespace is visually indistinguishable. Always verify the raw Excel file programmatically (not by eye) when investigating NPE during import.
8. **Sparse Excel templates waste iteration** — POI `sheet.getLastRowNum()` returns the highest row index in the file, which can be 1M+ due to template formatting even though only a few thousand rows have data. The code loops through all of them checking `sheet.getRow(i) != null`. This is wasteful but not buggy — the real cost is developer debugging time when trying to estimate data size from log row counts vs template max_row.
