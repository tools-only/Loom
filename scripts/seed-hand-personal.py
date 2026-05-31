"""Seed hands/<id>/{personal/,context/} for all hands. Idempotent."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HANDS = ["market", "sentiment", "target", "position"]

PERSONAL_TEMPLATES = {
    "profile.md": (
        "# Profile\n\n"
        "_研究风格 / 视域 / 风险偏好（用户填写）。Hand 每次运行时会读取此文件。_\n\n"
        "## 偏好\n\n"
        "## 视域\n\n"
        "## 风险偏好\n"
    ),
    "sources.md": (
        "# Sources\n\n"
        "_用户信任的 KOL / 媒体 / 自定义 RSS。Hand 在评估信息源时会参考此列表。_\n\n"
        "## KOLs / Analysts\n\n"
        "## Media / News\n\n"
        "## Custom RSS / Sites\n"
    ),
    "watchlist.md": (
        "# Watchlist\n\n"
        "_关注的标的及理由。Hand 在做行业链分析时会优先对齐这里的 tickers。_\n\n"
        "| Ticker | Why |\n"
        "|--------|-----|\n"
    ),
    "themes.md": (
        "# Themes\n\n"
        "_当前关注的主题。Hand 综合分析时会优先对齐这些主题。_\n\n"
        "### 进行中\n\n"
        "### 候选\n"
    ),
    "learned-notes.md": (
        "# Learned Notes\n\n"
        "_累积散文反馈。最新在底部。读 references/loop.md 了解何时追加。_\n"
    ),
}


def seed():
    for hand_id in HANDS:
        h = ROOT / "hands" / hand_id

        personal = h / "personal"
        personal.mkdir(parents=True, exist_ok=True)
        for name, content in PERSONAL_TEMPLATES.items():
            p = personal / name
            if not p.exists():
                p.write_text(content, encoding="utf-8")
                print(f"  created {p.relative_to(ROOT)}")
            else:
                print(f"  skip    {p.relative_to(ROOT)} (exists)")

        context = h / "context"
        context.mkdir(parents=True, exist_ok=True)
        gk = context / ".gitkeep"
        if not gk.exists():
            gk.touch()
            print(f"  created {gk.relative_to(ROOT)}")

    print(f"\nDone. Seeded {len(HANDS)} hands.")


if __name__ == "__main__":
    seed()
