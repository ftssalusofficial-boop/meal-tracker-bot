from flask import Flask, request, session
import os
import json
import requests
import time
from google import genai
from google.genai import types
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FIREBASE_CREDENTIALS = os.environ.get("FIREBASE_CREDENTIALS")

cred_dict = json.loads(FIREBASE_CREDENTIALS)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

from dashboard import init_dashboard
init_dashboard(app)

client = genai.Client(api_key=GEMINI_API_KEY)

JST = timezone(timedelta(hours=9))

HELP_TEXT = """📖 SALUS MEAL 使い方

🍽 食事を記録
料理名を送るだけ！
例：ラーメン、サラダチキン

📸 写真で記録
食事の写真を送るだけ！

🏃 運動を記録
例：ウォーキング30分
　　スクワット50回
　　ベンチプレス60kg 10回3セット

📊 今日の合計
「今日の合計」と送ってください

📋 今日の記録
「今日の記録」と送ってください

🗑 削除
「削除」→番号を選んで削除
「やり直し」→直前の記録を削除

🎯 目標設定
以下の形式で送ってください：
目標設定 2000 150 50 250
（カロリー タンパク質 脂質 炭水化物）"""

def reply_message(reply_token, text):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    data = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=data)

def get_line_image(message_id):
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
    response = requests.get(url, headers=headers)
    return response.content

def save_user_profile(user_id):
    doc = db.collection("users").document(user_id).get()
    if not doc.exists:
        url = f"https://api.line.me/v2/bot/profile/{user_id}"
        headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            profile = response.json()
            db.collection("users").document(user_id).set({
                "display_name": profile.get("displayName", "不明"),
                "picture_url": profile.get("pictureUrl", "")
            })

def gemini_generate(prompt, image_bytes=None):
    for i in range(3):
        try:
            if image_bytes:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                        prompt
                    ]
                )
            else:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt
                )
            return response.text
        except Exception as e:
            if i == 2:
                raise e
            time.sleep(2)

def classify_message(text):
    prompt = f"""以下のメッセージが「食事」「運動」「合計確認」「目標設定」「記録一覧」「削除リスト」「やり直し」「使い方」「その他」のどれかを判定してください。
JSONのみで返してください。例：{{"type":"食事"}}

判定ルール：
- 料理名、食べ物、飲み物 → 食事
- 歩いた、走った、泳いだ、歩数、ジョギング、ウォーキング、筋トレ、スクワット、ベンチプレス、腕立て、腹筋、種目名、運動、トレーニング → 運動
- 今日の合計、合計 → 合計確認
- 目標設定 → 目標設定
- 今日の記録、記録一覧、記録を見る → 記録一覧
- 削除、削除したい、消したい → 削除リスト
- やり直し、取り消し、間違えた → やり直し
- 使い方、ヘルプ、help → 使い方
- それ以外 → その他

メッセージ：「{text}」"""
    result = gemini_generate(prompt)
    clean = result.strip().replace("```json", "").replace("```", "").strip()
    data = json.loads(clean)
    return data.get("type", "その他")

def analyze_food_text(text):
    prompt = f"「{text}」の栄養素を教えてください。カロリー、タンパク質、脂質、炭水化物をJSON形式のみで返してください。他の文章は不要です。例：{{\"dish\":\"料理名\",\"calories\":500,\"protein\":20,\"fat\":15,\"carbs\":60}}"
    return gemini_generate(prompt)

def analyze_food_image(image_bytes):
    prompt = "この食事の写真を見て、料理名とカロリー、タンパク質、脂質、炭水化物をJSON形式のみで返してください。他の文章は不要です。例：{\"dish\":\"料理名\",\"calories\":500,\"protein\":20,\"fat\":15,\"carbs\":60}"
    return gemini_generate(prompt, image_bytes)

def analyze_exercise(text):
    prompt = f"「{text}」の消費カロリーを教えてください。運動名と消費カロリーをJSON形式のみで返してください。歩数の場合は距離と消費カロリーを計算してください。他の文章は不要です。例：{{\"exercise\":\"ウォーキング30分\",\"burned_calories\":120}}"
    return gemini_generate(prompt)

