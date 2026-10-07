# SALUS MEAL BOT — 安定化と使いやすさ改善 設計書

日付: 2026-10-07 / 方針: 案A（現行構成を強化。費用は0円のまま）

## 1. 目的・制約・成功条件

- 目的: 顧客の食事を自動で記録・カロリー計算し、スタッフはダッシュボードで確認するだけ、という運用を「放置でも壊れにくく」「顧客が続けやすく」する。
- 制約: 追加費用0円（Render無料 / Gemini無料枠 / Firestore無料枠 / LINE無料プラン）。運営側の手作業を増やさない。作り直しはしない。
- 成功条件:
  1. LINEの再送・偽リクエスト・Gemini枠切れで、記録の重複・不正な書き込み・無応答が起きない。
  2. 顧客が1通送るだけで「今日あと何kcalか」まで分かり、目標設定も数字の書式を覚えずに完了できる。
  3. 異常時にスタッフが自分で気付ける（既存のUptimeRobotメール＋朝のヘルスチェックを維持）。

## 2. 現状（変更しない部分）

Flask + gunicorn(gthread, 4 threads, timeout 90) / Render無料(Virginia) / Firestore(東京, REST互換層 `firestore_rest.py`) / Gemini(`gemini-2.5-flash`) / LINE Messaging API。
既に実装済み: 入力中アニメーション、返信失敗時のプッシュ通知フォールバック、処理ごとのエラー処理、`/health`、朝のヘルスチェック(GitHub Actions)、UptimeRobot(5分間隔)。

## 3. 範囲外（今回やらない）

ホスティング移行 / 作り直し / 非同期処理化 / リマインド配信（LINEのプッシュ無料枠が小さいため。プラン確認後に別途判断）/ スタッフ向け「未記録日数」表示 / `note_system/` / Geminiの有料化。

## 4. 設計

### 4.1 二重記録の防止（再送対策）

- LINEは応答が遅いと同じイベントを再送する。`message.id` を一意キーとして、処理開始時に Firestore `processed_messages/{message_id}` を**排他的に作成**して「処理権」を取る。
- `firestore_rest.py` に `create_if_absent(segments, data) -> bool` を追加: PATCH に `currentDocument.exists=false` を付ける。既に存在する場合は「取得できなかった」として False を返す（HTTP 409、または 400 かつ status が `FAILED_PRECONDITION`/`ALREADY_EXISTS` の場合。実装時に実APIで挙動を確認する）。
- False の場合はそのイベントを無視して 200 を返す。
- 処理中に想定外の例外で落ちた場合は、取得した処理権を削除して再送時にやり直せるようにする。
- 保存データは `{claimed_at, expires_at(7日後)}` のみ。古い文書の自動削除は、Firestoreコンソールで `expires_at` にTTLポリシーを一度だけ設定する（任意。未設定でも容量はごく小さい）。

### 4.2 なりすまし防止（署名検証）

- `/callback` で `X-Line-Signature` を検証する: `base64(HMAC-SHA256(LINE_CHANNEL_SECRET, 生のリクエストボディ))` と一致しなければ 400 を返して何も処理しない。
- 環境変数 `LINE_CHANNEL_SECRET` が未設定の場合は、**検証を無効化して起動時に警告ログを出す**（設定漏れでBOT全体が止まらないようにするため）。`/health` の結果に `signature_verification: true/false` を含め、朝のヘルスチェックで気付けるようにする。
- LINE Developersの「検証」ボタン（空events）も署名付きなので通る。

### 4.3 `/health` の悪用対策

- `/health` の結果をプロセス内で**5分間キャッシュ**する。誰が何回叩いても、Gemini呼び出しとFirestore書き込みは最大でも5分に1回。キャッシュ期間中は同じ結果を返す。

### 4.4 Gemini枠切れ対策

- `gemini_generate` を「主モデルで最大2回 → だめなら予備モデルで1回」に変更（最悪待ち時間を現行以下に抑える）。モデル名は環境変数 `GEMINI_MODEL`(既定 `gemini-2.5-flash`)・`GEMINI_FALLBACK_MODEL`(既定 `gemini-2.5-flash-lite`)。無料枠はモデルごとに枠が別なので、片方が枠切れでももう片方で動く可能性がある。
- 実装時にモデル名が現在も有効かAPIで確認する（モデルは廃止されることがあるため）。
- 失敗した場合は既存のエラー文面を返す（変更なし）。

