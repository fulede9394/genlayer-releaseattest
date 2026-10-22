# ReleaseAttest — Software Release Attestation Primitive

A standalone Intelligent Contract that turns "version X.Y.Z has actually
shipped" into an immutable, queryable on-chain record.

## Why this exists

Protocol upgrades, bounty payouts, plugin listings and integration switches
all depend on a release really existing. Today a person reads the releases
page, or a trusted bot signs off. Other builders should not have to rebuild
that trust assumption for every project. With ReleaseAttest:

1. `request_attestation(project, release_page_url, expected_tag)` — the page
   and the exact tag are fixed in the request. They cannot be changed later.
2. `verify_release(request_id)` — anyone may trigger it. The result is stored
   once and can never be re-verified or edited.
3. Other contracts / builders just call `is_attested(request_id)` or
   `get_request(request_id)` instead of trusting a screenshot or a bot.

## The design point: the LLM extracts, the code decides

This contract is deliberately **not** "the AI decides whether it shipped".

- The non-deterministic step only *extracts* a machine-readable line from
  the release page: `tag|YYYY-MM-DD|STABLE` (or `PRERELEASE`, or
  `NOT_FOUND`). It returns no opinion and no free-form verdict.
- That line is checked with `gl.eq_principle.strict_eq` — extraction of the
  same page must be reproducible, so validators must match exactly.
- All decisions after extraction are deterministic helper code that runs
  identically on every validator: tag format (`v1.4.0` shape), date format
  (`YYYY-MM-DD` shape), extracted tag must equal the requested tag, channel
  must be `STABLE` or `PRERELEASE`. Failed checks end in `MALFORMED` or
  `NOT_FOUND`, never in a false attestation.
- Only a genuine stable release reaches the changelog summary step, which
  uses `gl.eq_principle.prompt_non_comparative`: validators do not re-write
  the summary (they would word it differently), they check the leader's
  summary against an explicit rule — one sentence, only changes listed for
  this release, nothing invented.

## State design

One-way state machine per request:
`PENDING -> ATTESTED | PRERELEASE_ONLY | NOT_FOUND | MALFORMED`

`PRERELEASE_ONLY` is a separate terminal state on purpose: a beta existing
is not a stable release shipping, and downstream users need to tell the two
apart without parsing text. Fields are stored in separate
`TreeMap[u256, str]` maps (project, page, expected/found tag, date, status,
summary) so other builders can read exactly the field they need.

## Try it in GenLayer Studio

1. Paste `contracts/release_attest.py` into Studio and deploy (no args).
2. `request_attestation("MyProject", "https://github.com/<owner>/<repo>/releases", "v1.0.0")`
   using a real releases page and a tag that exists on it.
3. `verify_release(0)`, then `get_request(0)` — expect `ATTESTED`, the
   release date from the page, and a one-sentence summary.
4. Repeat with a tag that does not exist yet — expect `NOT_FOUND`, and with
   a beta tag — expect `PRERELEASE_ONLY`.

## Tests

See `tests/test_cases.md`: 10 cases covering tag/date validation in the
deterministic layer, unknown and double verification, and all four
terminal states.
