# Security and operations

## Required deployment controls

- Replace both development bearer tokens and keep them server-side.
- Terminate TLS at a trusted reverse proxy; never send tokens or audio over plain public HTTP.
- Use PostgreSQL for multi-instance deployment and a managed backup/restore policy.
- Use S3-compatible private object storage with server-side KMS encryption plus the application Fernet envelope.
- Keep `AUDIO_ENCRYPTION_KEY`, provider keys, database password, and service tokens in a secret manager.
- Run retention cleanup on a schedule and document the chosen consent/retention policy.
- Restrict pronunciation callback access to its dedicated token.
- Put a distributed/API-gateway rate limit in front of multiple service processes; the built-in limiter is process-local.
- Do not log transcripts or audio content. Audit rows store IDs, decisions, versions, and operational metadata only.

## Monitoring

Scrape `/metrics` and alert on evaluator failures, invalid-audio spikes, request latency, completion decline, and unexpected level-distribution shifts. Dashboard metrics include completion count, level distribution, invalid audio, response decisions, total assessment duration, request latency, and evaluator failures.

## Version rollback

Install each immutable item bank as `item_bank_vX.Y.Z.json`. Call the admin activation endpoint, then restart with the matching `ITEM_BANK_VERSION`. Never replace an old bank file in place. Every session stores assessment, item-bank, rubric, and scorer versions, so historical results stay interpretable.

## Data deletion

Encrypted audio is deleted by the retention endpoint/tool after `AUDIO_RETENTION_DAYS`. In a production account-deletion workflow, also delete assessment, response, audit, and pronunciation records by user/assessment according to the application's privacy policy. The MVP does not expose destructive user deletion publicly; add it behind the owning backend's verified account-deletion process.

## Failure isolation

Gemini/OpenAI invalid output is schema-validated and retried once; exhausted
failures return 503 without changing the learner level. Pronunciation failure
produces a separate failed diagnostic and never blocks or changes the
conversational result. The `english-tutor` and `english-level-assessor` LiveKit
workers remain separate runtimes, while both call the same integrated FastAPI
backend. A placement-provider failure therefore cannot change a level, but API
availability must be monitored for both workers.
