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
NEW_ARTICLE_SLUG_RE = re.compile(r"^[a-z0-9]+-[a-z0-9]+-impression$")
TITLE_SUFFIX = "のインプレ・使い方を徹底解説"
METADATA_FIELDS = POST_FIELDS | {"slug", "official_product_url"}


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
    return {key: data[key] for key in METADATA_FIELDS if key in data}


def is_new_article_slug(slug: str) -> bool:
    return slug.endswith("-impression")


def validate_new_article_slug(slug: str) -> None:
    if not NEW_ARTICLE_SLUG_RE.fullmatch(slug) or slug.count("-") != 2:
        raise ValueError("New-format article slug must match ^[a-z0-9]+-[a-z0-9]+-impression$ and contain exactly two hyphens")


def slug_from_product_name(product_name: str) -> str:
    """Return the approved 3-word impression slug for known product-name patterns."""
    normalized = product_name.strip()
    examples = {
        "SCHNEIDER 13": "schneider-13-impression",
        "sobat 80": "sobat-80-impression",
        "HONEY TRAP 70S KARUTORA": "honeytrap-70skarutora-impression",
        "Rocket Bait 95 Heavy": "rocketbait-95heavy-impression",
        "PUGACHEV'S COBRA": "pugachevs-cobra-impression",
        "PUGACHEV'S COBRA 60": "pugachevscobra-60-impression",
    }
    if normalized in examples:
        return examples[normalized]
    words = [re.sub(r"[^A-Za-z0-9]", "", part).lower() for part in normalized.split()]
    words = [word for word in words if word]
    if len(words) < 2:
        raise ValueError("商品名から安全に3語スラッグを生成できません。記事生成前に確認してください。")
    first = words[0] if len(words) == 2 else "".join(words[:-1])
    second = words[1] if len(words) == 2 else words[-1]
    slug = f"{first}-{second}-impression"
    if not NEW_ARTICLE_SLUG_RE.fullmatch(slug):
        raise ValueError("生成スラッグが新形式に一致しません。")
    return slug


def html_text_without_href_values(html_text: str) -> str:
    return re.sub(r"\s+href=[\"'][^\"']*[\"']", "", html_text, flags=re.IGNORECASE)


def validate_new_article_metadata_and_html(html_path: Path, html_text: str, metadata: dict) -> None:
    slug = html_path.stem
    json_path = html_path.with_suffix(".json")
    if not json_path.exists():
        raise ValueError(f"New-format article requires metadata JSON: {json_path}")
    if metadata.get("slug") != slug:
        raise ValueError(f"JSON slug must match HTML filename slug: {json_path}")
    title = str(metadata.get("title", ""))
    if not title.endswith(TITLE_SUFFIX) or title == TITLE_SUFFIX or title.endswith("。"):
        raise ValueError(f"JSON title must be '<正式商品名>{TITLE_SUFFIX}' with no trailing punctuation")
    product_name = title[: -len(TITLE_SUFFIX)]
    if re.search(r"<\s*h1\b", html_text, flags=re.IGNORECASE):
        raise ValueError("HTML body must not contain H1 tags")
    official_url = str(metadata.get("official_product_url", ""))
    if not official_url:
        raise ValueError("New-format metadata JSON requires official_product_url for official-link validation")
    expected_anchor = f"「{product_name}」"
    first_p = re.search(r"<p[^>]*>(.*?)</p>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not first_p:
        raise ValueError("Intro first paragraph is missing")
    first_p_html = first_p.group(1).strip()
    anchors = re.findall(r"<a\b([^>]*)>(.*?)</a>", html_text, flags=re.IGNORECASE | re.DOTALL)
    official_anchors = []
    for attrs, body in anchors:
        href_match = re.search(r"href=[\"']([^\"']+)[\"']", attrs, flags=re.IGNORECASE)
        href = href_match.group(1) if href_match else ""
        if href == official_url:
            official_anchors.append((attrs, re.sub(r"<[^>]+>", "", body).strip()))
        elif re.match(r"https?://", href):
            raise ValueError("HTML contains an external link other than the official product URL")
    if len(official_anchors) != 1:
        raise ValueError("HTML must contain exactly one official product URL link")
    attrs, anchor_text = official_anchors[0]
    if anchor_text != expected_anchor:
        raise ValueError("Official product link anchor text must be the quoted official product name")
    if not re.search(r"target=[\"']_blank[\"']", attrs, flags=re.IGNORECASE):
        raise ValueError("Official product link requires target=\"_blank\"")
    if not re.search(r"rel=[\"']noopener noreferrer[\"']", attrs, flags=re.IGNORECASE):
        raise ValueError("Official product link requires rel=\"noopener noreferrer\"")
    if not re.search(rf"<a\b[^>]*href=[\"']{re.escape(official_url)}[\"'][^>]*>{re.escape(expected_anchor)}</a>\s*$", first_p_html, flags=re.IGNORECASE | re.DOTALL):
        raise ValueError("Intro first paragraph must end with the official product-name link")
    visible_text = re.sub(r"<[^>]+>", "", html_text_without_href_values(html_text))
    if re.search(r"https?://", visible_text, flags=re.IGNORECASE):
        raise ValueError("URL strings must not be visible in HTML text")


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
    if is_new_article_slug(slug):
        validate_new_article_slug(slug)
        validate_new_article_metadata_and_html(html_path, html_text, metadata)
    payload = {"slug": slug, "content": html_text}
    payload.update({key: value for key, value in metadata.items() if key in POST_FIELDS or key == "slug"})
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
