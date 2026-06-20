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

## Future product article rules

For new product articles, prefer these permanent rules even when a product-specific prompt contains an old slug or title format:

- WordPress post title must be exactly `<正式商品名>のインプレ・使い方を徹底解説`; preserve the official product name spelling, case, and symbols, do not add words such as 評判/口コミ/おすすめ, do not add trailing punctuation, and do not add an H1 to the HTML body.
- Slugs for new articles must match `^[a-z0-9]+-[a-z0-9]+-impression$`: exactly three words, exactly two hyphens, lowercase ASCII letters and digits only, and the last word `impression`.
- Generate the first two slug words from the product series word and the size/model/variant word. Join multi-word series or model parts into one word, remove apostrophes, periods, spaces, and existing hyphens, and ask before writing when a safe official-English slug cannot be determined.
- Create exactly matching file stems for `articles/<slug>.html`, `articles/<slug>.json`, and `research/<slug>-sources.md`.
- `articles/<slug>.json` is required for new articles and must include at least `title`, `slug`, and `official_product_url`; WordPress publishing must use the JSON `title` and `slug` instead of inferring from the first H2.
- The first intro paragraph must end with a single official product-page link whose anchor text is `「正式商品名」`, including the Japanese brackets. Use the official product URL supplied by the product prompt, `target="_blank"`, and `rel="noopener noreferrer"`.
- Public HTML must not show raw URLs and must not include source lists or reference links. The only URL exception is the one official product-page href in the first intro paragraph, and it must exactly match the prompt's official product URL.
- Before dry-run or WordPress sending, validate the fixed title, slug regex and hyphen count, matching HTML/JSON/research filenames, JSON syntax/title/slug, first-paragraph official link, lack of extra URLs, absence of H1, and existing SEO/HTML/SWELL/usage-impression/bad-impression/source-hidden rules.


## Staged WordPress draft workflow for all article tasks

For every future article generation task, after creating the article HTML and metadata, run the repository standard completion command:

```bash
npm run article:complete -- --slug <slug>
```

Do not report an article as complete unless this command succeeds in normal mode. It runs tests, local article validation, staged WordPress draft creation, content update, REST API read-back verification, and final metadata/result report updates. Use `--local-only` or `--no-wordpress` only when the task is explicitly local development/testing; normal article work must not silently skip WordPress. WordPress status is always fixed to `draft`; do not add publish, future, pending, private, trash, or inherit posting flows.

The staged draft flow creates a minimal draft first and then updates only `content`. It must check duplicate slugs/titles and existing `wordpress_draft_id`, avoid unconditional repost after timeouts, and update `metadata.json`, `wp-result.md`, and `check-report.md` only after final REST read-back verification succeeds.
