from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import nh3

from app.smtp.parser import parse_email


class TestParseEmail:
    def test_simple_text_email(self):
        msg = MIMEText("Hello, world!", "plain")
        msg["Subject"] = "Test Subject"
        msg["From"] = "sender@example.com"
        msg["To"] = "user@tempinbox.dev"

        result = parse_email(msg.as_bytes(), "sender@example.com", "user@tempinbox.dev")

        assert result.sender == "sender@example.com"
        assert result.recipient == "user@tempinbox.dev"
        assert result.subject == "Test Subject"
        assert result.body_text == "Hello, world!"
        assert result.body_html is None
        assert result.domain == "tempinbox.dev"
        assert result.size_bytes > 0

    def test_multipart_email(self):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Multipart Test"
        msg["From"] = "sender@example.com"
        msg["To"] = "user@tempinbox.dev"
        msg.attach(MIMEText("Plain text body", "plain"))
        msg.attach(MIMEText("<h1>HTML body</h1>", "html"))

        result = parse_email(msg.as_bytes(), "sender@example.com", "user@tempinbox.dev")

        assert result.body_text == "Plain text body"
        assert result.body_html == nh3.clean("<h1>HTML body</h1>")

    def test_email_with_attachment(self):
        msg = MIMEMultipart("mixed")
        msg["Subject"] = "With Attachment"
        msg.attach(MIMEText("Body text", "plain"))

        attachment = MIMEText("file content", "plain")
        attachment.add_header("Content-Disposition", "attachment", filename="test.txt")
        msg.attach(attachment)

        result = parse_email(msg.as_bytes(), "sender@example.com", "user@tempinbox.dev")

        assert result.body_text == "Body text"
        # Attachment should be ignored
        assert "file content" not in (result.body_text or "")

    def test_empty_body(self):
        msg = MIMEText("", "plain")
        msg["Subject"] = "Empty"

        result = parse_email(msg.as_bytes(), "sender@example.com", "user@tempinbox.dev")

        assert result.body_text == ""
        assert result.subject == "Empty"

    def test_no_subject(self):
        msg = MIMEText("body", "plain")

        result = parse_email(msg.as_bytes(), "sender@example.com", "user@tempinbox.dev")

        assert result.subject is None

    def test_headers_extracted(self):
        msg = MIMEText("body", "plain")
        msg["Subject"] = "Test"
        msg["X-Custom-Header"] = "custom-value"

        result = parse_email(msg.as_bytes(), "sender@example.com", "user@tempinbox.dev")

        assert "X-Custom-Header" in result.raw_headers
        assert result.raw_headers["X-Custom-Header"] == ["custom-value"]

    def test_html_sanitization(self):
        html = '<p>Hello</p><script>alert("xss")</script><img src=x onerror=alert(1)>'
        msg = MIMEText(html, "html")
        msg["Subject"] = "XSS test"

        result = parse_email(msg.as_bytes(), "sender@example.com", "user@tempinbox.dev")

        assert "<script>" not in (result.body_html or "")
        assert "onerror" not in (result.body_html or "")
        assert "<p>Hello</p>" in (result.body_html or "")

    def test_utf8_encoding(self):
        msg = MIMEText("Привет, мир!", "plain", "utf-8")
        msg["Subject"] = "Тест кодировки"

        result = parse_email(msg.as_bytes(), "sender@example.com", "user@tempinbox.dev")

        assert "Привет" in (result.body_text or "")
