#!/usr/bin/env python3
"""Create or update WordPress posts from articles/<slug>.html files."""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
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
PR_ALLOWED_FILE_RE = re.compile(r"^(articles/[^/]+\.(?:html|json)|research/[^/]+\.md)$")
PR_ARTICLE_RE = re.compile(r"^articles/([^/]+)\.(html|json)$")
PR_POSTABLE_STATUSES = {"added", "modified", "renamed", "changed"}


@dataclass(frozen=True)
class PublishResult:
    slug: str
    post_id: object
    action: str
    status: str


class PublishedPostRefused(RuntimeError):
    pass


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
        raise RuntimeError(f"HTTP {exc.code}: {wordpress_error_message(exc)}") from exc
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


def validate_html(html_path: Path, html_text: str) -> None:
    if html_path.suffix != ".html" or html_path.parent.name != "articles":
        raise ValueError(f"Only articles/*.html files can be published: {html_path}")
    if not html_text.strip():
        raise ValueError(f"Article HTML is empty: {html_path}")
    if "<" not in html_text or ">" not in html_text:
        raise ValueError(f"Article HTML failed validation: {html_path}")


def build_payload(html_path: Path, new_status: str, status_override: str) -> dict:
    slug = html_path.stem
    html_text = html_path.read_text(encoding="utf-8")
    validate_html(html_path, html_text)
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


def publish(html_path: Path, args: argparse.Namespace, auth_header: str | None) -> PublishResult | None:
    payload = build_payload(html_path, args.new_post_status, args.status)
    slug = str(payload["slug"])
    if args.dry_run:
        print(f"DRY RUN: {html_path} -> slug={slug!r}, title={payload['title']!r}, status={payload['status']!r}")
        return None
    assert auth_header is not None
    existing = find_existing(args.base_url, auth_header, slug)
    if existing:
        post_id = existing.get("id")
        existing_status = str(existing.get("status", ""))
        if args.refuse_published_update and existing_status == "publish":
            raise PublishedPostRefused("公開済み記事はmainマージ後または手動実行で更新してください")
        if args.status == "preserve":
            payload.pop("status", None)
            result_status = existing_status or "preserve"
        else:
            result_status = str(payload["status"])
        url = f"{args.base_url}/wp-json/wp/v2/posts/{post_id}"
        result = request_json(url, "POST", auth_header, payload)
        final_status = str(result.get("status", result_status)) if isinstance(result, dict) else result_status
        final_id = result.get("id", post_id) if isinstance(result, dict) else post_id
        print(f"Updated slug={slug} WordPress post ID={final_id} status={final_status}")
        return PublishResult(slug, final_id, "updated", final_status)
    url = f"{args.base_url}/wp-json/wp/v2/posts"
    result = request_json(url, "POST", auth_header, payload)
    final_id = result.get("id") if isinstance(result, dict) else None
    final_status = str(result.get("status", payload["status"])) if isinstance(result, dict) else str(payload["status"])
    print(f"Created slug={slug} WordPress post ID={final_id} status={final_status}")
    return PublishResult(slug, final_id, "created", final_status)


def html_paths(inputs: list[str]) -> list[Path]:
    paths: set[Path] = set()
    for item in inputs:
        path = Path(item)
        if path.suffix == ".json":
            path = path.with_suffix(".html")
        if path.suffix == ".html" and path.exists():
            paths.add(path)
    return sorted(paths)


def is_same_repo_pull_request(event: dict) -> bool:
    pr = event.get("pull_request") or {}
    head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name")
    base_repo = ((pr.get("base") or {}).get("repo") or {}).get("full_name")
    return bool(head_repo and base_repo and head_repo == base_repo)


def select_pr_article_targets(changed_files: list[dict], candidate_root: Path) -> list[Path]:
    disallowed = [str(item.get("filename", "")) for item in changed_files if not PR_ALLOWED_FILE_RE.fullmatch(str(item.get("filename", "")))]
    if disallowed:
        raise ValueError("PR contains files outside allowed paths: " + ", ".join(disallowed))
    targets: set[Path] = set()
    for item in changed_files:
        filename = str(item.get("filename", ""))
        status = str(item.get("status", ""))
        if status not in PR_POSTABLE_STATUSES:
            continue
        match = PR_ARTICLE_RE.fullmatch(filename)
        if not match:
            continue
        slug, suffix = match.groups()
        html_path = candidate_root / "articles" / f"{slug}.html"
        if suffix == "html" or html_path.exists():
            targets.add(html_path)
    return sorted(targets)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("articles", nargs="+", help="Changed articles/*.html or articles/*.json files")
    parser.add_argument("--base-url", default=os.environ.get("WP_BASE_URL", ""))
    parser.add_argument("--username", default=os.environ.get("WP_USERNAME", ""))
    parser.add_argument("--app-password", default=os.environ.get("WP_APP_PASSWORD", ""))
    parser.add_argument("--new-post-status", default=os.environ.get("WP_NEW_POST_STATUS", "draft"))
    parser.add_argument("--status", choices=sorted(VALID_STATUSES), default="preserve")
    parser.add_argument("--refuse-published-update", action="store_true")
    parser.add_argument("--summary-file", default=os.environ.get("GITHUB_STEP_SUMMARY", ""))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def append_summary(summary_file: str, results: list[PublishResult]) -> None:
    if not summary_file or not results:
        return
    with open(summary_file, "a", encoding="utf-8") as handle:
        handle.write("\n| slug | WordPress post ID | action | status |\n")
        handle.write("| --- | --- | --- | --- |\n")
        for result in results:
            handle.write(f"| {result.slug} | {result.post_id} | {result.action} | {result.status} |\n")


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
        results = []
        for path in files:
            result = publish(path, args, auth_header)
            if result is not None:
                results.append(result)
        append_summary(args.summary_file, results)
    except PublishedPostRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
