# SALUS MEAL BOT — 監視・即時通知・朝の連絡の裏付け 設計書

日付: 2026-10-07 / 費用: 0円 / 先に実装する（`2026-10-07-meal-bot-hardening-design.md` はこの後）

## 1. 背景と目的

- 現状の朝の連絡は `/health`（サーバーが生きているか）しか確認しておらず、「正常」と通知されても、実際にメッセージを受けて返信できたかは分からない。通知はGitHubの定期実行の遅延で7時ではなく9〜11時頃に届いている。
- 調査の結果（Renderログ7日分・LINE配信統計・Firestore記録）、9/26〜10/6は受信0件・返信0件だが、「障害があった」のか「誰も使わなかった」のかを後から判別できなかった。Renderのログは7日で消える。
- 目的: (1) 返信できない状況になったら**すぐ自動で通知**、(2) 朝の連絡が**本当に動いている裏付け**を持つ、(3) 後から原因を追える**実績ログ**を残す。
- 成功条件: 実メッセージの処理失敗が数分以内にスタッフのLINEへ通知される / 10〜15分おきの自動テストが失敗・停止したらUptimeRobotのメールと本BOTのLINE通知で分かる / 朝の連絡に「昨日の受信・成功・失敗件数」と「最後の自動テスト結果」が含まれ、「利用なし」と「正常」が区別される。

## 2. できないこと（正直な限界）

LINEにはユーザーとして送信する手段がなく、実際のユーザー端末へ届くまでの最終区間は外部から検証できない。代わりに、(a) LINE公式の疎通テスト、(b) 決まった文章のAI判定、(c) 返信API用キーと形式の検証、(d) 実メッセージごとの結果記録と失敗通知、で近い保証をする。

## 3. 範囲外

ホスティング移行 / 顧客向けUX改善・二重記録防止・署名検証（別設計書）/ `note_system/` / 有料サービス。

## 4. 設計

### 4.1 実績ログ（A）

- 保存先: Firestore `bot_events/{YYYY-MM-DD(JST)}/items/{自動ID}`。
- 項目: `ts`(JST ISO), `user_id`, `kind`("text"/"image"/"follow"/"other"), `outcome`("ok"/"handler_error"/"reply_failed"), `duration_ms`, `reply_via`("reply"/"push"/null), `reply_status`(整数またはnull), `error`(200文字まで・メッセージ本文は含めない)。
- `reply_message` は戻り値 `{"ok": bool, "via": "reply"|"push"|None, "status": int|None}` を返すよう変更（現行のpushフォールバックは維持）。
- 既存の各 `except` が `traceback.print_exc()` を呼んでいる箇所を `log_error(label)` に置換。`log_error` は従来どおりトレースバックを出力し、さらに `flask.g` のイベント別エラーリストへ `label` を追加する。1イベントで1つでもエラーがあれば `outcome="handler_error"`。
- `callback()` の各イベント処理を try/except で包み、想定外の例外も `handler_error` として記録して200を返す（LINEの再送ループを避ける）。ログ書き込みの失敗は握りつぶしてログ出力のみとし、**返信処理は絶対に止めない**。

### 4.2 即時通知（B）

- `alert_staff(key, text)`: 環境変数 `ALERT_LINE_USER_ID` 宛てにLINEプッシュ。未設定なら送信せず起動時に警告し、`/status` に `alerts_configured:false` を出す。
- 頻度制限: `key` ごとに30分に1回（Firestore `system/alerts` の `{key: 最終送信ISO}`をmerge更新）。プッシュ送信自体の失敗はログのみ。
- 通知条件: 実イベントの `outcome != "ok"`（key=`event_failure`、本文に時刻・種別・原因・ユーザー表示名）/ カナリアの2回連続失敗（key=`canary_failure`）。

### 4.3 自動テスト（カナリア・C）

`run_canary()` が次を確認し、結果を Firestore `system/canary` に `{ran_at, ok, checks, last_ok_at, consecutive_failures}` として保存する。

1. `line_webhook`: `GET /v2/bot/channel/webhook/endpoint` が `active:true` かつ URL が `PUBLIC_BASE_URL + "/callback"`（環境変数、既定は本番URL）と一致、かつ `POST /v2/bot/channel/webhook/test` が `success:true, statusCode:200`（LINE側から本番へ実際にPOSTが届く）。
2. `line_reply_api`: `POST /v2/bot/message/validate/reply` が200（キーと形式の検証のみで送信しない）。404などエンドポイント非対応の場合は `skipped` とし失敗にしない。
3. `gemini`: `classify_and_analyze("ラーメン")` が `type=="食事"` かつ `calories` が数値。**1時間に1回まで**（無料枠節約）。`system/canary.gemini_checked_at` で管理。それ以外の回は前回結果を引き継ぐ。
4. `firestore`: `system/canary` 自体の書き込みと読み戻しで確認。

