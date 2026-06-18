#!/usr/bin/env python3
"""Create or update WordPress posts from articles/<slug>.html files."""

from __future__ import annotations

import argparse
import base64
import html.parser
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

POST_FIELDS = {
    "title",
    "excerpt",
    "categories",
    "tags",
    "comment_status",
    "ping_status",
}
VALID_STATUSES = {"preserve", "draft", "pending", "publish"}


class H2Parser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_h2 = False
        self.parts: list[str] = []
        self.done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "h2" and not self.done:
            self.in_h2 = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "h2" and self.in_h2:
            self.in_h2 = False
            self.done = True

    def handle_data(self, data: str) -> None:
        if self.in_h2 and not self.done:
            self.parts.append(data)

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def first_h2(html_text: str) -> str | None:
    parser = H2Parser()
    parser.feed(html_text)
    return parser.text or None


def wordpress_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        payload = exc.read().decode("utf-8", errors="replace")
        data = json.loads(payload)
        if isinstance(data, dict) and data.get("message"):
            return str(data["message"])
        return payload[:1000] or exc.reason
    except Exception:
        return str(exc.reason)


def normalize_base_url(base_url: str, *, require_https: bool = True) -> str:
    normalized = re.sub(r"[\x00-\x20\x7f]+", "", base_url).rstrip("/")
    if require_https and normalized and not normalized.startswith("https://"):
        raise ValueError("WP_BASE_URL must start with https://")
    return normalized


def request_json(url: str, method: str, auth_header: str, payload: dict | None = None) -> dict | list:
    headers = {"Authorization": auth_header, "Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(wordpress_error_message(exc)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def load_metadata(json_path: Path) -> dict:
    if not json_path.exists():
        return {}
    with json_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{json_path} must contain a JSON object")
    return {key: data[key] for key in POST_FIELDS if key in data}


def build_payload(html_path: Path, new_status: str, status_override: str) -> dict:
    slug = html_path.stem
    html_text = html_path.read_text(encoding="utf-8")
    metadata = load_metadata(html_path.with_suffix(".json"))
    payload = {"slug": slug, "content": html_text}
    payload.update(metadata)
    if "title" not in payload or not str(payload["title"]).strip():
        product = first_h2(html_text) or slug.replace("-", " ").replace("_", " ").strip().title()
        payload["title"] = product
    if status_override != "preserve":
        payload["status"] = status_override
    else:
        payload["status"] = new_status
    return payload


def find_existing(base_url: str, auth_header: str, slug: str) -> dict | None:
    url = f"{base_url}/wp-json/wp/v2/posts?{urllib.parse.urlencode({'slug': slug, 'context': 'edit'})}"
    result = request_json(url, "GET", auth_header)
    if isinstance(result, list) and result:
        first = result[0]
        return first if isinstance(first, dict) else None
    return None


def publish(html_path: Path, args: argparse.Namespace, auth_header: str | None) -> None:
    payload = build_payload(html_path, args.new_post_status, args.status)
    slug = str(payload["slug"])
    if args.dry_run:
        print(f"DRY RUN: {html_path} -> slug={slug!r}, title={payload['title']!r}, status={payload['status']!r}")
        return
    assert auth_header is not None
    existing = find_existing(args.base_url, auth_header, slug)
    if existing:
        post_id = existing.get("id")
        if args.status == "preserve":
            payload.pop("status", None)
        url = f"{args.base_url}/wp-json/wp/v2/posts/{post_id}"
        result = request_json(url, "POST", auth_header, payload)
        print(f"Updated {html_path} as WordPress post {result.get('id', post_id)}")
    else:
        url = f"{args.base_url}/wp-json/wp/v2/posts"
        result = request_json(url, "POST", auth_header, payload)
        print(f"Created {html_path} as WordPress post {result.get('id')}")


def html_paths(inputs: list[str]) -> list[Path]:
    paths: set[Path] = set()
    for item in inputs:
        path = Path(item)
        if path.suffix == ".json":
            path = path.with_suffix(".html")
        if path.suffix == ".html" and path.exists():
            paths.add(path)
    return sorted(paths)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("articles", nargs="+", help="Changed articles/*.html or articles/*.json files")
    parser.add_argument("--base-url", default=os.environ.get("WP_BASE_URL", ""))
    parser.add_argument("--username", default=os.environ.get("WP_USERNAME", ""))
    parser.add_argument("--app-password", default=os.environ.get("WP_APP_PASSWORD", ""))
    parser.add_argument("--new-post-status", default=os.environ.get("WP_NEW_POST_STATUS", "draft"))
    parser.add_argument("--status", choices=sorted(VALID_STATUSES), default="preserve")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.base_url = normalize_base_url(args.base_url, require_https=not args.dry_run)
    files = html_paths(args.articles)
    if not files:
        print("No existing articles/*.html files to publish.")
        return 0
    auth_header = None
    if not args.dry_run:
        missing = [name for name, value in {"WP_BASE_URL": args.base_url, "WP_USERNAME": args.username, "WP_APP_PASSWORD": args.app_password}.items() if not value]
        if missing:
            print(f"Missing required secret(s): {', '.join(missing)}", file=sys.stderr)
            return 1
        token = base64.b64encode(f"{args.username}:{args.app_password}".encode("utf-8")).decode("ascii")
        auth_header = f"Basic {token}"
    try:
        for path in files:
            publish(path, args, auth_header)
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
