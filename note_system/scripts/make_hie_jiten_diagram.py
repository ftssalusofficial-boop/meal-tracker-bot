import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from diagram_helpers import BOLD, REG, BLUE, BLUE_BG, ORANGE, ORANGE_BG, OUT_DIR


def draw_snowflake(ax, cx, cy, r, color, lw=3.5):
    for angle in range(0, 180, 30):
        import math
        rad = math.radians(angle)
        dx, dy = r * math.cos(rad), r * math.sin(rad)
        ax.plot([cx - dx, cx + dx], [cy - dy, cy + dy], color=color, linewidth=lw, solid_capstyle="round")


def draw_sun(ax, cx, cy, r, color, lw=3.5):
    import math
    circle = plt.Circle((cx, cy), r * 0.55, facecolor=color, edgecolor="none", zorder=5)
    ax.add_patch(circle)
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        x1, y1 = cx + r * 0.72 * math.cos(rad), cy + r * 0.72 * math.sin(rad)
        x2, y2 = cx + r * 1.05 * math.cos(rad), cy + r * 1.05 * math.sin(rad)
        ax.plot([x1, x2], [y1, y2], color=color, linewidth=lw, solid_capstyle="round")


fig, ax = plt.subplots(figsize=(8.5, 4.6), dpi=200)
ax.axis("off")
fig.patch.set_facecolor("white")
ax.set_xlim(0, 10)
ax.set_ylim(0, 5.8)

ax.text(5, 5.45, "緊張が続く体と、休めている体では", ha="center", fontproperties=BOLD, fontsize=16, color="#232323")
ax.text(5, 4.95, "手足の血流がこう変わります", ha="center", fontproperties=BOLD, fontsize=16, color="#232323")

# Left panel : tense / cold
ax.add_patch(FancyBboxPatch((0.4, 0.4), 4.3, 4.0, boxstyle="round,pad=0.06,rounding_size=0.22",
                             linewidth=2, edgecolor=BLUE, facecolor=BLUE_BG))
draw_snowflake(ax, 2.55, 3.55, 0.62, BLUE)
ax.text(2.55, 2.55, "交感神経が優位", ha="center", fontproperties=BOLD, fontsize=14.5, color=BLUE)
ax.text(2.55, 2.1, "（緊張・ストレスが続く）", ha="center", fontproperties=REG, fontsize=10.5, color="#555555")
ax.add_patch(FancyBboxPatch((1.35, 1.05), 2.4, 0.55, boxstyle="round,pad=0,rounding_size=0.27",
                             linewidth=0, facecolor=BLUE, alpha=0.18))
ax.text(2.55, 1.32, "血管が収縮 → 冷える", ha="center", fontproperties=BOLD, fontsize=11.5, color=BLUE)

# Right panel : relaxed / warm
ax.add_patch(FancyBboxPatch((5.3, 0.4), 4.3, 4.0, boxstyle="round,pad=0.06,rounding_size=0.22",
                             linewidth=2, edgecolor=ORANGE, facecolor=ORANGE_BG))
draw_sun(ax, 7.45, 3.55, 0.55, ORANGE)
ax.text(7.45, 2.55, "副交感神経が優位", ha="center", fontproperties=BOLD, fontsize=14.5, color=ORANGE)
ax.text(7.45, 2.1, "（休めている・リラックス）", ha="center", fontproperties=REG, fontsize=10.5, color="#555555")
ax.add_patch(FancyBboxPatch((6.25, 1.05), 2.4, 0.55, boxstyle="round,pad=0,rounding_size=0.27",
                             linewidth=0, facecolor=ORANGE, alpha=0.2))
ax.text(7.45, 1.32, "血管が拡張 → 温まる", ha="center", fontproperties=BOLD, fontsize=11.5, color=ORANGE)

arrow = FancyArrowPatch((4.75, 2.4), (5.25, 2.4), arrowstyle="-|>", mutation_scale=22,
                         color="#aaaaaa", linewidth=2.5)
ax.add_patch(arrow)

plt.tight_layout()
path = os.path.join(OUT_DIR, "hie_jiten_diagram.png")
plt.savefig(path, facecolor="white", bbox_inches="tight")
print("saved", path)
