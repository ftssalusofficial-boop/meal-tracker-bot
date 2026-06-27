from flask import Flask, request
import os
import json
import requests
from google import genai

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

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

@app.route("/callback", methods=["POST"])
def callback():
    body = request.get_json()
    for event in body.get("events", []):
        if event["type"] != "message":
            continue
        reply_token = event["replyToken"]
        msg_type = event["message"]["type"]
        if msg_type == "text":
            user_text = event["message"]["text"]
            result = analyze_food(user_text)
            try:
                clean = result.strip().replace("```json", "").replace("```", "").strip()
                data = json.loads(clean)
                reply = f"🍽 {data['dish']}\n\nカロリー：{data['calories']} kcal\nタンパク質：{data['protein']} g\n脂質：{data['fat']} g\n炭水化物：{data['carbs']} g"
            except:
                reply = "食事を認識できませんでした。料理名を入力してみてください。"
            reply_message(reply_token, reply)
        else:
            reply_message(reply_token, "テキストで料理名を送ってください！")
    return "OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
