# 実行指示：note運用の評価と改善提案

このファイルは、ユーザーが「note運用を評価して」「アナリティクス見て改善案出して」等を依頼したときに実行する手順書。
**note.comへのログインが必要な作業なので、必ずユーザーがブラウザ上でログイン済み（またはログイン操作をユーザー自身が行う）の状態で実施する。パスワード等の認証情報はClaudeが入力・保持しない。**

## 前提として読み込むファイル
- [business_profile.json](./business_profile.json)
- [content_strategy.md](./content_strategy.md)
- [content_calendar.json](./content_calendar.json)
- [analytics_log.csv](./analytics_log.csv) — 過去の記録

## 手順

1. ブラウザで `https://note.com/salus_seitai` を開き、ユーザーにログイン状態を確認する（未ログインなら、ユーザー自身にログインしてもらうよう依頼する。代行入力はしない）。
2. ログイン済みであれば note のクリエイターダッシュボード（アナリティクス画面）を開き、以下を確認する：
   - 全体のフォロワー数
   - 各記事のビュー数（PV）、スキ数、コメント数
   - 直近の増減トレンド
3. 取得した数値を [analytics_log.csv](./analytics_log.csv) に1行追記する（日付・フォロワー数・記事別PV/スキの要約・気づいた点）。
4. 過去ログと比較し、以下の観点で評価する：
   - フォロワー・PVは増加傾向か横ばいか
   - どのピラー（[content_calendar.json](./content_calendar.json) の分類）の記事が相対的に強いか
   - CTA導入後、CTA経由らしき動き（HPアクセス増・体験予約の問い合わせ増）があるか（ユーザーへのヒアリングで確認）
   - [content_strategy.md](./content_strategy.md) の方針（タイトルの型・CTA・タグ運用・ピラー分散）が実際の投稿で守られているか
5. 評価結果をもとに、具体的な改善提案を2〜4個、優先度付きで提示する（例：「特定ピラーへの偏りを是正」「タイトルの型を◯◯に寄せる」「CTA文言をA/Bテストする」など）。
6. ユーザーが合意した改善提案は [content_strategy.md](./content_strategy.md) または [content_calendar.json](./content_calendar.json) に反映する（ユーザー確認のうえで編集する）。

## 注意
- 数値の手入力・スクリーンショット読み取りはユーザーの手を借りる前提。Claudeが推測で数値を作らない。
- 改善提案は「なぜそう考えるか」の根拠（過去ログとの比較、他ピラーとの比較など）を必ず添える。
