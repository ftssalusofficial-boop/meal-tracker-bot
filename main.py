全部消して以下をコピペしてください👇
pythonfrom flask import Flask, request
import os
import json
import requests
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

def get_line_image(message_id):
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
    response = requests.get(url, headers=headers)
    return response.content

def analyze_food_text(text):
    prompt = f"「{text}」の栄養素を教えてください。カロリー、タンパク質、脂質、炭水化物をJSON形式のみで返してください。他の文章は不要です。例：{{\"dish\":\"料理名\",\"calories\":500,\"protein\":20,\"fat\":15,\"carbs\":60}}"
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text

def analyze_food_image(image_bytes):
    prompt = "この食事の写真を見て、料理名とカロリー、タンパク質、脂質、炭水化物をJSON形式のみで返してください。他の文章は不要です。例：{\"dish\":\"料理名\",\"calories\":500,\"protein\":20,\"fat\":15,\"carbs\":60}"
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            prompt
        ]
    )
    return response.text

def analyze_exercise(text):
    prompt = f"「{text}」の消費カロリーを教えてください。運動名と消費カロリーをJSON形式のみで返してください。他の文章は不要です。例：{{\"exercise\":\"ウォーキング30分\",\"burned_calories\":120}}"
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

def save_exercise(user_id, exercise_data):
    now = datetime.now(JST)
    date_str = now.strftime("%Y-%m-%d")
    doc_ref = db.collection("exercises").document(user_id).collection(date_str).document()
    doc_ref.set({
        "exercise": exercise_data["exercise"],
        "burned_calories": exercise_data["burned_calories"],
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
        cal_percent = int(net / goal["calories"] * 100)
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
            if user_text == "今日の合計":
                total = get_daily_total(user_id)
                burned = get_daily_exercise_total(user_id)
                goal = get_goal(user_id)
                reply = format_total_reply(total, burned, goal)
            elif user_text.startswith("運動"):
                try:
                    result = analyze_exercise(user_text)
                    clean = result.strip().replace("```json", "").replace("```", "").strip()
                    exercise_data = json.loads(clean)
                    save_exercise(user_id, exercise_data)
                    reply = f"🏃 {exercise_data['exercise']}\n\n消費カロリー：{exercise_data['burned_calories']} kcal\n\n✅ 記録しました！"
                except:
                    reply = "運動を認識できませんでした。\n例：運動 ウォーキング 30分"
            elif user_text.startswith("目標設定"):
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
                    reply = "目標設定の形式が正しくありません。\n例：目標設定 2000 150 50 250\n（カロリー タンパク質 脂質 炭水化物）"
            else:
                result = analyze_food_text(user_text)
                try:
                    clean = result.strip().replace("```json", "").replace("```", "").strip()
                    meal_data = json.loads(clean)
                    save_meal(user_id, meal_data)
                    reply = f"🍽 {meal_data['dish']}\n\nカロリー：{meal_data['calories']} kcal\nタンパク質：{meal_data['protein']} g\n脂質：{meal_data['fat']} g\n炭水化物：{meal_data['carbs']} g\n\n✅ 記録しました！"
                except:
                    reply = "食事を認識できませんでした。料理名を入力してみてください。"
            reply_message(reply_token, reply)

        else:
            reply_message(reply_token, "料理名か食事の写真を送ってください！")
    return "OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
