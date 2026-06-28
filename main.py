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
    doc =
