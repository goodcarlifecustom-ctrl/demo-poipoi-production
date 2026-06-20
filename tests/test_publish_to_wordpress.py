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

        first_url = request_json.call_args_list[0].args[0]
        self.assertEqual(base_url, "https://example.com")
        self.assertTrue(first_url.startswith("https://example.com/wp-json/wp/v2/posts?"))
        self.assertFalse(first_url.startswith("https://example.com//wp-json/wp/v2"))
        self.assertEqual(request_json.call_count, len(wp.WP_SEARCH_STATUSES))
        for call, status in zip(request_json.call_args_list, wp.WP_SEARCH_STATUSES):
            url = call.args[0]
            query = wp.urllib.parse.parse_qs(wp.urllib.parse.urlparse(url).query)
            self.assertEqual(query["slug"], ["example-slug"])
            self.assertEqual(query["context"], ["edit"])
            self.assertEqual(query["status"], [status])

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

    def write_legacy_article(self, root: Path, slug: str = "slug") -> Path:
        article_dir = root / "articles"
        article_dir.mkdir()
        html = article_dir / f"{slug}.html"
        html.write_text("<h2>Title</h2>", encoding="utf-8")
        return html

    def publish_args(self, status: str = "draft", refuse_published_update: bool = True) -> argparse.Namespace:
        return argparse.Namespace(new_post_status="draft", status=status, dry_run=False, refuse_published_update=refuse_published_update, base_url="https://example.com")

    def search_results(self, *, draft=None, pending=None, private=None, future=None, publish=None):
        by_status = {
            "draft": draft or [],
            "pending": pending or [],
            "private": private or [],
            "future": future or [],
            "publish": publish or [],
        }
        return [by_status[status] for status in wp.WP_SEARCH_STATUSES]

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

    def test_existing_draft_is_updated_with_same_post_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_legacy_article(Path(tmp))
            side_effect = self.search_results(draft=[{"id": 10, "status": "draft"}]) + [{"id": 10, "status": "draft"}]
            with patch.object(wp, "request_json", side_effect=side_effect) as request_json:
                result = wp.publish(html, self.publish_args(), "Basic token")
        self.assertEqual(result.action, "updated")
        self.assertEqual(result.post_id, 10)
        self.assertIn("/wp-json/wp/v2/posts/10", request_json.call_args_list[-1].args[0])

    def test_existing_pending_is_detected_and_updated(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_legacy_article(Path(tmp))
            side_effect = self.search_results(pending=[{"id": 11, "status": "pending"}]) + [{"id": 11, "status": "draft"}]
            with patch.object(wp, "request_json", side_effect=side_effect) as request_json:
                result = wp.publish(html, self.publish_args(), "Basic token")
        self.assertEqual(result.action, "updated")
        self.assertEqual(result.post_id, 11)
        self.assertIn("/wp-json/wp/v2/posts/11", request_json.call_args_list[-1].args[0])

    def test_duplicate_slug_posts_stop_without_create_or_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_legacy_article(Path(tmp))
            side_effect = self.search_results(draft=[{"id": 10, "status": "draft"}], pending=[{"id": 11, "status": "pending"}])
            with patch.object(wp, "request_json", side_effect=side_effect) as request_json, self.assertRaisesRegex(wp.DuplicateSlugPosts, "10, 11"):
                wp.publish(html, self.publish_args(), "Basic token")
        self.assertEqual(request_json.call_count, len(wp.WP_SEARCH_STATUSES))

    def test_existing_publish_is_detected_and_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_legacy_article(Path(tmp))
            side_effect = self.search_results(publish=[{"id": 13, "status": "publish"}])
            with patch.object(wp, "request_json", side_effect=side_effect) as request_json, self.assertRaisesRegex(wp.PublishedPostRefused, "公開済み記事"):
                wp.publish(html, self.publish_args(), "Basic token")
        self.assertEqual(request_json.call_count, len(wp.WP_SEARCH_STATUSES))

    def test_no_existing_post_creates_new_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_legacy_article(Path(tmp))
            side_effect = self.search_results() + [{"id": 12, "status": "draft"}]
            with patch.object(wp, "request_json", side_effect=side_effect) as request_json:
                result = wp.publish(html, self.publish_args(), "Basic token")
        self.assertEqual(result.action, "created")
        self.assertEqual(result.post_id, 12)
        self.assertEqual(request_json.call_args_list[-1].args[1], "POST")
        self.assertTrue(request_json.call_args_list[-1].args[0].endswith("/wp-json/wp/v2/posts"))

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

class NewArticleRuleTests(unittest.TestCase):
    def write_new_article(self, root: Path, slug: str = "schneider-13-impression", title: str = "SCHNEIDER 13のインプレ・使い方を徹底解説", url: str = "https://example.com/product") -> Path:
        article_dir = root / "articles"
        article_dir.mkdir(exist_ok=True)
        html = article_dir / f"{slug}.html"
        product = title.removesuffix(wp.TITLE_SUFFIX)
        html.write_text(
            f'<p>全長59mm・重量13gのシンキングタイプで、軽い巻き心地が長所の<a href="{url}" target="_blank" rel="noopener noreferrer">「{product}」</a>。レンジ30cmから河川や干潟で使いやすい鉄板バイブレーションです。</p>'
            '<p>「根掛かりには注意が必要」という悪いインプレもあります。本当に初心者でも扱いやすいのでしょうか？</p>'
            f'<h2>{product}とは？基本スペック</h2>',
            encoding="utf-8",
        )
        html.with_suffix(".json").write_text('{"title":"' + title + '","slug":"' + slug + '","official_product_url":"' + url + '"}', encoding="utf-8")
        return html

    def test_slug_generation_examples(self):
        cases = {
            "SCHNEIDER 13": "schneider-13-impression",
            "sobat 80": "sobat-80-impression",
            "HONEY TRAP 70S KARUTORA": "honeytrap-70skarutora-impression",
            "Rocket Bait 95 Heavy": "rocketbait-95heavy-impression",
            "PUGACHEV'S COBRA": "pugachevs-cobra-impression",
        }
        for product, expected in cases.items():
            self.assertEqual(wp.slug_from_product_name(product), expected)
            self.assertRegex(expected, wp.NEW_ARTICLE_SLUG_RE)
            self.assertEqual(expected.count("-"), 2)

    def test_new_article_uses_json_title_and_slug(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_new_article(Path(tmp))
            payload = wp.build_payload(html, "draft", "draft")
        self.assertEqual(payload["title"], "SCHNEIDER 13のインプレ・使い方を徹底解説")
        self.assertEqual(payload["slug"], "schneider-13-impression")

    def test_missing_official_link_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_new_article(Path(tmp))
            html.write_text('<p>全長59mm・重量13gのシンキングタイプで、軽い巻き心地が長所の「SCHNEIDER 13」。レンジ30cmから河川や干潟で使いやすい鉄板バイブレーションです。</p><p>「根掛かりには注意が必要」という悪いインプレもあります。本当に初心者でも扱いやすいのでしょうか？</p>', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "first sentence"):
                wp.build_payload(html, "draft", "draft")

    def test_intro_first_paragraph_bad_impression_question_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_new_article(Path(tmp))
            html.write_text(
                '<p>全長59mm・重量13gのシンキングタイプで、軽い巻き心地が長所の<a href="https://example.com/product" target="_blank" rel="noopener noreferrer">「SCHNEIDER 13」</a>。根掛かりには気をつけてという評判があるルアーです。</p>'
                '<p>「根掛かりには注意が必要」という悪いインプレもあります。本当に初心者でも扱いやすいのでしょうか？</p>',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "prohibited"):
                wp.build_payload(html, "draft", "draft")

    def test_intro_second_paragraph_question_and_no_external_link_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_new_article(Path(tmp))
            html.write_text(
                '<p>全長59mm・重量13gのシンキングタイプで、軽い巻き心地が長所の<a href="https://example.com/product" target="_blank" rel="noopener noreferrer">「SCHNEIDER 13」</a>。レンジ30cmから河川や干潟で使いやすい鉄板バイブレーションです。</p>'
                '<p><a href="https://example.net">「根掛かりには注意が必要」</a>という悪いインプレもあります。本当に初心者でも扱いやすいのでしょうか？</p>',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "must not contain external links"):
                wp.build_payload(html, "draft", "draft")

    def test_different_official_link_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_new_article(Path(tmp))
            html.write_text('<p>全長59mm・重量13gのシンキングタイプで、軽い巻き心地が長所の<a href="https://evil.example" target="_blank" rel="noopener noreferrer">「SCHNEIDER 13」</a>。レンジ30cmから河川や干潟で使いやすい鉄板バイブレーションです。</p><p>「根掛かりには注意が必要」という悪いインプレもあります。本当に初心者でも扱いやすいのでしょうか？</p>', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "other than"):
                wp.build_payload(html, "draft", "draft")

    def test_second_external_link_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_new_article(Path(tmp))
            html.write_text(html.read_text(encoding="utf-8") + '<p><a href="https://example.org">x</a></p>', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "other than"):
                wp.build_payload(html, "draft", "draft")

    def test_visible_url_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_new_article(Path(tmp))
            html.write_text(html.read_text(encoding="utf-8") + '<p>https://example.com/product</p>', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "visible"):
                wp.build_payload(html, "draft", "draft")

    def test_json_title_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_new_article(Path(tmp), title="SCHNEIDER 13の評判")
            with self.assertRaisesRegex(ValueError, "JSON title"):
                wp.build_payload(html, "draft", "draft")

    def test_json_slug_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_new_article(Path(tmp))
            html.with_suffix(".json").write_text('{"title":"SCHNEIDER 13のインプレ・使い方を徹底解説","slug":"wrong-slug-impression","official_product_url":"https://example.com/product"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON slug"):
                wp.build_payload(html, "draft", "draft")

    def test_three_or_more_hyphen_slug_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.write_new_article(Path(tmp), slug="honey-trap-70s-karutora-impression", title="HONEY TRAP 70S KARUTORAのインプレ・使い方を徹底解説")
            with self.assertRaisesRegex(ValueError, "exactly two hyphens"):
                wp.build_payload(html, "draft", "draft")
