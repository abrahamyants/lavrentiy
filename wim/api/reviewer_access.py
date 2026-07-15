"""Small, testable policy for Google Play reviewer access."""

import re


def configured_reviewer_emails(value):
    """Return normalized emails from a comma, semicolon, or newline list."""
    return {
        item.strip().casefold()
        for item in re.split(r"[,;\n]", value or "")
        if item.strip()
    }


def reviewer_email_is_allowed(email, email_verified, configured):
    """Only a verified Firebase email in the explicit allowlist may bypass billing."""
    if not email or email_verified is not True:
        return False
    return email.strip().casefold() in configured_reviewer_emails(configured)
