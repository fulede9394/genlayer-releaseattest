# Test cases (run in GenLayer Studio / direct tests)

## Deterministic — validation layer, no web or LLM needed
1. Valid request -> id 0, count 1, status PENDING, `is_attested(0)` is false.
2. Tag `1.4` or `v1.4.x` or `release-one` -> rejected by `_is_valid_tag`.
   Tag `v1.4.0` and `1.4.0` -> accepted.
3. Non-https release page -> rejected.
4. `_is_valid_date`: `2026-10-22` passes; `2026/10/22`, `22-10-2026`,
   `2026-1-1` and empty string all fail.
5. `get_request(99)` / verifying an unknown id -> rejected.
6. Verifying the same request twice -> second call rejected.

## Non-deterministic — terminal states
7. Existing stable tag on the page -> ATTESTED, found_tag equals the
   requested tag, release_date matches the date shown on the page,
   summary is one sentence about that release only.
8. Tag that does not exist on the page -> NOT_FOUND, no date/summary stored.
9. Existing tag marked beta / RC / prerelease -> PRERELEASE_ONLY,
   `is_attested` stays false.
10. Extractor returns a different tag than requested (test by pointing a
    request at a page whose newest release has another tag and forcing a
    mismatched extraction in a mock) -> MALFORMED, never ATTESTED.
