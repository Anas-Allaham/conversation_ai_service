# Conversational rubric v0.1

| Dimension | Weight | Evidence |
|---|---:|---|
| Task achievement and relevance | 25% | Required communicative goal and relevant content |
| Interactive communication | 20% | Understanding, direct reaction, follow-up handling, support needed |
| Fluency | 20% | Maintaining meaningful speech, disruptive pauses, false starts, abandoned turns |
| Coherence and discourse | 15% | Connected sequence, explanation, comparison, reasons, qualifications |
| Lexical adequacy | 10% | Enough vocabulary to communicate the target function |
| Intelligibility | 10% | Listener effort and communication repair, not accent removal |

Each dimension is 0-4: 0 no usable evidence; 1 far below target; 2 partial; 3 meets target; 4 clearly exceeds target.

The weighted score is `0.25T + 0.20I + 0.20F + 0.15C + 0.10L + 0.10P`.

Pass requires weighted score at least 2.8, task achievement at least 3, interaction at least 3, intelligibility at least 2, relevant task completion, recoverable meaning, and usable audio. Borderline is 2.4-2.799 or a weighted pass with a slightly missed critical dimension. Failure is below 2.4, irrelevant/unfinished task, or blocked meaning.

Grammar is absent from the score schema. “Yesterday I go to class” is not downgraded merely for tense. If a breakdown prevents the listener from recovering the message, task achievement or intelligibility reflects that consequence.

Words per minute, ASR confidence, and phoneme-error rate are supporting/validity evidence only; none can directly assign a level.