def save_meal(user_id, meal_data):
    now = datetime.now(JST)
    date_str = now.strftime("%Y-%m-%d")
    doc_ref = db.collection("meals").document(user_id).collection(date_str).document()
    doc_ref.set({
        "dish": meal_data["dish"],
        "calories": meal_data["calories"],
        "protein": meal_data["protein"],
        "fat": meal_data["fat"],
        "carbs": meal_data["carbs"],
        "timestamp": now.isoformat()
    })

def save_exercise(user_id, exercise_data):
    now = datetime.now(JST)
    date_str = now.strftime("%Y-%m-%d")
    doc_ref = db.collection("exercises").document(user_id).collection(date_str).document()
    doc_ref.set({
        "exercise": exercise_data["exercise"],
        "burned_calories": exercise_data["burned_calories"],
        "timestamp": now.isoformat()
    })

def get_today_records_with_ids(user_id):
    now = datetime.now(JST)
    date_str = now.strftime("%Y-%m-%d")
    records = []
    meals = db.collection("meals").document(user_id).collection(date_str).order_by("timestamp").stream()
    for doc in meals:
        d = doc.to_dict()
        records.append({"type": "食事", "id": doc.id, "name": d["dish"], "calories": d["calories"], "timestamp": d["timestamp"]})
    exercises = db.collection("exercises").document(user_id).collection(date_str).order_by("timestamp").stream()
    for doc in exercises:
        d = doc.to_dict()
        records.append({"type": "運動", "id": doc.id, "name": d["exercise"], "calories": d["burned_calories"], "timestamp": d["timestamp"]})
    records.sort(key=lambda x: x["timestamp"])
    return records, date_str

def show_delete_list(user_id):
    records, _ = get_today_records_with_ids(user_id)
    if not records:
        return "今日はまだ記録がありません。"
    reply = "🗑 削除する番号を送ってください\n例：「削除 2」\n"
    for i, r in enumerate(records, 1):
        if r["type"] == "食事":
            reply += f"\n{i}. 🍽 {r['name']}（{r['calories']} kcal）"
        else:
            reply += f"\n{i}. 🏃 {r['name']}（消費{r['calories']} kcal）"
    return reply

def delete_by_number(user_id, number):
    records, date_str = get_today_records_with_ids(user_id)
    if not records:
        return "削除できる記録がありません。"
    if number < 1 or number > len(records):
        return f"1〜{len(records)}の番号を入力してください。"
    record = records[number - 1]
    if record["type"] == "食事":
        db.collection("meals").document(user_id).collection(date_str).document(record["id"]).delete()
    else:
        db.collection("exercises").document(user_id).collection(date_str).document(record["id"]).delete()
    return f"🗑 「{record['name']}」の記録を削除しました！"

def delete_last_record(user_id):
    now = datetime.now(JST)
    date_str = now.strftime("%Y-%m-%d")
    last_meal = None
    last_exercise = None
    meals = db.collection("meals").document(user_id).collection(date_str).order_by("timestamp", direction=firestore.Query.DESCENDING).limit(1).stream()
    for doc in meals:
        last_meal = (doc.id, doc.to_dict())
    exercises = db.collection("exercises").document(user_id).collection(date_str).order_by("timestamp", direction=firestore.Query.DESCENDING).limit(1).stream()
    for doc in exercises:
        last_exercise = (doc.id, doc.to_dict())
    if last_meal and last_exercise:
        if last_meal[1]["timestamp"] > last_exercise[1]["timestamp"]:
            db.collection("meals").document(user_id).collection(date_str).document(last_meal[0]).delete()
            return f"🗑 「{last_meal[1]['dish']}」の記録を削除しました！"
        else:
            db.collection("exercises").document(user_id).collection(date_str).document(last_exercise[0]).delete()
            return f"🗑 「{last_exercise[1]['exercise']}」の記録を削除しました！"
    elif last_meal:
        db.collection("meals").document(user_id).collection(date_str).document(last_meal[0]).delete()
        return f"🗑 「{last_meal[1]['dish']}」の記録を削除しました！"
    elif last_exercise:
        db.collection("exercises").document(user_id).collection(date_str).document(last_exercise[0]).delete()
        return f"🗑 「{last_exercise[1]['exercise']}」の記録を削除しました！"
    else:
        return "削除できる記録がありません。"

