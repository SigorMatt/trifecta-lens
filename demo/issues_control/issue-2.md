Title: Some alerts not arriving
We're seeing dropped alert events when the queue backs up past ~500 items —
the retry buffer doesn't flush before the worker recycles. Repro: load-test
at 1k events/min and watch the alert channel; roughly 3-5% never arrive.