### 4.5 返信の改善

- **進捗の同時表示**: 食事・運動・写真の記録成功後の返信末尾に「今日の合計: 摂取◯kcal / 消費◯kcal / 目標まであと◯kcal（目標未設定なら合計のみ）」を追加。`get_daily_total`/`get_daily_exercise_total`/`get_goal` は**3つ並列**で読み、遅延の増加を抑える。取得に失敗しても記録成功の返信自体は送る（進捗行だけ省略）。
- **クイックボタン**: 記録成功の返信に LINE の quick reply（「取り消す」→送信テキスト`やり直し`、「今日の合計」→`今日の合計`）を付ける。既存の判定ロジックで処理されるため新しい分岐は不要。`reply_message` に任意引数 `quick_reply` を追加する。ボタンはプッシュ枠を消費しない。
- **目標設定の対話化**: 「目標設定」だけ送られたら Firestore `conversations/{user_id}` に `{flow:"goal", step, data, updated_at}` を保存し、順に質問する（カロリー → タンパク質 → 脂質 → 炭水化物）。タンパク質以降は「なし」でスキップ可。全角数字は NFKC 正規化。数字以外は例付きで1度だけ聞き直す。「キャンセル」で中止。`updated_at` から30分以上経った状態は無視する。
  - 進行中の会話は**判定(classify)より前**に処理する（数字が食事と誤判定されないため）。
  - 進行中でも「合計」「記録」「削除」「使い方」「体重」を含むコマンド文が来たら会話を中止して通常処理する。
  - 従来の一行書式「目標設定 2000 150 50 250」は引き続き動作する（互換維持）。

## 5. データ・設定の変更

- 新規コレクション: `processed_messages`, `conversations`（どちらも小さな文書）。
- 新規環境変数（Render）: `LINE_CHANNEL_SECRET`（必須推奨）、`GEMINI_MODEL`/`GEMINI_FALLBACK_MODEL`（任意）。
- `requirements.txt` は変更なし（HMACは標準ライブラリ）。テスト用の `requirements-dev.txt` に `pytest` を追加（本番には入れない）。

## 6. エラー処理の方針

- 付加機能（進捗行・クイックボタン・重複チェックのFirestore障害）が失敗しても、**記録と返信という主機能は止めない**。重複チェックのFirestore自体が障害の場合は処理を続行（二重記録のリスクより無応答を避ける）。
- 想定外の例外はログに出力して握りつぶさない（既存の `traceback.print_exc()` 方針を維持）。

## 7. テストと検証

- `tests/`（pytest）: メモリ上の偽Firestore（`firestore_rest` と同じインターフェース）とGeminiのモックで、(a) 重複メッセージの無視と例外時の処理権解放、(b) 署名検証の合否と未設定時の挙動、(c) `/health` のキャッシュ、(d) Gemini主→予備の切替、(e) 目標設定の対話（正常系・スキップ・キャンセル・コマンド割り込み・30分失効・一行書式互換）、(f) 進捗行の組み立て、をローカルで検証。
- 本番検証: デプロイ後、(1) LINE Developersの「検証」ボタン成功、(2) `/health` が `signature_verification: true`、(3) 実機LINEで 食事→進捗行とボタン表示、「取り消す」動作、目標設定の対話、同じ写真/文の再送で重複しないこと、を確認。

## 8. 公開手順とロールバック

1. Renderの環境変数に `LINE_CHANNEL_SECRET` を設定（ユーザーが値を用意。設定変更前に確認を取る）。
2. mainへpush → 自動デプロイ。
3. 上記の本番検証を実施。
4. 問題があれば `git revert` して再デプロイ（またはRenderの以前のデプロイへ戻す）。署名検証だけを一時的に外したい場合は `LINE_CHANNEL_SECRET` を空にすれば無効化される。

## 9. 未確認事項（実装前後に確認）

- LINE公式アカウントのプランとプッシュ通知の月間無料枠（リマインド配信を将来検討するため）。
- Gemini無料枠の入力データの扱い（改善目的の利用がある場合は、顧客への案内文の追加を検討）。
- Firestoreの前提条件付き書き込み(`currentDocument.exists=false`)の実際のHTTP応答。
