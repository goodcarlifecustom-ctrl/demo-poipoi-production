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
