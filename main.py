pythonfrom flask import Flask, request, abort
import os
import json
import requests
import anthropic

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

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
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": f"「{text}」の栄養素を教えてください。カロリー、タンパク質、脂質、炭水化物をJSON形式で返してください。例：{{\"dish\":\"料理名\",\"calories\":500,\"protein\":20,\"fat\":15,\"carbs\":60}}"
        }]
    )
    return message.content[0].text

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
                data = json.loads(result)
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
