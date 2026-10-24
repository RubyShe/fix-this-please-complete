# Filtering (F1-F2)

The sampling frame uses two filters, both applied inline in the analysis scripts;
there are no standalone filter scripts.

- F1 keeps the first session of each task (the session-initiating ask), selected with
  `session_index = 0`, for example in `scripts/06`, `07`, `10`, `11`, and `12`.
- F2 drops empty and auto-template asks, which are the published classifier's `missing`
  and `error` sessions: once platform text is stripped, the prompt carries no
  developer-written content.

F1 then F2 leaves 324,695 labelled asks out of 353,432 first sessions (the Table II
funnel; see the main README).

We do not apply the heavier F3 (playground repositories) and F4 (deduplication) steps
from the original plan; the paper's filtering is F1 and F2 only. Playground repos and
retried duplicate prompts are left in the population rather than removed. See the note on
filtering in the main README.
