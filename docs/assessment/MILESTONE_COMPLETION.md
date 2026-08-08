# Milestone completion record

| Milestone | Delivered | Verification | External gate |
|---|---|---|---|
| 0 - construct/content | Charter, naming, grammar exclusion, provenance, original-content policy | Bank validator rejects non-original active items | Named owner approval recommended |
| 1 - blueprint | Population, purpose, stages, timing, support, validity, rules, confidence, traceability | Version 0.2 documentation plus branching tests | None |
| 2 - item bank | 16 frozen original records, schema, checklist, 32-candidate review log | Version 0.2.0 validates exactly 3 normal + 1 boundary item per level; runtime selects active only | Named human reviewer before formal pilot claim |
| 3 - microservice | FastAPI, Pydantic, SQLite/PostgreSQL repository, OpenAPI, health, Docker, logs/correlation | Full core simulation and API smoke tool | Install runtime dependencies |
| 4 - scoring/branching | Metrics, structured Gemini/OpenAI adapters, code-owned decisions, combined stage evidence, same-level boundary checks, confidence, golden cases | Automated pass/borderline/fail/boundary/invalid/idempotency tests, including reported learner-session regressions | Provider key for production scoring |
| 5 - LiveKit | Separate assessor, idempotent deferred-response recovery, client retries/circuit breaker, fixed prompts, raw track capture; tutor preserved unchanged | Original tutor SHA-256 comparison, 503-recovery regression, and compile checks | End-to-end run with project credentials/devices |
| 6 - pilot/calibration | Manifest, two-rater sheet, analyzer, notebook, report template | Analyzer tested with sample rows | 15-30 real recordings and two human raters; no data fabricated |
| 7 - pronunciation | Separate optional pronunciation contract, pre-enhancement raw recorder, encrypted audio URI, event/result schemas | Removed from placement flow; failure leaves conversational result unchanged | Connect teammate phoneme worker as a separate activity |
| 8 - hardening | Bearer service auth, admin auth, limits, PostgreSQL, encrypted local/S3 storage, retention, audit, dashboards, version rollback, backend/limitations docs | Storage/repository tests, `/metrics`, Docker compose | Production secrets, gateway/TLS, deployment monitoring |

Software implementation is complete for the 0.2.0 MVP. The 43-test suite verifies the software contract; it does not establish CEFR cut-score validity. Two evidence-producing activities cannot be truthfully manufactured in code: human pilot agreement and the teammate phoneme model's real output. Their interfaces, templates, acceptance calculations, and failure isolation are complete and ready to run.
