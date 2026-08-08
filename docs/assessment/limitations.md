# Assessment limitations

- A1-B2 conversational interaction only; no C1/C2 distinction.
- Grammar, reading, and writing are not independently assessed.
- Initial thresholds are engineering values pending human calibration.
- Automated rubric judgments may contain semantic mistakes despite strict JSON.
- ASR errors, noise, and microphone quality can reduce evidence; they must not automatically lower proficiency.
- The four golden cases are synthetic regression fixtures, not validation participants.
- The item bank has AI-assisted review metadata; named human owner approval and two-rater pilot evidence remain necessary before claiming empirical agreement.
- The current in-memory rate limiter is per service process. Put a gateway/distributed limiter in front of a horizontally scaled deployment.
- SQLite is local single-node mode. Use PostgreSQL and secured object storage for deployment.
- Pronunciation integration is a non-blocking contract/adapter until the teammate phoneme worker is connected.

