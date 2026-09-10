# Kubernetes Service Log Chain Tracing

Trace a failing request through multiple microservice containers by reading each service's logs backwards — from caller to callee.

## When to Use

- A caller service (e.g. dialog manager) reports HTTP 500 from an internal service
- You have access to Kubernetes container logs but no distributed tracing (Jaeger/Zipkin)
- The error message is generic ("Internal Server Error") with no detail
- You need to distinguish "service is down" from "service responded with error"

## The Technique

### Step 1: Identify the call chain

Read the caller's log to extract:
- **Endpoint called** (URL + path)
- **Request body** sent
- **Response received**
- **Timestamps** (request vs response latency)

From the log record, identify the downstream URL. Example:
```
call api http://service-b:8081/api/search with request {...}
```

### Step 2: Get the downstream service's log

Use the same timestamp window to read the downstream container's log. Look for:
- HTTP method + path match (e.g. `[Post] /search/nlp`)
- The exact request body from the caller
- The downstream's own `call api` to its next hop

### Step 3: Walk the chain backwards

Repeat until you reach the terminal service (the one that does NOT make any further HTTP calls for this request).

At each hop, check:
1. **Does it receive the request?** If no → connectivity/DNS issue between caller and callee (UnknownHostException, Connection refused, timeout)
2. **Does it make an upstream call?** If no → the service itself is failing before sending
3. **What does the upstream return?** Match the response against expectations

### Step 4: Root cause identification

Classify the terminal failure:

| Symptom | Likely Cause |
|---------|-------------|
| `Connection refused` (java.net.ConnectException) | Downstream pod crashed / port not listening / service selector mismatch |
| `UnknownHostException` | DNS resolution failure — service name doesn't exist or pod can't resolve cluster DNS |
| `Connection timed out` (readTimeout) | Downstream pod is overloaded, hung, or firewall blocks port |
| HTTP 500 with stack trace | Downstream app exception — needs that service's log |
| HTTP 404 | Wrong URL path — route not registered in downstream controller |
| Empty response / `null` data | Downstream app returned without body — possible NPE or early return in handler |

### Step 5: Distinguish proxy vs origin failures

Many services act as **proxies/gateways** — they forward requests to another service and return the result. If a proxy returns HTTP 500:

1. Check if the proxy's own log shows it successfully called the upstream
2. If `call api search fail` appears in proxy log → the upstream is the real problem
3. If the proxy never attempted an upstream call → the proxy's own code is crashing (NullPointerException, config error)

**Rule of thumb:** The "Internal Server Error" message almost always comes from the service that *caught* the exception, not the service that *threw* it. Keep walking the chain.

## Real-World Example

```
chatbot-public-dialog (dialog)
  ↓ POST /search/nlp
chatbot-public-intent-ner-nlp (proxy/gateway)
  ↓ POST /api/v1/cyberbot/nlp/search  
monengine-vds.chatbot-nlp-vds.svc.cluster.local:9301 (origin)
```

- Dialog log: `response api nlp {"message":"Internal Server Error","data":null,"return_code":"500"}`
- Proxy log: `ERROR - Connect to monengine-vds...:9301 failed: Connection refused`
- **Root cause:** `monengine-vds` pod is not listening on port 9301. Proxy is healthy.

## Pitfalls

1. **Log timestamps may not align exactly** — services may have slightly different clocks. Use a range around the caller's timestamp.
2. **Pod restarts reset log history** — if a pod restarted, its log may only cover recent activity. Check `grep -i "Started Main"` to confirm startup time.
3. **Thread IDs matter** — a multi-threaded service interleaves multiple concurrent requests in the log. Match request bodies, not just timestamps.
4. **Not all services log request bodies** — some only log the URL. You may need to add logging at the service level.
5. **Kubernetes log rotation** — `kubectl logs --tail=N` may miss the relevant lines. Use `--since=5m` or full timestamp-based grep.
