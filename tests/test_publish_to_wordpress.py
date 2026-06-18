import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import publish_to_wordpress as wp


class BaseUrlNormalizationTests(unittest.TestCase):
    def test_removes_control_and_space_characters_before_building_api_url(self):
        base_url = wp.normalize_base_url("https://example.com/\n/")

        with patch.object(wp, "request_json", return_value=[]) as request_json:
            wp.find_existing(base_url, "Basic token", "example-slug")

        url = request_json.call_args.args[0]
        self.assertEqual(base_url, "https://example.com")
        self.assertTrue(url.startswith("https://example.com/wp-json/wp/v2/posts?"))
        self.assertFalse(url.startswith("https://example.com//wp-json/wp/v2"))

    def test_keeps_https_validation(self):
        with self.assertRaisesRegex(ValueError, "https://"):
            wp.normalize_base_url("http://example.com")


class PullRequestSelectionTests(unittest.TestCase):
    def test_same_repository_pr_new_html_is_detected(self):
        event = {"pull_request": {"head": {"repo": {"full_name": "o/r"}}, "base": {"repo": {"full_name": "o/r"}}}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "articles").mkdir()
            (root / "articles" / "new.html").write_text("<h2>New</h2>", encoding="utf-8")
            self.assertTrue(wp.is_same_repo_pull_request(event))
            self.assertEqual(wp.select_pr_article_targets([{"filename": "articles/new.html", "status": "added"}], root), [root / "articles" / "new.html"])

    def test_json_only_change_detects_corresponding_html_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "articles").mkdir()
            (root / "articles" / "post.html").write_text("<h2>Post</h2>", encoding="utf-8")
            self.assertEqual(wp.select_pr_article_targets([{"filename": "articles/post.json", "status": "modified"}], root), [root / "articles" / "post.html"])

    def test_fork_pr_is_rejected_by_repository_check(self):
        event = {"pull_request": {"head": {"repo": {"full_name": "fork/r"}}, "base": {"repo": {"full_name": "o/r"}}}}
        self.assertFalse(wp.is_same_repo_pull_request(event))

    def test_disallowed_file_rejects_pr(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "outside allowed paths"):
                wp.select_pr_article_targets([{"filename": "scripts/publish_to_wordpress.py", "status": "modified"}], Path(tmp))


class PublishingSafetyTests(unittest.TestCase):
    def test_pr_event_status_can_be_forced_to_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            article_dir = Path(tmp) / "articles"
            article_dir.mkdir()
            html = article_dir / "slug.html"
            html.write_text("<h2>Title</h2>", encoding="utf-8")
            payload = wp.build_payload(html, "draft", "draft")
            self.assertEqual(payload["status"], "draft")

    def test_published_wordpress_post_update_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            article_dir = Path(tmp) / "articles"
            article_dir.mkdir()
            html = article_dir / "slug.html"
            html.write_text("<h2>Title</h2>", encoding="utf-8")
            args = argparse.Namespace(new_post_status="draft", status="draft", dry_run=False, refuse_published_update=True, base_url="https://example.com")
            with patch.object(wp, "find_existing", return_value={"id": 10, "status": "publish"}), self.assertRaisesRegex(wp.PublishedPostRefused, "公開済み記事"):
                wp.publish(html, args, "Basic token")

    def test_secrets_are_not_printed_to_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            article_dir = Path(tmp) / "articles"
            article_dir.mkdir()
            html = article_dir / "slug.html"
            html.write_text("<h2>Title</h2>", encoding="utf-8")
            args = argparse.Namespace(new_post_status="draft", status="draft", dry_run=False, refuse_published_update=False, base_url="https://example.com")
            with patch.object(wp, "find_existing", return_value=None), patch.object(wp, "request_json", return_value={"id": 1, "status": "draft"}):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    wp.publish(html, args, "Basic super-secret-token")
            self.assertNotIn("super-secret-token", output.getvalue())
            self.assertNotIn("Basic", output.getvalue())

    def test_preserve_status_for_existing_main_push_still_omits_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            article_dir = Path(tmp) / "articles"
            article_dir.mkdir()
            html = article_dir / "slug.html"
            html.write_text("<h2>Title</h2>", encoding="utf-8")
            args = argparse.Namespace(new_post_status="draft", status="preserve", dry_run=False, refuse_published_update=False, base_url="https://example.com")
            with patch.object(wp, "find_existing", return_value={"id": 10, "status": "pending"}), patch.object(wp, "request_json", return_value={"id": 10, "status": "pending"}) as request_json:
                wp.publish(html, args, "Basic token")
            payload = request_json.call_args.args[3]
            self.assertNotIn("status", payload)


if __name__ == "__main__":
    unittest.main()
