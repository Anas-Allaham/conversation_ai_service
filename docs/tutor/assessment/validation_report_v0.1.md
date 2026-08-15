# Validation report v0.1 - pre-pilot engineering evidence

## Current evidence

- The frozen bank contains 16 schema-valid original items: three normal and one tie-breaker at each A1-B2 stage.
- Automated tests cover all nine main/follow-up decision combinations, invalid audio, critical-dimension constraints, meaning-blocked failure, grammar exclusion, deterministic form selection, timestamp metrics, low-ASR-confidence policy, idempotent retry, A1 failure, tie-breaker advancement, and A1-B2 ceiling completion.
- Four synthetic golden cases cover obvious A1, A2, B1 grammar-tolerant, and B2 responses.
- A full scripted simulation reaches B2 ceiling without allowing the evaluator to set the final level.
- At the time of the v0.1 validation, the ordinary `voice_agent.py` was preserved
  byte-for-byte and assessment code was isolated. In the merged backend its
  behavior is preserved in `conversation_ai.agent.pipeline` and the redundant
  standalone file has been removed.

## Empirical status

No real participant recordings or two-human-rater scores were supplied. Therefore exact agreement, adjacent-level agreement, bias, stability, and calibration claims are **not yet measured**. The repository intentionally does not invent results.

## Required pilot

Collect 15-30 consented sessions spanning clear beginners, intermediate/strong speakers, fluent but grammatically inaccurate speakers, clear pronunciation with weak interaction, noise, and incomplete speech. Obtain two independent ratings with the same rubric, adjudicate disagreements, fill the templates, and run `tools/analyze_pilot.py`.

Development targets are at least 70% exact agreement, at least 90% within one adjacent level, and no systematic downgrade of communicatively successful grammar-inaccurate cases. These are project targets, not psychometric certification standards.
