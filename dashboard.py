from flask import request, render_template_string, redirect, session
import os
from firebase_admin import firestore
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "salus2024")

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SALUS 管理画面</title>
<style>
body { font-family: sans-serif; background: #f5f5f5; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
.box { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); width: 300px; }
h2 { text-align: center; color: #333; margin-bottom: 24px; }
input { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; box-sizing: border-box; margin-bottom: 16px; }
button { width: 100%; padding: 12px; background: #4CAF50; color: white; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; }
button:hover { background: #45a049; }
.error { color: red; text-align: center; margin-bottom: 12px; }
</style>
</head>
<body>
<div class="box">
<h2>🏋️ SALUS 管理画面</h2>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="post">
<input type="password" name="password" placeholder="パスワード">
<button type="submit">ログイン</button>
</form>
</div>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SALUS 管理画面</title>
<style>
body { font-family: sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }
h1 { color: #333; }
.date { color: #888; font-size: 14px; margin-bottom: 24px; }
.card { background: white; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.avatar { width: 48px; height: 48px; border-radius: 50%; background: #e0e0e0; object-fit: cover; flex-shrink: 0; }
.user-info { flex: 1; }
.user-name { font-size: 16px; font-weight: bold; color: #333; margin-bottom: 4px; }
.user-id { font-size: 11px; color: #bbb; margin-bottom: 6px; }
.stats { font-size: 13px; color: #555; }
.badge { padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: bold; }
.badge-good { background: #e8f5e9; color: #2e7d32; }
.badge-none { background: #f5f5f5; color: #999; }
.progress-bar { background: #eee; border-radius: 4px; height: 8px; width: 160px; margin-top: 8px; }
.progress-fill { background: #4CAF50; border-radius: 4px; height: 8px; }
.detail-btn { padding: 8px 16px; background: #2196F3; color: white; border: none; border-radius: 8px; cursor: pointer; text-decoration: none; font-size: 14px; white-space: nowrap; }
.logout { float: right; padding: 8px 16px; background: #f44336; color: white; border: none; border-radius: 8px; cursor: pointer; text-decoration: none; font-size: 14px; }
</style>
</head>
<body>
<h1>🏋️ SALUS 管理画面 <a href="/dashboard/logout" class="logout">ログアウト</a></h1>
<p class="date">📅 {{ date }}の記録</p>
{% for user in users %}
<div class="card">
  {% if user.picture_url %}
  <img class="avatar" src="{{ user.picture_url }}" alt="{{ user.display_name }}">
  {% else %}
  <div class="avatar" style="display:flex;align-items:center;justify-content:center;font-size:20px;">👤</div>
  {% endif %}
  <div class="user-info">
    <div class="user-name">{{ user.display_name }}</div>
    <div class="user-id">{{ user.user_id[:16] }}...</div>
    <div class="stats">
      🍽 摂取：{{ user.total_calories }} kcal　
      🏃 消費：{{ user.burned_calories }} kcal　
      ⚡ 純：{{ user.net_calories }} kcal
    </div>
    {% if user.goal_calories > 0 %}
    <div class="progress-bar">
      <div class="progress-fill" style="width: {{ [user.percent, 100]|min }}%"></div>
    </div>
    <div style="font-size:11px;color:#888;margin-top:4px;">目標 {{ user.goal_calories }} kcal の {{ user.percent }}% 達成</div>
    {% endif %}
  </div>
  <div style="display:flex;flex-direction:column;align-items:flex-end;gap:8px;">
    {% if user.has_record %}
    <span class="badge badge-good">✅ 記録あり</span>
    {% else %}
    <span class="badge badge-none">未記録</span>
    {% endif %}
    <a href="/dashboard/user/{{ user.user_id }}" class="detail-btn">詳細</a>
  </div>
</div>
{% endfor %}
{% if not users %}
<p style="color:#999;text-align:center;margin-top:40px;">まだ顧客データがありません</p>
{% endif %}
</body>
</html>
"""

DETAIL_HTML = """
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>顧客詳細</title>
<style>
body { font-family: sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }
h1 { color: #333; }
.back { display: inline-block; margin-bottom: 16px; color: #2196F3; text-decoration: none; }
.profile { display: flex; align-items: center; gap: 16px; background: white; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.avatar { width: 64px; height: 64px; border-radius: 50%; background: #e0e0e0; object-fit: cover; }
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 16px; }
.stat-box { background: white; border-radius: 12px; padding: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); text-align: center; }
.stat-label { font-size: 12px; color: #888; margin-bottom: 4px; }
.big-num { font-size: 28px; font-weight: bold; color: #333; }
.unit { font-size: 14px; color: #888; }
.summary { background: white; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.record-list { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.record-item { padding: 10px 0; border-bottom: 1px solid #f0f0f0; font-size: 14px; color: #555; }
.record-item:last-child { border-bottom: none; }
</style>
</head>
<body>
<a href="/dashboard" class="back">← 一覧に戻る</a>
<div class="profile">
  {% if data.picture_url %}
  <img class="avatar" src="{{ data.picture_url }}" alt="{{ data.display_name }}">
  {% else %}
  <div class="avatar" style="display:flex;align-items:center;justify-content:center;font-size:28px;">👤</div>
  {% endif %}
  <div>
    <h1 style="margin:0;">{{ data.display_name }}</h1>
    <p style="font-size:12px;color:#999;margin:4px 0 0;">{{ data.user_id }}</p>
  </div>
</div>
<div class="grid">
  <div class="stat-box">
    <div class="stat-label">🍽 摂取カロリー</div>
    <div class="big-num">{{ data.total_calories }}</div>
    <div class="unit">kcal</div>
  </div>
  <div class="stat-box">
    <div class="stat-label">🏃 消費カロリー</div>
    <div class="big-num">{{ data.burned_calories }}</div>
    <div class="unit">kcal</div>
  </div>
  <div class="stat-box">
    <div class="stat-label">⚡ 純カロリー</div>
    <div class="big-num">{{ data.net_calories }}</div>
    <div class="unit">kcal</div>
  </div>
</div>
{% if data.goal %}
<div class="summary">
  <h3 style="margin:0 0 12px;color:#555;">🎯 目標</h3>
  カロリー：{{ data.goal.get('calories', '-') }} kcal
  {% if data.goal.get('protein') %}／ タンパク質：{{ data.goal.get('protein') }} g{% endif %}
  {% if data.goal.get('fat') %}／ 脂質：{{ data.goal.get('fat') }} g{% endif %}
  {% if data.goal.get('carbs') %}／ 炭水化物：{{ data.goal.get('carbs') }} g{% endif %}
</div>
{% endif %}
<div class="record-list">
  <h3 style="margin:0 0 12px;color:#555;">📋 今日の記録</h3>
  {% for meal in data.meals %}
  <div class="record-item">🍽 {{ meal.dish }}（{{ meal.calories }} kcal / タンパク質{{ meal.protein }}g / 脂質{{ meal.fat }}g / 炭水化物{{ meal.carbs }}g）</div>
  {% endfor %}
  {% for ex in data.exercises %}
  <div class="record-item">🏃 {{ ex.exercise }}（消費{{ ex.burned_calories }} kcal）</div>
  {% endfor %}
  {% if not data.meals and not data.exercises %}
  <p style="color:#999;text-align:center;">今日はまだ記録がありません</p>
  {% endif %}
</div>
</body>
</html>
"""

def init_dashboard(app):
    db = firestore.client()
    app.secret_key = os.environ.get("SECRET_KEY", "salus-secret-2024")

    def get_all_users():
        users = []
        now = datetime.now(JST)
        date_str = now.strftime("%Y-%m-%d")
        user_docs = db.collection("users").stream()
        for doc in user_docs:
            user_id = doc.id
            profile = doc.to_dict()
            goal_doc = db.collection("goals").document(user_id).get()
            goal = goal_doc.to_dict() if goal_doc.exists else {}
            meals = list(db.collection("meals").document(user_id).collection(date_str).stream())
            exercises = list(db.collection("exercises").document(user_id).collection(date_str).stream())
            total_calories = sum(m.to_dict().get("calories", 0) for m in meals)
            burned_calories = sum(e.to_dict().get("burned_calories", 0) for e in exercises)
            net_calories = total_calories - burned_calories
            goal_calories = goal.get("calories", 0)
            percent = int(net_calories / goal_calories * 100) if goal_calories > 0 else 0
            has_record = len(meals) > 0 or len(exercises) > 0
            users.append({
                "user_id": user_id,
                "display_name": profile.get("display_name", "不明"),
                "picture_url": profile.get("picture_url", ""),
                "total_calories": total_calories,
                "burned_calories": burned_calories,
                "net_calories": net_calories,
                "goal_calories": goal_calories,
                "percent": percent,
                "has_record": has_record
            })
        return users

    def get_user_detail(user_id):
        now = datetime.now(JST)
        date_str = now.strftime("%Y-%m-%d")
        profile_doc = db.collection("users").document(user_id).get()
        profile = profile_doc.to_dict() if profile_doc.exists else {}
        meals = [doc.to_dict() for doc in db.collection("meals").document(user_id).collection(date_str).order_by("timestamp").stream()]
        exercises = [doc.to_dict() for doc in db.collection("exercises").document(user_id).collection(date_str).order_by("timestamp").stream()]
        goal_doc = db.collection("goals").document(user_id).get()
        goal = goal_doc.to_dict() if goal_doc.exists else {}
        total_calories = sum(m.get("calories", 0) for m in meals)
        burned_calories = sum(e.get("burned_calories", 0) for e in exercises)
        net_calories = total_calories - burned_calories
        return {
            "user_id": user_id,
            "display_name": profile.get("display_name", "不明"),
            "picture_url": profile.get("picture_url", ""),
            "meals": meals,
            "exercises": exercises,
            "goal": goal,
            "total_calories": total_calories,
            "burned_calories": burned_calories,
            "net_calories": net_calories
        }

    @app.route("/dashboard/login", methods=["GET", "POST"])
    def dashboard_login():
        if request.method == "POST":
            if request.form.get("password") == DASHBOARD_PASSWORD:
                session["logged_in"] = True
                return redirect("/dashboard")
            return render_template_string(LOGIN_HTML, error="パスワードが違います")
        return render_template_string(LOGIN_HTML, error=None)

    @app.route("/dashboard/logout")
    def dashboard_logout():
        session.clear()
        return redirect("/dashboard/login")

    @app.route("/dashboard")
    def dashboard():
        if not session.get("logged_in"):
            return redirect("/dashboard/login")
        users = get_all_users()
        now = datetime.now(JST)
        date_str = now.strftime("%Y年%m月%d日")
        return render_template_string(DASHBOARD_HTML, users=users, date=date_str)

    @app.route("/dashboard/user/<user_id>")
    def dashboard_user(user_id):
        if not session.get("logged_in"):
            return redirect("/dashboard/login")
        data = get_user_detail(user_id)
        return render_template_string(DETAIL_HTML, data=data)
