# 実行指示：note記事の下書きを1本生成する

このファイルは、定期実行タスク（スケジュール）またはユーザーの指示によって呼び出されたときに実行する手順書。

## 前提として読み込むファイル
- [business_profile.json](./business_profile.json) — 事業・ターゲット・トーン
- [content_strategy.md](./content_strategy.md) — コンテンツ方針・タイトルの型・CTAテンプレート・タグ運用
- [content_calendar.json](./content_calendar.json) — ピラーのローテーション状態・ネタ候補・使用済みトピック
- [past_articles.json](./past_articles.json) — 既存記事一覧（重複回避・トーン参考用）

## 手順

1. `content_calendar.json` の `next_pillar_index` を見て、今回生成するピラーを `pillar_rotation` から特定する。
2. そのピラーの `topic_pool` からまだ `used_topics` に入っていないトピックを1つ選ぶ。候補が尽きていたら、同ピラーの方向性でオリジナルの新しいトピックを1つ考案する。
3. [content_strategy.md](./content_strategy.md) の「タイトルの型」「本文構成」「CTAテンプレート」「タグ運用」「やらないこと」に厳密に従い、note投稿用の記事を作成する。
   - タイトルには悩み・検索ワード（肩こり／猫背／腰痛／頭痛／自律神経／姿勢／疲労 等）を必ず含める。
   - 本文末に必ずCTAブロックを入れる（テーマに合わせて1文目のみ調整可）。
   - 文字数目安 2,500〜4,000字。
   - 記事末に推奨タグ一覧を記載する。
4. 生成した記事を `note_system/drafts/YYYY-MM-DD_slug.md` として保存する（`YYYY-MM-DD` は実行日、`slug` はタイトルから短い英数字スラッグを作る）。ファイル冒頭に以下のメタ情報を含める。
   ```
   ---
   title: <タイトル>
   pillar: <今回のピラー名>
   target_keyword: <狙った検索ワード>
   status: draft
   created: <実行日>
   ---
   ```
5. `content_calendar.json` を更新する：
   - 使ったトピックを `used_topics` に追記（トピック名・日付・ピラー名）
   - `next_pillar_index` を次のインデックスに進める（配列の最後なら0に戻す）
   - `last_generated` を実行日に更新、`generation_count` を+1
6. ユーザーに完了報告をする。報告には以下を含める：
   - 生成したファイルパス
   - 記事タイトルと狙ったキーワード
   - 「内容を確認のうえ、問題なければnoteに手動で投稿してください」という一言
   - CTAブロックが入っていることの確認

## 重要な制約
- **note.comへの自動投稿・自動ログインは行わない。** 生成するのはあくまで下書きファイルであり、投稿はユーザーが手動で行う。
- 同じトピック・同じ切り口を連続で生成しない（`used_topics` を必ず確認する）。
- 医療的な断定表現、誇大な効果保証は書かない。
