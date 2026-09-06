"""
2026-09分の月次バッチ記事に使う説明図を、まとめて生成する。
diagram_helpers.py（同梱フォント使用）を使うため、Windows・クラウド（Linux）どちらでも同じ見た目になる。

実行方法:
    pip install matplotlib
    python note_system/scripts/generate_all_diagrams.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from diagram_helpers import (
    two_panel_compare, three_panel_compare, bidirectional_pair, timeline, save,
    BLUE, BLUE_BG, ORANGE, ORANGE_BG, GREEN, GREEN_BG,
)
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

# 1) 冷え：交感神経 vs 副交感神経と血管
fig = two_panel_compare(
    "緊張状態が続くと、手足の血管はどうなるか",
    {"color": BLUE, "bg": BLUE_BG, "heading": "交感神経が優位", "sub": "（緊張・ストレス状態が続く）",
     "bar_width": 0.15, "bottom_label": "血管が収縮 → 血流が減る"},
    {"color": ORANGE, "bg": ORANGE_BG, "heading": "副交感神経が優位", "sub": "（リラックスできている）",
     "bar_width": 1.0, "bottom_label": "血管が拡張 → 血流が増える"},
)
save(fig, "hie_kekkan_diagram.png")

# 2) 冷え：1日のタイムライン
fig = timeline(
    "1日のうち、緊張をオフにするタイミングを作れているか",
    [(1.4, "起床"), (3.3, "昼食10分\n休む"), (5.2, "1時間に1回\n立って動く"),
     (7.1, "就寝3h前に\n運動を終える"), (8.9, "就寝")],
    footer="オレンジの点が「体を緩める」意識づけのタイミング。回数を増やすほど、緊張の固定化を防ぎやすくなります。",
)
save(fig, "hie_timeline_diagram.png")

# 3) 運動疲労：交感神経の高さの推移（line chart、helperを使わず直接描画）
fig, ax = plt.subplots(figsize=(8, 4.3), dpi=200)
ax.axis("off")
fig.patch.set_facecolor("white")
from diagram_helpers import BOLD, REG
ax.set_xlim(-0.3, 10)
ax.set_ylim(-0.9, 6)
ax.text(5, 5.7, "トレーニング後、交感神経はいつ落ち着くか", ha="center", fontproperties=BOLD, fontsize=14, color="#2b2b2b")
x = [0.8, 2.5, 4.2, 6.2, 8.5]
y_push = [1.0, 4.6, 5.2, 5.0, 4.6]
y_care = [1.0, 4.6, 5.2, 2.3, 1.3]
ax.plot(x, y_push, color=BLUE, linewidth=3, solid_capstyle="round")
ax.plot(x, y_care, color=ORANGE, linewidth=3, solid_capstyle="round")
for xi, yi in zip(x, y_push):
    ax.scatter([xi], [yi], color=BLUE, s=28, zorder=5)
for xi, yi in zip(x, y_care):
    ax.scatter([xi], [yi], color=ORANGE, s=28, zorder=5)
ax.text(8.7, 4.6, "追い込むだけ\n（クールダウン無し）", fontproperties=REG, fontsize=9.5, color=BLUE, va="center")
ax.text(8.7, 1.1, "緩める時間を追加\n（呼吸・筋膜リリース）", fontproperties=REG, fontsize=9.5, color=ORANGE, va="center")
for xi, label in zip(x, ["開始前", "トレーニング中", "追い込み後", "1時間後", "翌朝"]):
    ax.text(xi, -0.35, label, ha="center", fontproperties=REG, fontsize=9, color="#555555")
ax.annotate("", xy=(0.3, 0.5), xytext=(0.3, 5.6), arrowprops=dict(arrowstyle="-|>", color="#999999", lw=1))
ax.text(0.05, 5.6, "交感神経\nの高さ", fontproperties=REG, fontsize=8.5, color="#777777", ha="left", va="top")
save(fig, "undou_diagram.png")

# 4) むくみ：3タイプ比較
fig = three_panel_compare(
    "むくみの3タイプ",
    [
        {"color": BLUE, "bg": BLUE_BG, "tag": "タイプ1", "heading": "夕方型", "desc": "同じ姿勢が続く\n筋肉ポンプの低下"},
        {"color": GREEN, "bg": GREEN_BG, "tag": "タイプ2", "heading": "朝型", "desc": "睡眠の質・\n夜間の巡りの停滞"},
        {"color": ORANGE, "bg": ORANGE_BG, "tag": "タイプ3", "heading": "ストレス・緊張型", "desc": "交感神経優位が続く\n慢性的な血管収縮"},
    ],
)
save(fig, "mukumi_diagram.png")

# 5) 巻き肩：胸郭の広がり比較
fig = two_panel_compare(
    "巻き肩と良い姿勢で、胸郭の広がりはどう変わるか",
    {"color": BLUE, "bg": BLUE_BG, "heading": "巻き肩", "sub": "（胸の筋肉が縮こまる）",
     "bar_width": 0.35, "bottom_label": "呼吸が浅くなりやすい"},
    {"color": ORANGE, "bg": ORANGE_BG, "heading": "良い姿勢", "sub": "（胸が開いている）",
     "bar_width": 1.0, "bottom_label": "呼吸が深く入りやすい"},
)
save(fig, "makikata_diagram.png")

# 6) 胃腸：脳腸相関
fig = bidirectional_pair(
    "脳と腸はどちらの方向にも影響し合っている", "（脳腸相関）",
    "脳", "腸", "ストレス信号\n（脳→腸）", "腸内環境の信号\n（腸→脳）",
    footer="迷走神経を介して、双方向にやり取りされている",
)
save(fig, "ichou_diagram.png", rect=(0, 0.02, 1, 1))

# 7) イライラ：反応の閾値比較
fig = two_panel_compare(
    "反応するまでに必要な「刺激の大きさ」の違い",
    {"color": ORANGE, "bg": ORANGE_BG, "heading": "普段リラックスできている", "sub": None,
     "bar_width": 0.85, "bottom_label": "多少のことでは反応しにくい"},
    {"color": BLUE, "bg": BLUE_BG, "heading": "交感神経が優位な状態が続く", "sub": None,
     "bar_width": 0.25, "bottom_label": "些細な刺激でも反応しやすい"},
)
save(fig, "iraira_diagram.png")

print("all diagrams regenerated with bundled font")