起動方法: 外部ping（UptimeRobot・GitHub keep-alive）が叩く `GET /status` が、前回実行から15分以上経っていて実行中でなければ、バックグラウンドスレッドで `run_canary()` を開始する（gthreadで並行処理）。専用スケジューラは使わない。

### 4.4 `/status`

- 認証なし・低コスト。`system/canary` を読み（プロセス内で30秒キャッシュ）、`{state, ok, canary_ok, canary_age_min, last_ok_at, alerts_configured, checks}` のJSONを返す。HEADでも同じ挙動。
- `state`: `warming_up`（プロセス起動後10分以内で未実行）→ HTTP 200 / `ok`（直近の結果が成功かつ経過45分以内）→ 200 / それ以外（失敗または45分超の停止）→ **503**。UptimeRobotは503を「ダウン」と判定してメール通知する。
- `?detail=1` では前日(JST)の `bot_events` を集計して `yesterday:{received, ok, failed, last_received_at}` を付ける。

### 4.5 朝の連絡（D）

- 送信元をGitHub Actionsからサーバーに移す（GitHubの定期実行が遅延するため）。`/status` が呼ばれた時、JSTの7:00〜7:30で、かつ Firestore `system/morning_report.sent_date` が当日でなければ、バックグラウンドで送信してから `sent_date` を更新（冪等）。
- 本文: 前日の受信/成功/失敗件数と最終受信時刻、最後の自動テスト時刻と結果、各チェック結果。判定アイコン: ⚠️（失敗あり／自動テスト失敗・45分超停止／`alerts_configured:false`）> ℹ️（受信0件=「昨日の利用なし。サーバーとWebhookは正常」）> ✅。
- `.github/workflows/morning-health-check.yml` は削除する。`keep-alive.yml` はURLを `/status` に変更し、UptimeRobotが止まった場合の予備にする。

## 5. 設定・データ変更

- Render環境変数（新規）: `ALERT_LINE_USER_ID`（通知先スタッフのLINEユーザーID）、`PUBLIC_BASE_URL`（任意）。既存の `LINE_CHANNEL_ACCESS_TOKEN` を再利用。
- UptimeRobot: 既存モニターのURLを `/dashboard/login` から `/status` に変更（ユーザー操作）。
- 新規Firestore: `bot_events`, `system/canary`, `system/alerts`, `system/morning_report`。
- 要追加のLINE呼び出し: webhook endpoint取得・webhook test・validate/reply（いずれもチャネルアクセストークンのみ）。

## 6. エラー処理

- 監視・記録・通知の失敗は本来の処理（記録と返信）を止めない。カナリアやレポートは別スレッドで例外を握ってログに出す。
- カナリア自体が例外で落ちた場合は失敗として保存し、2回連続でアラート。
- 通知は頻度制限を超えない。LINEプッシュ枠（無料200件/月）は、通常時は朝の連絡1通/日のみ消費し、失敗時だけ追加で消費する（現在の使用量は7件）。

## 7. テストと検証

- pytest（偽Firestore・偽LINE・偽Gemini）: 実績ログの記録と失敗フラグ、ログ書き込み失敗時に返信が止まらないこと、アラートの頻度制限と未設定時の無効化、カナリアの2回連続失敗ルールとGemini1時間制限、`/status` の `warming_up`/`ok`/503の遷移、朝の連絡の冪等性と判定（利用なし/失敗あり/正常）。
- 本番検証: デプロイ後に `/status` が200で `canary_ok:true`、LINEでテストメッセージ→`bot_events` に記録、アラート経路はローカルから実トークンで「[テスト]」を1通だけ送って確認（本番を壊す疑似障害は起こさない）、翌朝7時台に朝の連絡が届くこと。

## 8. 公開手順とロールバック

1. 先に `ALERT_LINE_USER_ID` をRenderに設定（設定変更の前にユーザー確認）。
2. mainにpush→自動デプロイ→ `/status` と各確認。
3. UptimeRobotのURLを `/status` に変更（ユーザー操作）。
4. 問題があれば `git revert` して再デプロイ。UptimeRobotのURLを元に戻す。

## 9. 未確認事項

- `POST /v2/bot/message/validate/reply` が現在のアカウントで使えるか（使えなければ `skipped` 扱い）。
- UptimeRobot無料プランが503応答を「ダウン」としてメール通知すること（通常のHTTP監視の挙動）。
- Gemini無料枠の1日あたりの上限。カナリアは1時間1回（24回/日）に抑えている。