def get_today_records(user_id):
    records, _ = get_today_records_with_ids(user_id)
    if not records:
        return "今日はまだ記録がありません。"
    reply = "📋 今日の記録\n"
    for r in records:
        if r["type"] == "食事":
            reply += f"\n🍽 {r['name']}（{r['calories']} kcal）"
        else:
            reply += f"\n🏃 {r['name']}（消費{r['calories']} kcal）"
    return reply

def get_daily_total(user_id):
    now = datetime.now(JST)
    date_str = now.strftime("%Y-%m-%d")
    docs = db.collection("meals").document(user_id).collection(date_str).stream()
    total = {"calories": 0, "protein": 0, "fat": 0, "carbs": 0}
    for doc in docs:
        d = doc.to_dict()
        total["calories"] += d.get("calories", 0)
        total["protein"] += d.get("protein", 0)
        total["fat"] += d.get("fat", 0)
        total["carbs"] += d.get("carbs", 0)
    return total

def get_daily_exercise_total(user_id):
    now = datetime.now(JST)
    date_str = now.strftime("%Y-%m-%d")
    docs = db.collection("exercises").document(user_id).collection(date_str).stream()
    burned = 0
    for doc in docs:
        d = doc.to_dict()
        burned += d.get("burned_calories", 0)
    return burned

def set_goal(user_id, calories, protein=None, fat=None, carbs=None):
    data = {"calories": calories}
    if protein: data["protein"] = protein
    if fat: data["fat"] = fat
    if carbs: data["carbs"] = carbs
    db.collection("goals").document(user_id).set(data)

def get_goal(user_id):
    doc = db.collection("goals").document(user_id).get()
    if doc.exists:
        return doc.to_dict()
    return None

def format_total_reply(total, burned, goal):
    net = total["calories"] - burned
    reply = f"📊 今日の合計\n\n🍽 摂取カロリー：{total['calories']} kcal\n🏃 消費カロリー：{burned} kcal\n⚡ 純カロリー：{net} kcal"
    reply += f"\n\nタンパク質：{total['protein']} g\n脂質：{total['fat']} g\n炭水化物：{total['carbs']} g"
    if goal:
        reply += "\n\n🎯 目標との比較"
        cal_remaining = goal["calories"] - net
        cal_percent = int(net / goal["calories"] * 100) if goal["calories"] > 0 else 0
        if cal_remaining > 0:
            reply += f"\nカロリー：残り{cal_remaining} kcal（{cal_percent}%達成）"
        else:
            reply += f"\nカロリー：⚠️ 目標超過！"
        if "protein" in goal:
            p_remaining = goal["protein"] - total["protein"]
            p_percent = int(total["protein"] / goal["protein"] * 100)
            reply += f"\nタンパク質：残り{p_remaining} g（{p_percent}%達成）"
        if "fat" in goal:
            f_remaining = goal["fat"] - total["fat"]
            f_percent = int(total["fat"] / goal["fat"] * 100)
            reply += f"\n脂質：残り{f_remaining} g（{f_percent}%達成）"
        if "carbs" in goal:
            c_remaining = goal["carbs"] - total["carbs"]
            c_percent = int(total["carbs"] / goal["carbs"] * 100)
            reply += f"\n炭水化物：残り{c_remaining} g（{c_percent}%達成）"
    return reply

