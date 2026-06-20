# Codex ルアー記事生成ワークフロー

## GitHubへ配置するファイル

`generate-lure-article.yml` を、対象リポジトリの次の場所へ配置してください。

```text
.github/workflows/generate-lure-article.yml
```

このZIPには、以下の2種類を収録しています。

- `.github/workflows/generate-lure-article.yml`：そのままリポジトリへコピーできる正式配置版
- `generate-lure-article.yml`：隠しフォルダを表示しない環境でも確認できる同一内容の予備コピー

## 事前設定

GitHubリポジトリの `Settings > Secrets and variables > Actions` で、次のRepository secretを登録します。

```text
OPENAI_API_KEY
```

## 実行方法

1. リポジトリの `Actions` を開く
2. `Codexでルアー記事を生成` を選択
3. `Run workflow` を押す
4. 商品名、公式商品ページURL、保存用スラッグなどを入力する

保存用スラッグは `^[a-z0-9]+-[a-z0-9]+-impression$` に一致する3語・2ハイフン形式にします。投稿タイトルは常に `<正式商品名>のインプレ・使い方を徹底解説` とし、HTML、JSON、researchの3ファイルを同じスラッグで作成します。導入文1段落目の末尾にある `「正式商品名」` だけを公式商品ページへリンクし、公開HTMLではその1件以外のURLを禁止します。

生成記事はArtifactとして保存され、設定に応じてPull Requestも作成されます。

## 恒久的な記事完了フロー

今後のCodex記事作成タスクでは、記事HTMLとメタデータを生成した後、標準完了コマンドとして次を実行します。

```bash
npm run article:complete -- --slug <slug>
```

このコマンドは `npm test`、記事単体チェック、WordPress下書き投稿を順に実行します。通常モードではWordPressへ投稿できない場合、記事作成を完了扱いにしません。開発・検証でWordPressへ送信しない場合だけ、明示的に次を使います。

```bash
npm run article:complete -- --slug <slug> --local-only
```

WordPress投稿は `scripts/post-wp-draft.mjs` が担当し、ステータスは常に `draft` に固定します。投稿は、最小HTMLコメントだけの下書き作成後に完成本文を `content` のみで更新する2段階方式です。重複スラッグ・重複タイトル・既存 `wordpress_draft_id` をREST APIで確認し、最終的に `context=edit` で再取得してタイトル、スラッグ、draftステータス、本文SHA-256を検証します。成功後だけ `metadata.json`、`wp-result.md`、`check-report.md` を実値で更新します。

認証情報、Authorizationヘッダー、Cookie、プロキシURL、`.env` の内容はログや結果ファイルへ記録しません。
