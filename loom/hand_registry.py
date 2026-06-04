from pathlib import Path

ROOT = Path(__file__).parent

REGISTRY = {
    "market": {
        "label": "市场研判",
        "description": "大盘 regime、板块轮动、宏观催化剂、财报、事件风险",
        "prompt": str(ROOT / "hands" / "prompts" / "market.md"),
        "anchor_id": "loom-market",
        "runtime": "sdk",
        "wiki_dir": str(ROOT.parent / "hands" / "market" / "wiki"),
        "config_schema": {
            "watched_sectors": {"type": "list", "label": "关注板块"},
            "kol_feeds": {"type": "list", "label": "KOL RSS 列表"},
            "macro_themes": {"type": "list", "label": "宏观主题"},
        },
    },
    "sentiment": {
        "label": "情绪追踪",
        "description": "情绪定位：fear/greed、AAII/NAAIM、COT、期权流",
        "prompt": str(ROOT / "hands" / "prompts" / "sentiment.md"),
        "anchor_id": "loom-sentiment",
        "runtime": "sdk",
        "wiki_dir": str(ROOT.parent / "hands" / "sentiment" / "wiki"),
        "config_schema": {
            "reddit_subs": {"type": "list", "label": "Reddit 社区"},
            "watched_tickers": {"type": "list", "label": "关注标的"},
        },
    },
    "target": {
        "label": "标的 Thesis",
        "description": "标的基本面 thesis：核心假设、失效条件、催化剂追踪",
        "prompt": str(ROOT / "hands" / "prompts" / "target.md"),
        "anchor_id": "loom-target",
        "runtime": "sdk",
        "wiki_dir": str(ROOT.parent / "hands" / "target" / "wiki"),
        "config_schema": {
            "tickers": {"type": "list", "label": "目标标的"},
            "initial_theses": {"type": "map", "label": "初始 Thesis (ticker → 文本)"},
        },
    },
    "position": {
        "label": "持仓管理",
        "description": "持仓报告：仓位、成本、P&L、敞口、集中度",
        "prompt": str(ROOT / "hands" / "prompts" / "position.md"),
        "anchor_id": "loom-position",
        "runtime": "sdk",
        "wiki_dir": str(ROOT.parent / "hands" / "position" / "wiki"),
        "config_schema": {
            "positions": {"type": "list", "label": "持仓数据"},
            "risk_profile": {"type": "str", "label": "风险偏好描述"},
        },
    },
    "canvas": {
        "label": "Canvas 协作",
        "description": "自由白板 co-design：生成、重排、连接内容卡片",
        "prompt": str(ROOT.parent / "domains" / "loom-human-ag" / "hands" / "canvas" / "CLAUDE.md"),
        "anchor_id": "canvas-root",
        "runtime": "canvas",
        "wiki_dir": str(ROOT.parent / "skills" / "canvas-codesign"),
        "config_schema": {},
    },
}
