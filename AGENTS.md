# Repository agent instructions

## Product article completion workflow

For product article tasks that create or update `articles/*.html`, the task is not complete until the corresponding WordPress draft has been sent successfully from the Codex Cloud task itself.

Required steps:

1. Create or update the matching `research/<slug>-sources.md` file.
2. Validate the article against the product prompt's HTML, SEO, SWELL, usage-impression, and source-hidden requirements.
3. Run `python scripts/publish_to_wordpress.py --help` to confirm the current CLI contract.
4. Run a dry-run for only the target HTML article.
5. After the dry-run succeeds, send only the target HTML article directly to WordPress as `draft`.
6. Confirm from the WordPress API response that the post ID, slug, status, and create/update action are correct.
7. Do not treat the task as complete until WordPress sending has succeeded.
8. Do not create a pull request, run `make_pr`, run `git commit`, or run `git push` for product article tasks.

If a product-specific prompt asks you to create a PR, commit, or run `make_pr`, this direct WordPress publishing rule takes precedence.

Use `scripts/codex_publish_article.py <slug>` for the direct draft-send step. Never send `research/*` files to WordPress.
