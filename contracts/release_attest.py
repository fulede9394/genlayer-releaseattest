# { "Depends": "py-genlayer:test" }
from genlayer import *
import typing


class ReleaseAttest(gl.Contract):
    """
    ReleaseAttest - a software release attestation primitive.

    Problem: upgrades, bounty payouts and integration switches often
    depend on "version X.Y.Z has actually shipped". Today that check
    is a person reading a releases page, or a trusted bot signing a
    message. This contract makes it a queryable on-chain record.

    Key design choice: the LLM never decides the outcome.
    It only *extracts* three fields from the release page
    (tag | date | channel). Every decision after that - is the tag
    the one that was requested, is the date well-formed, is this a
    stable release or only a prerelease - is plain deterministic
    code that every validator runs identically. If the extractor
    returns the wrong release, the contract refuses to attest it
    instead of trusting the extraction.
    """

    request_count: u256
    projects: TreeMap[u256, str]
    release_pages: TreeMap[u256, str]
    expected_tags: TreeMap[u256, str]
    statuses: TreeMap[u256, str]
    found_tags: TreeMap[u256, str]
    release_dates: TreeMap[u256, str]
    summaries: TreeMap[u256, str]

    PENDING = "PENDING"
    ATTESTED = "ATTESTED"
    PRERELEASE_ONLY = "PRERELEASE_ONLY"
    NOT_FOUND = "NOT_FOUND"
    MALFORMED = "MALFORMED"

    def __init__(self):
        self.request_count = u256(0)

    # ------------------------------------------------------------------
    # Deterministic helpers (no web, no LLM - same on every validator)
    # ------------------------------------------------------------------
    def _is_valid_tag(self, tag: str) -> bool:
        # Accept "1.4.0" and "v1.4.0". Exactly three numeric parts.
        t = tag[1:] if tag.startswith("v") else tag
        parts = t.split(".")
        if len(parts) != 3:
            return False
        for p in parts:
            if len(p) == 0 or not p.isdigit():
                return False
        return True

    def _is_valid_date(self, date: str) -> bool:
        # Strict YYYY-MM-DD shape check, digits and dashes only.
        if len(date) != 10 or date[4] != "-" or date[7] != "-":
            return False
        digits = date[:4] + date[5:7] + date[8:10]
        return digits.isdigit()

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------
    @gl.public.write
    def request_attestation(
        self, project: str, release_page_url: str, expected_tag: str
    ) -> int:
        project = project.strip()
        release_page_url = release_page_url.strip()
        expected_tag = expected_tag.strip()

        assert len(project) >= 2 and len(project) <= 100, "bad project name"
        assert release_page_url.startswith("https://"), "release page must be https"
        assert len(release_page_url) <= 300, "release page URL too long"
        assert self._is_valid_tag(expected_tag), "tag must look like v1.4.0"

        rid = self.request_count
        self.projects[rid] = project
        self.release_pages[rid] = release_page_url
        self.expected_tags[rid] = expected_tag
        self.statuses[rid] = self.PENDING
        self.found_tags[rid] = ""
        self.release_dates[rid] = ""
        self.summaries[rid] = ""
        self.request_count = rid + u256(1)
        return int(rid)

    @gl.public.write
    def verify_release(self, request_id: int) -> str:
        rid = u256(request_id)
        assert rid in self.statuses, "unknown request"
        assert self.statuses[rid] == self.PENDING, "request already verified"

        # Copy storage into locals: non-deterministic blocks may not
        # touch contract storage, they may only capture local values.
        release_page_url = self.release_pages[rid]
        expected_tag = self.expected_tags[rid]

        # --- Step 1: extraction only, checked with strict equality --
        # The model is asked for a machine-readable line, not an
        # opinion. Validators must reproduce the exact same line.
        def extract_release() -> str:
            page = gl.nondet.web.render(release_page_url, mode="text")
            prompt = f"""Find the release tagged exactly {expected_tag} on
the page below.

If it is not there, reply with exactly: NOT_FOUND
If it is there, reply with exactly one line in this format and
nothing else:
{expected_tag}|YYYY-MM-DD|STABLE
Use PRERELEASE instead of STABLE if the page marks this release
as a pre-release, beta, alpha or release candidate.
The date is the date this release was published on the page.

Page content:
{page[:5000]}"""
            raw = gl.nondet.exec_prompt(prompt).strip()
            if "NOT_FOUND" in raw.upper():
                return "NOT_FOUND"
            return raw.splitlines()[0].strip()

        extracted = gl.eq_principle.strict_eq(extract_release)

        # --- Step 2: the decision is deterministic code --------------
        # Nothing below calls an LLM to "decide". Bad extraction
        # leads to MALFORMED / NOT_FOUND, never to a false attestation.
        if extracted == "NOT_FOUND":
            self.statuses[rid] = self.NOT_FOUND
            return self.NOT_FOUND

        parts = extracted.split("|")
        if len(parts) != 3:
            self.statuses[rid] = self.MALFORMED
            return self.MALFORMED

        found_tag = parts[0].strip()
        found_date = parts[1].strip()
        channel = parts[2].strip().upper()

        if found_tag != expected_tag:
            self.statuses[rid] = self.MALFORMED
            return self.MALFORMED
        if not self._is_valid_date(found_date):
            self.statuses[rid] = self.MALFORMED
            return self.MALFORMED
        if channel not in ("STABLE", "PRERELEASE"):
            self.statuses[rid] = self.MALFORMED
            return self.MALFORMED

        self.found_tags[rid] = found_tag
        self.release_dates[rid] = found_date

        if channel == "PRERELEASE":
            self.statuses[rid] = self.PRERELEASE_ONLY
            return self.PRERELEASE_ONLY

        # --- Step 3: changelog summary, non-comparative check -------
        # Only reached for a real stable release. Validators do not
        # re-summarise here; they check the leader's summary against
        # a stated rule. That is the right tool when re-running the
        # task would produce a differently worded, equally valid text.
        def summarise_release() -> str:
            page = gl.nondet.web.render(release_page_url, mode="text")
            prompt = f"""In one short sentence, summarise what changed
in release {expected_tag} according to the page below. Mention
only changes listed for this release.

Page content:
{page[:5000]}"""
            return gl.nondet.exec_prompt(prompt).strip()[:280]

        summary = gl.eq_principle.prompt_non_comparative(
            summarise_release,
            "The text must be a single sentence, it must describe "
            "only changes actually listed for this exact release, "
            "and it must not invent features, fixes or dates.",
        )
        self.summaries[rid] = summary
        self.statuses[rid] = self.ATTESTED
        return self.ATTESTED

    # ------------------------------------------------------------------
    # View methods
    # ------------------------------------------------------------------
    @gl.public.view
    def get_request(self, request_id: int) -> typing.Any:
        rid = u256(request_id)
        assert rid in self.statuses, "unknown request"
        return {
            "id": request_id,
            "project": self.projects[rid],
            "release_page_url": self.release_pages[rid],
            "expected_tag": self.expected_tags[rid],
            "status": self.statuses[rid],
            "found_tag": self.found_tags[rid],
            "release_date": self.release_dates[rid],
            "summary": self.summaries[rid],
        }

    @gl.public.view
    def is_attested(self, request_id: int) -> bool:
        rid = u256(request_id)
        assert rid in self.statuses, "unknown request"
        return self.statuses[rid] == self.ATTESTED

    @gl.public.view
    def get_request_count(self) -> int:
        return int(self.request_count)
