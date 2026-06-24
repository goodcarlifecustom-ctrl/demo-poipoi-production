# 新規SEO記事作成プロンプト

以下の入力がすべて揃うまで記事生成を開始しない。

- 対象メディア: `<target_media>`
- 記事タイプ: `<article_type>`
- メインキーワード: `<main_keyword>`
- 関連キーワード: `<related_keywords>`
- 想定読者: `<target_reader>`
- 記事の目的: `<article_goal>`
- 日本語可視本文文字数設定: `char_count.min`, `char_count.target`, `char_count.max`（整数、`min <= target <= max`）
- WordPress下書き投稿: `wordpress_draft: true`（`articles/_template` は誤投稿防止のため `false`。実記事作成時に明示的に `true` へ変更する）

完成本文は `templates/gutenberg-article.html` を基準に、front matterなしのGutenbergブロックマークアップで作成する。本文内にH1、Markdown見出し、Markdownリスト、Markdown画像、作業ログ、メタデータを残さない。


`post_to_wp` は後方互換用の同義フィールドです。新規入力・新規ドキュメントでは `wordpress_draft` だけを使用し、両方を指定する場合は同じboolean値にしてください。`status` はユーザー入力にせず、ワークフローが常に `draft` を設定します。
