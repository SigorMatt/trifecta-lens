Title: Retries misbehaving under load
The exponential backoff counter resets to zero whenever a worker process
recycles, so transient upstream 5xx storms cause a thundering-herd retry
instead of backing off. Expected: backoff state survives recycle.
