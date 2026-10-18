"""Normalize user-provided study sources into text for graph extraction.

The graph extractor intentionally accepts only text. This module is the guarded
boundary for everything else: web pages, uploaded Markdown/text/HTML, and PDFs.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from src.harness.retry import ExternalCallError, call_with_retries

MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 250
MAX_REDIRECTS = 5
FETCH_TIMEOUT_SECONDS = 15.0
USER_AGENT = "AdaptiveLearningAgent/0.1 (+source ingestion)"


class SourceIngestionError(ValueError):
    """A source could not be safely fetched or converted to usable text."""

    def __init__(self, message: str, *, code: str = "invalid_source"):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class IngestedSource:
    text: str
    title: str
    source_type: str
    canonical_uri: str | None = None


class _ReadableHTMLParser(HTMLParser):
    """Small dependency-free readable-text extractor for article-like HTML."""

    BLOCK_TAGS = {
        "article", "aside", "blockquote", "br", "div", "footer", "h1", "h2", "h3",
        "h4", "h5", "h6", "header", "li", "main", "nav", "p", "pre", "section",
        "table", "td", "th", "tr",
    }
    SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if not self._skip_depth and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if not self._skip_depth and tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        self.parts.append(data)


def _clean_lines(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def html_to_text(html: str) -> tuple[str, str | None]:
    parser = _ReadableHTMLParser()
    parser.feed(html)
    text = _clean_lines("".join(parser.parts))
    title = " ".join("".join(parser.title_parts).split()) or None
    return text, title


def _ensure_useful_text(text: str) -> str:
    text = text.replace("\x00", "").strip()
    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise SourceIngestionError(
            f"The extracted text exceeds the {MAX_SOURCE_BYTES // (1024 * 1024)} MB limit.",
            code="source_too_large",
        )
    if len(text) < 40:
        raise SourceIngestionError(
            "The source did not contain enough readable text to build a learning map.",
            code="empty_source",
        )
    return text


def _is_public_address(address: str) -> bool:
    try:
        return ipaddress.ip_address(address.split("%")[0]).is_global
    except ValueError:
        return False


def validate_public_url(url: str, *, resolver=socket.getaddrinfo) -> str:
    """Validate an HTTP(S) URL and reject hosts resolving to non-public IPs."""
    raw = url.strip()
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise SourceIngestionError("Only http:// and https:// URLs are supported.", code="bad_url")
    if not parsed.hostname or parsed.username or parsed.password:
        raise SourceIngestionError(
            "The URL must have a hostname and cannot include credentials.", code="bad_url"
        )
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise SourceIngestionError("Local and private network URLs are not allowed.", code="unsafe_url")

    try:
        literal = ipaddress.ip_address(host.split("%")[0])
        addresses = {str(literal)}
    except ValueError:
        try:
            addresses = {info[4][0] for info in resolver(host, parsed.port or 443)}
        except (OSError, socket.gaierror) as exc:
            raise SourceIngestionError(
                f"Could not resolve the URL hostname: {host}", code="unreachable_url"
            ) from exc
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise SourceIngestionError("Local and private network URLs are not allowed.", code="unsafe_url")

    # Fragments never affect fetched content; remove them for stable cache hashes.
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))


def _read_limited_response(response: httpx.Response) -> bytes:
    declared = response.headers.get("content-length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError:
            declared_size = 0
        if declared_size > MAX_SOURCE_BYTES:
            raise SourceIngestionError(
                f"The source exceeds the {MAX_SOURCE_BYTES // (1024 * 1024)} MB limit.",
                code="source_too_large",
            )
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > MAX_SOURCE_BYTES:
            raise SourceIngestionError(
                f"The source exceeds the {MAX_SOURCE_BYTES // (1024 * 1024)} MB limit.",
                code="source_too_large",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def parse_source_bytes(
    data: bytes,
    *,
    filename: str = "source.txt",
    content_type: str | None = None,
    canonical_uri: str | None = None,
) -> IngestedSource:
    """Convert supported source bytes into normalized, non-empty text."""
    if len(data) > MAX_SOURCE_BYTES:
        raise SourceIngestionError(
            f"The source exceeds the {MAX_SOURCE_BYTES // (1024 * 1024)} MB limit.",
            code="source_too_large",
        )
    suffix = Path(filename).suffix.lower()
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    fallback_title = Path(filename).stem.replace("_", " ").replace("-", " ").strip() or "Source"

    if mime == "application/pdf" or suffix == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(data))
            if len(reader.pages) > MAX_PDF_PAGES:
                raise SourceIngestionError(
                    f"PDFs are limited to {MAX_PDF_PAGES} pages.", code="source_too_large"
                )
            pages = [(page.extract_text() or "").strip() for page in reader.pages]
            text = "\n\n".join(f"## Page {i}\n{page}" for i, page in enumerate(pages, 1) if page)
            metadata_title = getattr(reader.metadata, "title", None) if reader.metadata else None
        except SourceIngestionError:
            raise
        except Exception as exc:
            raise SourceIngestionError("The PDF could not be read.", code="invalid_pdf") from exc
        return IngestedSource(
            text=_ensure_useful_text(text),
            title=(metadata_title or fallback_title).strip(),
            source_type="pdf",
            canonical_uri=canonical_uri,
        )

    if mime in {"text/html", "application/xhtml+xml"} or suffix in {".html", ".htm"}:
        html = data.decode("utf-8", errors="replace")
        text, html_title = html_to_text(html)
        return IngestedSource(
            text=_ensure_useful_text(text),
            title=html_title or fallback_title,
            source_type="html",
            canonical_uri=canonical_uri,
        )

    textual_mimes = {
        "", "text/plain", "text/markdown", "text/x-markdown", "application/octet-stream"
    }
    if mime in textual_mimes and suffix in {"", ".txt", ".md", ".markdown"}:
        text = data.decode("utf-8-sig", errors="replace")
        return IngestedSource(
            text=_ensure_useful_text(text),
            title=fallback_title,
            source_type="markdown" if suffix in {".md", ".markdown"} else "text",
            canonical_uri=canonical_uri,
        )

    raise SourceIngestionError(
        "Unsupported source type. Use a web page, PDF, Markdown, HTML, or plain-text file.",
        code="unsupported_source_type",
    )


def fetch_url(
    url: str,
    *,
    client: httpx.Client | None = None,
    resolver=socket.getaddrinfo,
) -> IngestedSource:
    """Fetch a public URL with manual, revalidated redirects and bounded reads."""
    current = validate_public_url(url, resolver=resolver)
    owns_client = client is None
    client = client or httpx.Client(
        timeout=FETCH_TIMEOUT_SECONDS,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,application/pdf"},
    )
    try:
        for _ in range(MAX_REDIRECTS + 1):
            def request_once() -> httpx.Response:
                request = client.build_request("GET", current)
                response = client.send(request, stream=True)
                if response.status_code >= 400:
                    response.read()
                    response.raise_for_status()
                return response

            try:
                response = call_with_retries(request_once, label="fetch_source_url")
            except ExternalCallError as exc:
                if isinstance(exc.cause, httpx.HTTPStatusError):
                    status = exc.cause.response.status_code
                    if status in {401, 403}:
                        message = (
                            f"The website refused automated access (HTTP {status}). "
                            "Try another public page, download it and upload the file, or paste its text."
                        )
                    elif status == 404:
                        message = "The source URL was not found (HTTP 404)."
                    else:
                        message = f"The source URL returned HTTP {status}."
                    raise SourceIngestionError(message, code="source_fetch_failed") from exc
                raise SourceIngestionError(
                    "The source URL could not be reached after retrying.",
                    code="source_fetch_failed",
                ) from exc
            try:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise SourceIngestionError("The URL returned an invalid redirect.", code="bad_redirect")
                    current = validate_public_url(urljoin(current, location), resolver=resolver)
                    continue
                data = _read_limited_response(response)
                content_type = response.headers.get("content-type", "")
            finally:
                response.close()

            path_name = Path(urlsplit(current).path).name or "web-page.html"
            if not Path(path_name).suffix and "html" in content_type:
                path_name += ".html"
            source = parse_source_bytes(
                data, filename=path_name, content_type=content_type, canonical_uri=current
            )
            if source.title in {"web page", "web page html"}:
                return IngestedSource(
                    text=source.text,
                    title=urlsplit(current).hostname or "Web page",
                    source_type=source.source_type,
                    canonical_uri=current,
                )
            return source
        raise SourceIngestionError(
            f"The URL redirected more than {MAX_REDIRECTS} times.", code="too_many_redirects"
        )
    finally:
        if owns_client:
            client.close()
