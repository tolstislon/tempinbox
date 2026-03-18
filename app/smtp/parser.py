"""Parse raw email bytes into a structured ParsedEmail dataclass."""

import email
import email.policy
from dataclasses import dataclass

import nh3


@dataclass(frozen=True)
class ParsedEmail:
    """Immutable representation of a parsed email message."""

    sender: str
    recipient: str
    subject: str | None
    body_text: str | None
    body_html: str | None
    raw_headers: dict[str, list[str]]
    size_bytes: int
    domain: str


MAX_MIME_PARTS = 50


def parse_email(raw_data: bytes, envelope_from: str, envelope_to: str) -> ParsedEmail:
    """Parse raw email bytes and SMTP envelope into a ParsedEmail."""
    msg = email.message_from_bytes(raw_data, policy=email.policy.default)

    subject = msg.get("Subject")

    headers: dict[str, list[str]] = {}
    for key, value in msg.items():
        headers.setdefault(key, []).append(str(value))

    body_text: str | None = None
    body_html: str | None = None

    if msg.is_multipart():
        for i, part in enumerate(msg.walk()):
            if i >= MAX_MIME_PARTS:
                break
            content_type = part.get_content_type()
            disposition = part.get_content_disposition()
            if disposition == "attachment":
                continue
            if content_type == "text/plain" and body_text is None:
                body_text = part.get_content()
            elif content_type == "text/html" and body_html is None:
                body_html = nh3.clean(part.get_content())
    else:
        content_type = msg.get_content_type()
        if content_type == "text/plain":
            body_text = msg.get_content()
        elif content_type == "text/html":
            body_html = nh3.clean(msg.get_content())

    domain = envelope_to.rsplit("@", 1)[-1] if "@" in envelope_to else ""

    return ParsedEmail(
        sender=envelope_from,
        recipient=envelope_to,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        raw_headers=headers,
        size_bytes=len(raw_data),
        domain=domain,
    )
