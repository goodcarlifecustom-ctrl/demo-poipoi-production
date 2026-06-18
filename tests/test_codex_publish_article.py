import argparse
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


@contextlib.contextmanager
def chdir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import codex_publish_article as codex
from scripts import publish_to_wordpress as wp


class CodexPublishArticleTests(unittest.TestCase):
    def make_article(self, root: Path, slug: str = "example") -> Path:
        article_dir = root / "articles"
        article_dir.mkdir(exist_ok=True)
        path = article_dir / f"{slug}.html"
        path.write_text("<h2>Example</h2><p>Body</p>", encoding="utf-8")
        return path

    def test_normal_html_can_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
            article = self.make_article(Path(tmp))
            codex.dry_run(article)

    def test_missing_target_html_fails(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
            with self.assertRaisesRegex(codex.UserFacingError, "does not exist"):
                codex.article_path_from_arg("missing")

    def test_base_url_strips_newlines_and_spaces(self):
        env = {"WP_BASE_URL": " https://example.com/\n", "WP_USERNAME": "user", "WP_APP_PASSWORD": "secret"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(codex.required_env()["WP_BASE_URL"], "https://example.com")

    def test_http_url_is_rejected(self):
        env = {"WP_BASE_URL": "http://example.com", "WP_USERNAME": "user", "WP_APP_PASSWORD": "secret"}
        with patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(ValueError, "https://"):
            codex.required_env()

    def test_missing_env_names_without_secret_values(self):
        with patch.dict(os.environ, {"WP_APP_PASSWORD": "do-not-print"}, clear=True), self.assertRaises(codex.UserFacingError) as raised:
            codex.required_env()
        message = str(raised.exception)
        self.assertIn("WP_BASE_URL", message)
        self.assertIn("WP_USERNAME", message)
        self.assertNotIn("do-not-print", message)

    def test_send_always_uses_draft_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            article = self.make_article(Path(tmp))
            with patch.object(codex, "publish", return_value=wp.PublishResult("example", 1, "created", "draft")) as publish:
                codex.send(article, {"WP_BASE_URL": "https://example.com", "WP_USERNAME": "user", "WP_APP_PASSWORD": "secret"})
        args = publish.call_args.args[1]
        self.assertEqual(args.status, "draft")
        self.assertEqual(args.new_post_status, "draft")

    def test_same_slug_draft_is_updated(self):
        with tempfile.TemporaryDirectory() as tmp:
            article = self.make_article(Path(tmp), "same-slug")
            args = argparse.Namespace(new_post_status="draft", status="draft", dry_run=False, refuse_published_update=True, base_url="https://example.com")
            with patch.object(wp, "find_existing", return_value={"id": 9, "status": "draft"}), patch.object(wp, "request_json", return_value={"id": 9, "status": "draft"}) as request_json:
                result = wp.publish(article, args, "Basic token")
        self.assertEqual(result.action, "updated")
        self.assertIn("/posts/9", request_json.call_args.args[0])

    def test_published_post_is_not_updated(self):
        with tempfile.TemporaryDirectory() as tmp:
            article = self.make_article(Path(tmp), "published")
            args = argparse.Namespace(new_post_status="draft", status="draft", dry_run=False, refuse_published_update=True, base_url="https://example.com")
            with patch.object(wp, "find_existing", return_value={"id": 4, "status": "publish"}), self.assertRaises(wp.PublishedPostRefused):
                wp.publish(article, args, "Basic token")

    def test_research_file_is_not_sendable(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
            research = Path("research")
            research.mkdir()
            (research / "example-sources.md").write_text("source", encoding="utf-8")
            with self.assertRaisesRegex(codex.UserFacingError, "Only articles"):
                codex.article_path_from_arg("research/example-sources.md")

    def test_logs_hide_application_password_and_authorization(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
            article = self.make_article(Path(tmp), "secret-test")
            env = {"WP_BASE_URL": "https://example.com", "WP_USERNAME": "user", "WP_APP_PASSWORD": "app-password-secret"}
            with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["codex_publish_article.py", "secret-test"]), patch.object(codex, "send", return_value=wp.PublishResult("secret-test", 7, "created", "draft")):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(codex.main(), 0)
        text = output.getvalue()
        self.assertNotIn("app-password-secret", text)
        self.assertNotIn("Authorization", text)
        self.assertNotIn("Basic", text)

    def test_workflow_has_no_pull_request_target(self):
        workflow = Path(".github/workflows/publish-to-wordpress.yml").read_text(encoding="utf-8")
        self.assertNotIn("pull_request_target", workflow)

    def test_agents_contains_direct_no_pr_rule(self):
        agents = Path("AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Do not create a pull request", agents)
        self.assertIn("direct WordPress", agents)


if __name__ == "__main__":
    unittest.main()