@app.route("/callback", methods=["POST"])
def callback():
    body = request.get_json()
    for event in body.get("events", []):
        if event["type"] != "message":
            continue
        reply_token = event["replyToken"]
        user_id = event["source"]["userId"]
        save_user_profile(user_id)
        msg_type = event["message"]["type"]

        if msg_type == "image":
            try:
                message_id = event["message"]["id"]
                image_bytes = get_line_image(message_id)
                result = analyze_food_image(image_bytes)
                clean = result.strip().replace("```json", "").replace("```", "").strip()
                meal_data = json.loads(clean)
                save_meal(user_id, meal_data)
                reply = f"📸 {meal_data['dish']}\n\nカロリー：{meal_data['calories']} kcal\nタンパク質：{meal_data['protein']} g\n脂質：{meal_data['fat']} g\n炭水化物：{meal_data['carbs']} g\n\n✅ 記録しました！"
            except:
                reply = "写真から料理を認識できませんでした。もう一度試してください。"
            reply_message(reply_token, reply)

        elif msg_type == "text":
            user_text = event["message"]["text"]

            if user_text.startswith("目標設定"):
                try:
                    parts = user_text.replace("目標設定", "").strip().split()
                    calories = int(parts[0])
                    protein = int(parts[1]) if len(parts) > 1 else None
                    fat = int(parts[2]) if len(parts) > 2 else None
                    carbs = int(parts[3]) if len(parts) > 3 else None
                    set_goal(user_id, calories, protein, fat, carbs)
                    reply = f"✅ 目標を設定しました！\nカロリー：{calories} kcal"
                    if protein: reply += f"\nタンパク質：{protein} g"
                    if fat: reply += f"\n脂質：{fat} g"
                    if carbs: reply += f"\n炭水化物：{carbs} g"
                except:
                    reply = "目標設定の形式が正しくありません。\n例：目標設定 2000 150 50 250"

            elif user_text.startswith("削除 "):
                try:
                    number = int(user_text.replace("削除", "").strip())
                    reply = delete_by_number(user_id, number)
                except:
                    reply = show_delete_list(user_id)

            else:
                try:
                    msg_type_classified = classify_message(user_text)
                except:
                    msg_type_classified = "その他"

                if msg_type_classified == "合計確認":
                    total = get_daily_total(user_id)
                    burned = get_daily_exercise_total(user_id)
                    goal = get_goal(user_id)
                    reply = format_total_reply(total, burned, goal)

                elif msg_type_classified == "運動":
                    try:
                        result = analyze_exercise(user_text)
                        clean = result.strip().replace("```json", "").replace("```", "").strip()
                        exercise_data = json.loads(clean)
                        save_exercise(user_id, exercise_data)
                        reply = f"🏃 {exercise_data['exercise']}\n\n消費カロリー：{exercise_data['burned_calories']} kcal\n\n✅ 記録しました！"
                    except:
                        reply = "運動を認識できませんでした。もう一度試してください。"

                elif msg_type_classified == "食事":
                    try:
                        result = analyze_food_text(user_text)
                        clean = result.strip().replace("```json", "").replace("```", "").strip()
                        meal_data = json.loads(clean)
                        save_meal(user_id, meal_data)
                        reply = f"🍽 {meal_data['dish']}\n\nカロリー：{meal_data['calories']} kcal\nタンパク質：{meal_data['protein']} g\n脂質：{meal_data['fat']} g\n炭水化物：{meal_data['carbs']} g\n\n✅ 記録しました！"
                    except:
                        reply = "食事を認識できませんでした。料理名を入力してみてください。"

                elif msg_type_classified == "記録一覧":
                    reply = get_today_records(user_id)

                elif msg_type_classified == "削除リスト":
                    reply = show_delete_list(user_id)

                elif msg_type_classified == "やり直し":
                    reply = delete_last_record(user_id)

                elif msg_type_classified == "使い方":
                    reply = HELP_TEXT

                else:
                    reply = HELP_TEXT

            reply_message(reply_token, reply)

        else:
            reply_message(reply_token, "料理名か食事の写真を送ってください！")
    return "OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
