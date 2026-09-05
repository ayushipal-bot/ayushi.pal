# Task 2 — Agent Workflow Debugging & System Design

## Given workflow

```
User -> LLM -> Search Knowledge Base -> LLM -> Order API (if needed) -> LLM -> Response
```

## 1. Technical problems in the given workflow

1. **No routing/decision step before acting.** The LLM always searches the
   KB and is trusted to also decide, mid-conversation, whether to call the
   order API — there's no explicit gate, so it can call the API when it
   isn't needed (cost, latency) or skip it when it is (wrong answers).
2. **No grounding boundary.** The final "LLM" step can freely mix retrieved
   text, tool output, and its own prior knowledge with no rule saying "only
   use what was retrieved/returned" — this is the direct cause of
   hallucinated order statuses/policies.
3. **No idempotency/state for the order API call.** Nothing tracks "have I
   already made this exact call for this request" so retries (by the user,
   a proxy, or the LLM itself re-deciding to call the tool) duplicate the
   call — as observed.
4. **No timeout/retry policy on the external API.** An 8-10s or hanging
   call blocks the whole pipeline synchronously; one slow/down dependency
   makes every request slow, with no circuit breaker or cached fallback.
5. **No relevance filtering on retrieval.** All top-k KB documents are
   passed through regardless of similarity score, so irrelevant documents
   dilute/mislead the final generation step.
6. **No error handling between stages.** If retrieval or the tool call
   throws, there's no defined fallback — the failure either crashes the
   request or (worse) is silently absorbed by the LLM, which then guesses.
7. **No observability.** No logging of what was retrieved, what the model
   decided, what the tool returned, or how long each stage took — so the
   reported symptoms (wrong answers, duplicate calls, slowness) can't be
   diagnosed from production data.

## 2. Redesigned workflow

The key change: replace "LLM decides implicitly, mid-chain" with an
explicit **routing step** that classifies intent once, up front, and a
**verified-context assembly** step that gates what the final generation is
even allowed to see.

```
1. User message received
2. Input validation (empty message, malformed order id) -> early response if invalid
3. Router: classify intent -> {kb_only, tool_only, kb_and_tool, none}
     - based on extracted order id / order-related keywords + presence of a
       retrievable topic; in a fuller system, this classification step
       itself can be an LLM call constrained to output one of these labels
       (function-calling / structured output), not free text.
4. If kb_only or kb_and_tool:
     a. Retrieve top-k documents
     b. Filter by relevance threshold -> keep only docs above threshold
5. If tool_only or kb_and_tool:
     a. Check idempotency store for (user, request_id) -> reuse cached
        result if already executed
     b. Otherwise call order API with timeout + retry policy
     c. Record result (or error) in idempotency store
6. Assemble "verified context" = {filtered_docs, tool_result_or_error}
     - if verified context is empty -> respond "cannot verify", skip LLM
       generation entirely (cheaper and strictly grounded)
7. LLM generation, constrained by system instruction (Q7) to only phrase
   an answer from verified context, never to add outside facts
8. Log every stage (routing decision, retrieval scores, tool latency/
   outcome, generation) with a request id
9. Return response to user
```

Diagram form:

```
User
  |
  v
Validate input
  |
  v
Router (intent classification)
  |-- kb_only ------> Retrieve + filter --------------------\
  |-- tool_only ----> Idempotency check -> Order API --------> Assemble
  |-- kb_and_tool --> (both of the above, in parallel) -------/   verified
  |-- none ---------> skip straight to "cannot verify" ------/    context
  v
LLM generation (verified context only, per system instruction)
  |
  v
Response (+ structured log)
```

Retrieval and the tool call are independent once routed, so for
`kb_and_tool` they can run concurrently instead of sequentially, cutting
latency.

## 3. Preventing duplicate order API execution (idempotency/state)

- Generate (or accept from the client) a **request id** per user turn, and
  derive an idempotency key from `(user_id or session_id, order_id,
  request_id)`.
- Before calling the API, check a shared store (Redis/DB row) for that key:
  - **In-flight**: another call with the same key is already running ->
    wait on it / return its eventual result rather than issuing a second
    call.
  - **Completed**: return the cached result (with a short TTL, e.g. a few
    minutes) instead of calling again.
  - **Not present**: acquire a lock (e.g. `SETNX` in Redis) for that key,
    call the API, store the result, release the lock.
