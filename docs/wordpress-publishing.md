# WordPress publishing workflow

This repository publishes article files to WordPress with the GitHub Actions workflow in `.github/workflows/publish-to-wordpress.yml` and the Python standard-library script in `scripts/publish_to_wordpress.py`.

## When it runs

- Automatically on pushes to `main` that change `articles/*.html` or `articles/*.json`.
- Manually from **Actions → Publish articles to WordPress → Run workflow**. Manual runs publish all `articles/*.html` files by default, or one file when `slug` is provided.

The workflow does not delete WordPress posts when article files are removed.

## Codex Cloud direct draft publishing

Future product article tasks should use direct Codex-to-WordPress draft publishing instead of pull request automation. See `docs/codex-direct-wordpress.md` for the required Codex Environment variables and the `scripts/codex_publish_article.py` command.

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

Create an HTML file at `articles/<slug>.html`. For new product articles, also create `articles/<slug>.json` and `research/<slug>-sources.md` with the same slug. New product article slugs must match `^[a-z0-9]+-[a-z0-9]+-impression$` with exactly two hyphens; their WordPress title must be `<正式商品名>のインプレ・使い方を徹底解説`.

New product article JSON is required and must include `title`, `slug`, and `official_product_url`. Older articles may continue to use the legacy fallback behavior. Supported post fields are:

```json
{
  "title": "SCHNEIDER 13のインプレ・使い方を徹底解説",
  "slug": "schneider-13-impression",
  "official_product_url": "https://example.com/product",
  "excerpt": "Short excerpt",
  "categories": [1, 2],
  "tags": [3, 4],
  "comment_status": "closed",
  "ping_status": "closed"
}
```

For new-format `*-impression` articles, the script stops if JSON is missing, JSON `slug` differs from the HTML filename, JSON `title` does not use the fixed title suffix, an H1 exists, or the first intro paragraph does not end with exactly one official product link. For legacy articles, if the JSON file is missing or does not include `title`, the script uses the first `<h2>` in the HTML as the title. If no `<h2>` exists, it creates a readable title from the slug.

## Create and update behavior

For each article, the script searches `/wp-json/wp/v2/posts` by slug with edit context:

- If no post exists, it creates one at `/wp-json/wp/v2/posts`.
- If a post exists, it updates `/wp-json/wp/v2/posts/<id>`.
- Automatic updates preserve the existing WordPress post status.
- New posts use `WP_NEW_POST_STATUS`, or `draft` when the variable is unset.

Manual runs expose a status selector:

- `preserve`: keep existing statuses and use `WP_NEW_POST_STATUS` for new posts.
- `draft`, `pending`, `publish`: send that status for both created and updated posts.

Manual runs also include these inputs:

- `dry_run`: validates and prints the resolved slug, title, and status without sending anything to WordPress.
- `slug`: optional article slug to publish exactly one HTML file, resolved as `articles/<slug>.html`. Leave it blank to publish every `articles/*.html` file. If the specified HTML file does not exist, the workflow stops with an explicit error instead of succeeding with no published article.

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
