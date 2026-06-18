#!/usr/bin/env python3
"""Safely send one Codex-created article HTML file to WordPress as a draft."""

from __future__ import annotations

import argparse
import contextlib
import io
import os
from pathlib import Path
import sys

from publish_to_wordpress import (
    PublishedPostRefused,
    normalize_base_url,
    publish,
)


class UserFacingError(RuntimeError):
    pass


def article_path_from_arg(value: str) -> Path:
    raw = Path(value)
    if raw.suffix == "":
        raw = Path("articles") / f"{value}.html"
    if raw.parent != Path("articles") or raw.suffix != ".html" or raw.name in {".html", ""}:
        raise UserFacingError("Only articles/<slug>.html can be sent to WordPress")
    if not raw.exists():
        raise UserFacingError(f"Article HTML does not exist: {raw}")
    return raw


def required_env() -> dict[str, str]:
    values = {
        "WP_BASE_URL": os.environ.get("WP_BASE_URL", ""),
        "WP_USERNAME": os.environ.get("WP_USERNAME", ""),
        "WP_APP_PASSWORD": os.environ.get("WP_APP_PASSWORD", ""),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise UserFacingError("Missing required environment variable(s): " + ", ".join(missing))
    values["WP_BASE_URL"] = normalize_base_url(values["WP_BASE_URL"], require_https=True)
    return values


def dry_run(article: Path) -> None:
    args = argparse.Namespace(
        new_post_status="draft",
        status="draft",
        dry_run=True,
        refuse_published_update=True,
        base_url="https://dry-run.invalid",
    )
    with contextlib.redirect_stdout(io.StringIO()):
        publish(article, args, None)


def send(article: Path, env_values: dict[str, str]):
    args = argparse.Namespace(
        new_post_status="draft",
        status="draft",
        dry_run=False,
        refuse_published_update=True,
        base_url=env_values["WP_BASE_URL"],
    )
    import base64

    token = base64.b64encode(f"{env_values['WP_USERNAME']}:{env_values['WP_APP_PASSWORD']}".encode("utf-8")).decode("ascii")
    auth_header = f"Basic {token}"
    with contextlib.redirect_stdout(io.StringIO()):
        return publish(article, args, auth_header)


def post_url(base_url: str, slug: str) -> str:
    return f"{base_url.rstrip('/')}/{slug}/"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("article", help="Article slug or articles/<slug>.html")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        article = article_path_from_arg(args.article)
        env_values = required_env()
        dry_run(article)
        result = send(article, env_values)
        if result is None:
            raise UserFacingError("WordPress send did not return a result")
        if result.status != "draft":
            raise UserFacingError("WordPress response status was not draft")
        print("WORDPRESS_SEND=success")
        print(f"ACTION={result.action}")
        print(f"POST_ID={result.post_id}")
        print(f"SLUG={result.slug}")
        print("STATUS=draft")
        print(f"POST_URL={post_url(env_values['WP_BASE_URL'], result.slug)}")
        return 0
    except PublishedPostRefused:
        print("Published WordPress post already exists; automatic Codex updates are stopped.", file=sys.stderr)
        return 1
    except UserFacingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"WordPress API error: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
