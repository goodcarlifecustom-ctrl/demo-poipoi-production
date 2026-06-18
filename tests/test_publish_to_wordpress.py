import unittest
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


if __name__ == "__main__":
    unittest.main()
