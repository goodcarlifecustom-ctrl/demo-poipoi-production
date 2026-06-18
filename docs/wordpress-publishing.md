# WordPress publishing workflow

This repository publishes article files to WordPress with the GitHub Actions workflow in `.github/workflows/publish-to-wordpress.yml` and the Python standard-library script in `scripts/publish_to_wordpress.py`.

## When it runs

- Automatically on pushes to `main` that change `articles/*.html` or `articles/*.json`.
- Manually from **Actions → Publish articles to WordPress → Run workflow**.

The workflow does not delete WordPress posts when article files are removed.

## Required configuration

Add these GitHub Actions secrets. Do not commit their values.

| Secret | Purpose |
| --- | --- |
| `WP_BASE_URL` | WordPress site base URL, without any required path beyond the site root. |
| `WP_USERNAME` | WordPress user name. |
| `WP_APP_PASSWORD` | WordPress Application Password used with Basic Auth. |

Optional repository variable:

| Variable | Default | Purpose |
| --- | --- | --- |
| `WP_NEW_POST_STATUS` | `draft` | Status for newly created posts during automatic or `preserve` runs. Use a WordPress REST API status such as `draft`, `pending`, or `publish`. |

## Article files

Create an HTML file at `articles/<slug>.html`. The file stem becomes the WordPress post slug, and the full HTML file becomes the post content.

You may add `articles/<slug>.json` with any of these fields:

```json
{
  "title": "Product title",
  "excerpt": "Short excerpt",
  "categories": [1, 2],
  "tags": [3, 4],
  "comment_status": "closed",
  "ping_status": "closed"
}
```

If the JSON file is missing or does not include `title`, the script uses the first `<h2>` in the HTML as the title. If no `<h2>` exists, it creates a readable title from the slug.

## Create and update behavior

For each article, the script searches `/wp-json/wp/v2/posts` by slug with edit context:

- If no post exists, it creates one at `/wp-json/wp/v2/posts`.
- If a post exists, it updates `/wp-json/wp/v2/posts/<id>`.
- Automatic updates preserve the existing WordPress post status.
- New posts use `WP_NEW_POST_STATUS`, or `draft` when the variable is unset.

Manual runs expose a status selector:

- `preserve`: keep existing statuses and use `WP_NEW_POST_STATUS` for new posts.
- `draft`, `pending`, `publish`: send that status for both created and updated posts.

Manual runs also include `dry_run`, which validates and prints the resolved slug, title, and status without sending anything to WordPress.

## Local validation

Run these checks before changing the workflow:

```bash
python -m py_compile scripts/publish_to_wordpress.py
python scripts/publish_to_wordpress.py --dry-run articles/example.html
```

YAML can be parsed with a local YAML parser when available, for example Ruby's standard `psych` parser:

```bash
ruby -e 'require "yaml"; YAML.load_file(".github/workflows/publish-to-wordpress.yml"); puts "ok"'
```
