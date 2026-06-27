from flask import Flask, request
import os
import json
import requests
from google import genai
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

client = genai.Client(api_key=GEMINI_API_KEY)

JST = timezone(timedelta(hours=9))

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

def analyze_food(text):
    prompt = f"「{text}」の栄養素を教えてください。カロリー、タンパク質、脂質、炭水化物をJSON形式のみで返してください。他の文章は不要です。例：{{\"dish\":\"料理名\",\"calories\":500,\"protein\":20,\"fat\":15,\"carbs\":60}}"
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text

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

def set_goal(user_id, calories):
    db.collection("goals").document(user_id).set({
        "calories": calories
    })

def get_goal(user_id):
    doc = db.collection("goals").document(user_id).get()
    if doc.exists:
        return doc.to_dict()
    return None

@app.route("/callback", methods=["POST"])
def callback():
    body = request.get_json()
    for event in body.get("events", []):
        if event["type"] != "message":
            continue
        reply_token = event["replyToken"]
        user_id = event["source"]["userId"]
        msg_type = event["message"]["type"]
        if msg_type == "text":
            user_text = event["message"]["text"]
            if user_text == "今日の合計":
                total = get_daily_total(user_id)
                goal = get_goal(user_id)
                reply = f"📊 今日の合計\n\nカロリー：{total['calories']} kcal\nタンパク質：{total['protein']} g\n脂質：{total['fat']} g\n炭水化物：{total['carbs']} g"
                if goal:
                    remaining = goal["calories"] - total["calories"]
                    percent = int(total["calories"] / goal["calories"] * 100)
                    if remaining > 0:
                        reply += f"\n\n🎯 目標：{goal['calories']} kcal\n残り：{remaining} kcal（{percent}%達成）"
                    else:
                        reply += f"\n\n🎯 目標：{goal['calories']} kcal\n⚠️ 目標カロリーを超えました！"
            elif user_text.startswith("目標設定"):
                try:
                    calories = int(user_text.replace("目標設定", "").strip())
                    set_goal(user_id, calories)
                    reply = f"✅ 目標カロリーを {calories} kcal に設定しました！"
                except:
                    reply = "目標設定の形式が正しくありません。\n例：目標設定 2000"
            else:
                result = analyze_food(user_text)
                try:
                    clean = result.strip().replace("```json", "").replace("```", "").strip()
                    meal_data = json.loads(clean)
                    save_meal(user_id, meal_data)
                    reply = f"🍽 {meal_data['dish']}\n\nカロリー：{meal_data['calories']} kcal\nタンパク質：{meal_data['protein']} g\n脂質：{meal_data['fat']} g\n炭水化物：{meal_data['carbs']} g\n\n✅ 記録しました！"
                except:
                    reply = "食事を認識できませんでした。料理名を入力してみてください。"
            reply_message(reply_token, reply)
        else:
            reply_message(reply_token, "テキストで料理名を送ってください！")
    return "OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
