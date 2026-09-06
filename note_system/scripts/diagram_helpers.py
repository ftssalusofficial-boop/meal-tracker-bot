"""
note記事用の説明図を作るための共通ヘルパー。
ローカル（Windows）・クラウド実行環境（Linux, matplotlib+pip）の両方で同じ見た目になるよう、
リポジトリに同梱したフォント（note_system/assets/fonts/）を使う。

使い方の例は note_system/scripts/make_diagrams_batch2.py を参照。
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import FancyBboxPatch, Circle, FancyArrowPatch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", ".."))
FONT_DIR = os.path.join(_REPO_ROOT, "note_system", "assets", "fonts")
OUT_DIR = os.path.join(_REPO_ROOT, "note_system", "drafts", "images")

BOLD = fm.FontProperties(fname=os.path.join(FONT_DIR, "MPLUS1p-Bold.ttf"))
REG = fm.FontProperties(fname=os.path.join(FONT_DIR, "MPLUS1p-Regular.ttf"))

# ブランドカラー（柔らかいトーン。note記事の説明図として汎用的に使う）
BLUE = "#3f6fa8"
BLUE_BG = "#eaf0f7"
ORANGE = "#c97a3a"
ORANGE_BG = "#fbeee1"
GREEN = "#4a8f6b"
GREEN_BG = "#e8f2ec"
GRAY = "#888888"


def new_fig(w, h):
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    return fig, ax


def save(fig, filename, rect=(0, 0.04, 1, 1)):
    """filenameは note_system/drafts/images/ 直下に保存される（例: 'hoge_diagram.png'）"""
    os.makedirs(OUT_DIR, exist_ok=True)
    plt.tight_layout(rect=list(rect))
    path = os.path.join(OUT_DIR, filename)
    plt.savefig(path, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    print("saved", path)
    return path


def two_panel_compare(title, left, right, figsize=(8, 4.5)):
    """
    2つの状態を左右カードで比較する図（例：緊張時 vs リラックス時）。
    left / right は dict: {color, bg, heading, sub, bar_width(0~1の相対値), bottom_label}
    """
    fig, ax = new_fig(*figsize)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5.6)
    ax.text(5, 5.25, title, ha="center", va="center", fontproperties=BOLD, fontsize=14, color="#2b2b2b")

    def _panel(x0, spec):
        ax.add_patch(FancyBboxPatch((x0, 0.4), 4.3, 4.3, boxstyle="round,pad=0.05,rounding_size=0.18",
                                     linewidth=0, facecolor=spec["bg"]))
        ax.text(x0 + 2.15, 4.3, spec["heading"], ha="center", va="center",
                fontproperties=BOLD, fontsize=13, color=spec["color"])
        if spec.get("sub"):
            ax.text(x0 + 2.15, 3.85, spec["sub"], ha="center", va="center",
                    fontproperties=REG, fontsize=10.5, color="#555555")
        bar_w = 0.5 + 2.5 * spec.get("bar_width", 0.5)
        ax.add_patch(FancyBboxPatch((x0 + 2.15 - bar_w / 2, 1.9), bar_w, 1.0,
                                     boxstyle="round,pad=0,rounding_size=0.3",
                                     linewidth=0, facecolor=spec["color"], alpha=0.85))
        if spec.get("bottom_label"):
            ax.text(x0 + 2.15, 1.2, spec["bottom_label"], ha="center", va="center",
                    fontproperties=REG, fontsize=10, color=spec["color"])

    _panel(0.3, left)
    _panel(5.4, right)
    return fig


def three_panel_compare(title, panels, figsize=(9.5, 4.6)):
    """panelsは3件のdict: {color, bg, tag(タイプ1等), heading, desc}"""
    fig, ax = new_fig(*figsize)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 5)
    ax.text(6, 4.7, title, ha="center", fontproperties=BOLD, fontsize=15, color="#2b2b2b")
    xs = [0.3, 4.15, 8.0]
    for x0, spec in zip(xs, panels):
        ax.add_patch(FancyBboxPatch((x0, 0.5), 3.7, 3.7, boxstyle="round,pad=0.05,rounding_size=0.18",
                                     linewidth=0, facecolor=spec["bg"]))
        if spec.get("tag"):
            ax.text(x0 + 1.85, 3.65, spec["tag"], ha="center", fontproperties=REG, fontsize=10, color=spec["color"])
        ax.text(x0 + 1.85, 3.15, spec["heading"], ha="center", fontproperties=BOLD, fontsize=13.5, color=spec["color"])
        ax.add_patch(Circle((x0 + 1.85, 2.05), 0.55, facecolor=spec["color"], alpha=0.85))
        ax.text(x0 + 1.85, 1.05, spec["desc"], ha="center", va="top", fontproperties=REG, fontsize=9.3, color="#555555")
    return fig


def bidirectional_pair(title, subtitle, top_label, bottom_label, left_arrow_label, right_arrow_label,
                        top_color=BLUE, bottom_color=ORANGE, footer=None, figsize=(7, 5.2)):
    fig, ax = new_fig(*figsize)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.text(5, 9.4, title, ha="center", fontproperties=BOLD, fontsize=13.5, color="#2b2b2b")
    if subtitle:
        ax.text(5, 8.8, subtitle, ha="center", fontproperties=REG, fontsize=10.5, color="#777777")

    ax.add_patch(Circle((5, 7.1), 1.15, facecolor=top_color, alpha=0.9))
    ax.text(5, 7.1, top_label, ha="center", va="center", fontproperties=BOLD, fontsize=16, color="white")
    ax.add_patch(Circle((5, 2.3), 1.15, facecolor=bottom_color, alpha=0.9))
    ax.text(5, 2.3, bottom_label, ha="center", va="center", fontproperties=BOLD, fontsize=16, color="white")

    ax.add_patch(FancyArrowPatch((4.3, 5.95), (4.3, 3.45), arrowstyle="-|>", mutation_scale=18,
                                  color=top_color, linewidth=2.5, connectionstyle="arc3,rad=0.15"))
    ax.add_patch(FancyArrowPatch((5.7, 3.45), (5.7, 5.95), arrowstyle="-|>", mutation_scale=18,
                                  color=bottom_color, linewidth=2.5, connectionstyle="arc3,rad=0.15"))
    ax.text(3.0, 4.7, left_arrow_label, ha="center", fontproperties=REG, fontsize=9.5, color=top_color)
    ax.text(7.1, 4.7, right_arrow_label, ha="center", fontproperties=REG, fontsize=9.5, color=bottom_color)
    if footer:
        ax.text(5, 0.55, footer, ha="center", fontproperties=REG, fontsize=9, color="#888888")
    return fig


def timeline(title, points, footer=None, figsize=(8, 3.6)):
    """points: [(x_0to10, label), ...] 5点前後を推奨"""
    fig, ax = new_fig(*figsize)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 4.2)
    ax.text(5, 3.9, title, ha="center", fontproperties=BOLD, fontsize=13.5, color="#2b2b2b")
    ax.add_patch(FancyBboxPatch((0.6, 1.75), 8.8, 0.35, boxstyle="round,pad=0,rounding_size=0.17",
                                 linewidth=0, facecolor="#e3e3e3"))
    for x, label in points:
        ax.add_patch(Circle((x, 1.925), 0.16, facecolor=ORANGE, edgecolor="white", linewidth=1.5, zorder=5))
        ax.text(x, 1.15, label, ha="center", va="top", fontproperties=REG, fontsize=9, color="#444444")
    if footer:
        fig.text(0.5, 0.03, footer, ha="center", fontproperties=REG, fontsize=8, color="#888888")
    return fig