- This also protects against the common causes of the duplicate-call bug
  specifically: client-side retries on timeout, the LLM being re-invoked
  and re-deciding "call the tool" for context it already has, and
  double-submits from the UI.
- If the downstream order API itself supports an `Idempotency-Key` header
  (many payment/order APIs do), pass the same key through so duplication is
  prevented on their side too, not just ours.

## 4. Reducing the chance the LLM uses irrelevant retrieved context

- **Score-threshold filtering** (already in Task 1): drop any retrieved
  document below a calibrated similarity cutoff before it ever reaches the
  prompt, rather than always forwarding top-k.
- **Reranking**: retrieve a slightly larger candidate set (e.g. top 5-10)
  with the cheap vector search, then rerank with a stronger but slower
  signal (cross-encoder, or an LLM relevance-judgment call) and keep only
  the top 1-2 — this catches cases where the vector search's top-3 contains
  two off-topic documents that happen to share vocabulary.
- **Cite-and-check prompting**: instruct the model to quote/reference which
  specific document it used, making it easy to detect (in logs or a
  post-hoc check) when the cited document doesn't actually support the
  claim.
- **Per-document scores in the prompt**: include the similarity score next
  to each snippet so the model has a signal to prefer the top match over
  weaker ones, instead of treating all provided context as equally
  authoritative.

## 5. Handling a slow/unreliable order API

- **Timeout**: set an aggressive client-side timeout (e.g. 3-4s) rather
  than waiting the full 8-10s — a support answer that says "still checking,
  I'll follow up" beats a request that hangs.
- **Retries**: retry only on clearly transient failures (timeout,
  connection reset, 5xx) with exponential backoff and a small retry cap
  (e.g. 2 retries, capped total wait ~6-8s) — never retry on 4xx (e.g. order
  not found), since that's not transient and blindly retrying it just adds
  latency.
- **Idempotency during retries**: reuse the same idempotency key across
  retries (section 3) so a retry after a timeout can't result in the order
  API actually executing the call twice server-side, even if the first
  attempt secretly succeeded before the client-side timeout fired.
- **Circuit breaker**: if the API fails repeatedly in a short window, trip
  a circuit breaker so subsequent requests fail fast (skip straight to "I
  can't verify this right now") instead of every user request separately
  paying the full timeout+retry cost while the dependency is down.
- **Fallback response, not fallback data**: on failure, tell the user
  verification isn't currently possible — never substitute a guessed or
  cached-stale status silently as if it were current truth.
- **Async option**: for a slow-by-design API, consider returning
  immediately with "checking your order, we'll notify you" and completing
  the lookup out-of-band, rather than holding the HTTP request open.

## 6. What to log/monitor in production

- **Per-request trace**: request id, user/session id, latency per stage
  (routing, retrieval, tool call, generation), and total latency.
- **Retrieval quality**: top-k documents returned + their similarity
  scores, and whether the relevance threshold was met — lets you spot
  "everything is below threshold" spikes (KB gap) vs. "high-scoring wrong
  doc" patterns (KB content overlap issue).
- **Tool call outcomes**: success/failure/timeout counts, latency
  distribution, and idempotency cache hit rate (a rising duplicate-call
  rate shows up here directly).
- **Grounding audits**: log the exact verified-context payload alongside
  the final answer so a sample can be periodically reviewed (or
  auto-checked by a second LLM judging "is every claim in this answer
  supported by this context?") to catch hallucinations before users report
  them.
- **Source distribution**: how often each response `source` (kb, tool,
  kb+tool, cannot_verify, tool_error, ...) fires — a rising
  `cannot_verify`/`tool_error` rate is an early warning independent of any
  single user complaint.
- **Alerting thresholds**: alert on tool error-rate, p95 latency, and
  cannot_verify-rate crossing baseline, not just on hard failures.

## 7. Example system instruction

> You are a customer support assistant. Answer only using the information
> provided to you in the "retrieved documents" and "tool results" sections
> of this prompt — never use prior knowledge, assumptions, or general
> knowledge about the company, its products, or orders. If the provided
> documents and tool results do not contain enough information to answer
> confidently, respond that you are unable to verify the information and
> suggest the user rephrase or contact a human agent. Never state an order
> status, refund amount, or policy detail that is not explicitly present in
> the provided context.
