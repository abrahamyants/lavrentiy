"""Offline reviewer-access contract tests (no Firebase credentials needed)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "wim", "api"))
from reviewer_access import configured_reviewer_emails, reviewer_email_is_allowed


configured = " First@Example.com,second@example.com; third@example.com\n"
assert configured_reviewer_emails(configured) == {
    "first@example.com", "second@example.com", "third@example.com",
}
assert reviewer_email_is_allowed("FIRST@example.com", True, configured)
assert reviewer_email_is_allowed(" second@example.com ", True, configured)
assert not reviewer_email_is_allowed("first@example.com", False, configured)
assert not reviewer_email_is_allowed("first@example.com", None, configured)
assert not reviewer_email_is_allowed("stranger@example.com", True, configured)
assert not reviewer_email_is_allowed("", True, configured)
assert not reviewer_email_is_allowed("first@example.com", True, "")

print("PASSED: reviewer access contract")
