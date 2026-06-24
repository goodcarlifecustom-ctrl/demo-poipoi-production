# 新規SEO記事 Gutenberg 出力ルール

- 完成記事はMarkdownではなく、WordPressコードエディターでブロック認識されるGutenbergブロックコメント付きHTMLで出力する。
- 通常段落、H2/H3、リスト、表、画像はWordPress標準ブロックを使い、記事全体を単一の `wp:html` で包まない。
- 新規記事入力では `target_media`, `article_type`, `main_keyword`, `related_keywords`, `target_reader`, `article_goal`, `char_count.min`, `char_count.target`, `char_count.max`, `wordpress_draft` を必須にする。
- 日本語可視本文文字数は `min <= target <= max` を満たす整数のみ許可し、HTMLタグ・ブロックコメント・script/style・作業用コメントを除いた表示文字数がmin未満またはmax超過なら投稿しない。
- ユーザー向け設定は `wordpress_draft` に統一する。`post_to_wp` は後方互換用の同義フィールドに限り、両方指定時に値が異なれば停止する。`status` はワークフロー側で常に `draft` に固定し、公開済み記事を直接更新しない。
- WordPress REST API の `content` にはfront matter、作業ログ、メタデータ、Markdown原稿、rendered.htmlを含めない。
- 導入文の後、最初のH2より前に「この記事でわかること」を置き、主要H2へのアンカーリンクを設定する。
- H2 idは `sec-01`, `sec-02`, `sec-03` の連番にし、目次リンクのhref・アンカーテキストは遷移先H2のid・文言と一致させる。
- 検証でブロック対応、二重変換なし、finalize冪等性、重複idなし、missing targetなし、H1なし、タイトル本文重複なし、Markdown構文なしを確認する。

- `articles/_template` は投稿不可の雛形であり、`wordpress_draft: false` のままにする。実記事作成時にslug・タイトル・キーワード等のプレースホルダーを置換し、投稿する場合だけ `wordpress_draft: true` に変更する。
