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
.date-form { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
.date-form input { padding: 8px 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; }
.date-form button { padding: 8px 16px; background: #2196F3; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; }
.tabs { display: flex; gap: 8px; margin-bottom: 20px; }
.tab { padding: 8px 20px; border-radius: 20px; font-size: 14px; cursor: pointer; text-decoration: none; border: 1px solid #ddd; background: white; color: #555; }
.tab.active { background: #4CAF50; color: white; border-color: #4CAF50; }
.card { background: white; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.avatar { width: 48px; height: 48px; border-radius: 50%; background: #e0e0e0; object-fit: cover; flex-shrink: 0; }
.user-info { flex: 1; }
.user-name { font-size: 16px; font-weight: bold; color: #333; margin-bottom: 4px; }
.user-id { font-size: 11px; color: #bbb; margin-bottom: 6px; }
.stats { font-size: 13px; color: #555; }
.badge { padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: bold; }
.badge-good { background: #e8f5e9; color: #2e7d32; }
.badge-none { background: #f5f5f5; color: #999; }
.badge-retired { background: #ffebee; color: #c62828; }
.progress-bar { background: #eee; border-radius: 4px; height: 8px; width: 160px; margin-top: 8px; }
.progress-fill { background: #4CAF50; border-radius: 4px; height: 8px; }
.detail-btn { padding: 8px 16px; background: #2196F3; color: white; border: none; border-radius: 8px; cursor: pointer; text-decoration: none; font-size: 14px; white-space: nowrap; }
.retire-btn { padding: 6px 12px; background: #fff; color: #f44336; border: 1px solid #f44336; border-radius: 8px; cursor: pointer; font-size: 12px; text-decoration: none; white-space: nowrap; }
.restore-btn { padding: 6px 12px; background: #fff; color: #4CAF50; border: 1px solid #4CAF50; border-radius: 8px; cursor: pointer; font-size: 12px; text-decoration: none; white-space: nowrap; }
.logout { float: right; padding: 8px 16px; background: #f44336; color: white; border: none; border-radius: 8px; cursor: pointer; text-decoration: none; font-size: 14px; }
</style>
</head>
<body>
<h1>🏋️ SALUS 管理画面 <a href="/dashboard/logout" class="logout">ログアウト</a></h1>

<form class="date-form" method="get" action="/dashboard">
  <label style="font-size:14px;color:#555;">📅 日付：</label>
  <input type="date" name="date" value="{{ selected_date }}">
  <button type="submit">表示</button>
  <a href="/dashboard" style="font-size:13px;color:#2196F3;">今日に戻る</a>
</form>

<div class="tabs">
  <a href="/dashboard?date={{ selected_date }}&tab=active" class="tab {% if tab == 'active' %}active{% endif %}">アクティブ（{{ active_count }}）</a>
  <a href="/dashboard?date={{ selected_date }}&tab=retired" class="tab {% if tab == 'retired' %}active{% endif %}">退会済み（{{ retired_count }}）</a>
</div>

<p style="font-size:13px;color:#888;margin-bottom:16px;">{{ selected_date_jp }}の記録</p>

{% for user in users %}
<div class="card" {% if user.is_retired %}style="opacity:0.6;"{% endif %}>
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
    {% if user.is_retired %}
    <span class="badge badge-retired">退会済み</span>
    <a href="/dashboard/restore/{{ user.user_id }}" class="restore-btn">復帰</a>
    {% else %}
    {% if user.has_record %}
    <span class="badge badge-good">✅ 記録あり</span>
    {% else %}
    <span class="badge badge-none">未記録</span>
    {% endif %}
    <a href="/dashboard/user/{{ user.user_id }}" class="detail-btn">詳細</a>
    <a href="/dashboard/retire/{{ user.user_id }}" class="retire-btn" onclick="return confirm('{{ user.display_name }}を退会済みにしますか？')">退会</a>
    {% endif %}
  </div>
</div>
{% endfor %}
{% if not users %}
<p style="color:#999;text-align:center;margin-top:40px;">該当する顧客がいません</p>
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
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body { font-family: sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }
h1 { color: #333; }
.back { display: inline-block; margin-bottom: 16px; color: #2196F3; text-decoration: none; }
.profile { display: flex; align-items: center; gap: 16px; background: white; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.avatar { width: 64px; height: 64px; border-radius: 50%; background: #e0e0e0; object-fit: cover; }
.date-form { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.date-form input { padding: 8px 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; }
.date-form button { padding: 8px 16px; background: #2196F3; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; }
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 16px; }
.stat-box { background: white; border-radius: 12px; padding: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); text-align: center; }
.stat-label { font-size: 12px; color: #888; margin-bottom: 4px; }
.big-num { font-size: 28px; font-weight: bold; color: #333; }
.unit { font-size: 14px; color: #888; }
.summary { background: white; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.record-list { background: white; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.record-item { padding: 10px 0; border-bottom: 1px solid #f0f0f0; font-size: 14px; color: #555; }
.record-item:last-child { border-bottom: none; }
.chart-box { background: white; border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
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

<form class="date-form" method="get" action="/dashboard/user/{{ data.user_id }}">
  <label style="font-size:14px;color:#555;">📅 日付：</label>
  <input type="date" name="date" value="{{ selected_date }}">
  <button type="submit">表示</button>
  <a href="/dashboard/user/{{ data.user_id }}" style="font-size:13px;color:#2196F3;">今日に戻る</a>
</form>

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

<div class="chart-box">
  <h3 style="margin:0 0 16px;color:#555;">📈 過去7日間のカロリー推移</h3>
  <canvas id="calorieChart" height="120"></canvas>
</div>

<div class="record-list">
  <h3 style="margin:0 0 12px;color:#555;">📋 {{ selected_date }}の記録</h3>
  {% for meal in data.meals %}
  <div class="record-item">🍽 {{ meal.dish }}（{{ meal.calories }} kcal / タンパク質{{ meal.protein }}g / 脂質{{ meal.fat }}g / 炭水化物{{ meal.carbs }}g）</div>
  {% endfor %}
  {% for ex in data.exercises %}
  <div class="record-item">🏃 {{ ex.exercise }}（消費{{ ex.burned_calories }} kcal）</div>
  {% endfor %}
  {% if not data.meals and not data.exercises %}
  <p style="color:#999;text-align:center;">この日は記録がありません</p>
  {% endif %}
</div>

<script>
const labels = {{ chart_labels | tojson }};
const intakeData = {{ chart_intake | tojson }};
const burnedData = {{ chart_burned | tojson }};
const netData = {{ chart_net | tojson }};

new Chart(document.getElementById('calorieChart'), {
  type: 'line',
  data: {
    labels: labels,
    datasets: [
      { label: '摂取', data: intakeData, borderColor: '#FF7043', backgroundColor: 'rgba(255,112,67,0.1)', tension: 0.3, fill: true },
      { label: '消費', data: burnedData, borderColor: '#42A5F5', backgroundColor: 'rgba(66,165,245,0.1)', tension: 0.3, fill: true },
      { label: '純カロリー', data: netData, borderColor: '#66BB6A', backgroundColor: 'rgba(102,187,106,0.1)', tension: 0.3, fill: true }
    ]
  },
  options: {
    responsive: true,
    plugins: { legend: { position: 'top' } },
    scales: { y: { beginAtZero: true } }
  }
});
</script>
</body>
</html>
"""

def init_dashboard(app):
    db = firestore.client()
    app.secret_key = os.environ.get("SECRET_KEY", "salus-secret-2024")

    def get_all_users(date_str, tab="active"):
        users = []
        user_docs = db.collection("users").stream()
        for doc in user_docs:
            user_id = doc.id
            profile = doc.to_dict()
            is_retired = profile.get("retired", False)
            if tab == "active" and is_retired:
                continue
            if tab == "retired" and not is_retired:
                continue
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
                "has_record": has_record,
                "is_retired": is_retired
            })
        return users

    def get_user_detail(user_id, date_str):
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

    def get_chart_data(user_id):
        labels = []
        intake_data = []
        burned_data = []
        net_data = []
        now = datetime.now(JST)
        for i in range(6, -1, -1):
            d = now - timedelta(days=i)
            date_str = d.strftime("%Y-%m-%d")
            labels.append(d.strftime("%m/%d"))
            meals = list(db.collection("meals").document(user_id).collection(date_str).stream())
            exercises = list(db.collection("exercises").document(user_id).collection(date_str).stream())
            intake = sum(m.to_dict().get("calories", 0) for m in meals)
            burned = sum(e.to_dict().get("burned_calories", 0) for e in exercises)
            intake_data.append(intake)
            burned_data.append(burned)
            net_data.append(intake - burned)
        return labels, intake_data, burned_data, net_data

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
        now = datetime.now(JST)
        selected_date = request.args.get("date", now.strftime("%Y-%m-%d"))
        tab = request.args.get("tab", "active")
        all_users_active = get_all_users(selected_date, "active")
        all_users_retired = get_all_users(selected_date, "retired")
        users = get_all_users(selected_date, tab)
        try:
            d = datetime.strptime(selected_date, "%Y-%m-%d")
            selected_date_jp = d.strftime("%Y年%m月%d日")
        except:
            selected_date_jp = selected_date
        return render_template_string(DASHBOARD_HTML,
            users=users,
            selected_date=selected_date,
            selected_date_jp=selected_date_jp,
            tab=tab,
            active_count=len(all_users_active),
            retired_count=len(all_users_retired)
        )

    @app.route("/dashboard/user/<user_id>")
    def dashboard_user(user_id):
        if not session.get("logged_in"):
            return redirect("/dashboard/login")
        now = datetime.now(JST)
        selected_date = request.args.get("date", now.strftime("%Y-%m-%d"))
        data = get_user_detail(user_id, selected_date)
        labels, intake, burned, net = get_chart_data(user_id)
        return render_template_string(DETAIL_HTML,
            data=data,
            selected_date=selected_date,
            chart_labels=labels,
            chart_intake=intake,
            chart_burned=burned,
            chart_net=net
        )

    @app.route("/dashboard/retire/<user_id>")
    def dashboard_retire(user_id):
        if not session.get("logged_in"):
            return redirect("/dashboard/login")
        db.collection("users").document(user_id).update({"retired": True})
        return redirect("/dashboard")

    @app.route("/dashboard/restore/<user_id>")
    def dashboard_restore(user_id):
        if not session.get("logged_in"):
            return redirect("/dashboard/login")
        db.collection("users").document(user_id).update({"retired": False})
        return redirect("/dashboard")
