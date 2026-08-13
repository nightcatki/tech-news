#!/usr/bin/env python3
"""Generate daily news JSON for the static PWA.

The script intentionally uses only Python's standard library so it can run in
GitHub Actions without dependency installation.
"""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TZ = timezone(timedelta(hours=8), "Asia/Shanghai")

BOARDS = {
    "ai": "AI 大模型",
    "3dgs": "3DGS",
    "embodied": "具身智能",
    "company": "产品与公司",
    "dev": "开发者工具",
    "infra": "算力与云",
    "security": "安全漏洞",
}

SOURCE_TIER_SCORE = {
    "primary": 3,
    "research": 1,
    "advisory": 2,
    "media": -2,
}

SOURCES = [
    # A tier: official announcements, changelogs, and first-party research.
    ("OpenAI News", "ai", "https://openai.com/news/rss.xml", "primary", 12),
    ("Google DeepMind", "ai", "https://deepmind.google/blog/rss.xml", "primary", 10),
    ("Google AI", "ai", "https://blog.google/technology/ai/rss/", "primary", 10),
    ("Hugging Face Blog", "ai", "https://huggingface.co/blog/feed.xml", "primary", 8),
    ("NVIDIA Blog", "infra", "https://blogs.nvidia.com/feed/", "primary", 8),
    ("NVIDIA Developer", "infra", "https://developer.nvidia.com/blog/feed/", "primary", 8),
    ("GitHub Changelog", "dev", "https://github.blog/changelog/feed/", "primary", 10),
    ("AWS News Blog", "infra", "https://aws.amazon.com/blogs/aws/feed/", "primary", 8),
    ("Microsoft Dev Blogs", "dev", "https://devblogs.microsoft.com/feed/", "primary", 8),
    ("GitHub Security Blog", "security", "https://github.blog/security/feed/", "primary", 8),
    ("CISA Advisories", "security", "https://www.cisa.gov/cybersecurity-advisories/all.xml", "advisory", 8),
    # B tier: useful research feeds, but noisier than official announcements.
    ("arXiv cs.AI", "ai", "https://export.arxiv.org/rss/cs.AI", "research", 6),
    ("arXiv cs.CL", "ai", "https://export.arxiv.org/rss/cs.CL", "research", 6),
    ("arXiv cs.CV", "3dgs", "https://export.arxiv.org/rss/cs.CV", "research", 6),
    ("arXiv cs.RO", "embodied", "https://export.arxiv.org/rss/cs.RO", "research", 6),
    # C tier: media is kept only as a backup signal.
    ("TechCrunch", "company", "https://techcrunch.com/feed/", "media", 4),
    ("The Verge", "company", "https://www.theverge.com/rss/index.xml", "media", 4),
]

KEYWORDS = {
    "ai": [
        "ai",
        "agent",
        "anthropic",
        "chatgpt",
        "claude",
        "deepseek",
        "gemini",
        "gpt",
        "llama",
        "model",
        "openai",
        "reasoning",
        "transformer",
    ],
    "3dgs": [
        "3d gaussian",
        "3dgs",
        "gaussian splatting",
        "nerf",
        "reconstruction",
        "scene reconstruction",
        "splatting",
        "view synthesis",
    ],
    "embodied": [
        "embodied",
        "humanoid",
        "manipulation",
        "robot",
        "robotics",
        "sim2real",
        "unitree",
        "vision-language-action",
        "vla",
    ],
    "company": [
        "acquires",
        "announces",
        "funding",
        "launch",
        "product",
        "raises",
        "release",
        "startup",
    ],
    "dev": [
        "api",
        "changelog",
        "cli",
        "codex",
        "copilot",
        "developer",
        "github",
        "release",
        "sdk",
        "typescript",
    ],
    "infra": [
        "aws",
        "azure",
        "cloud",
        "cuda",
        "gpu",
        "inference",
        "nvidia",
        "training",
    ],
    "security": [
        "advisory",
        "attack",
        "breach",
        "cisa",
        "cve",
        "exploit",
        "malware",
        "patch",
        "security",
        "vulnerability",
    ],
}

IMPORTANT_TERMS = [
    "announces",
    "available",
    "breakthrough",
    "changelog",
    "critical",
    "cve",
    "developer preview",
    "general availability",
    "introducing",
    "launch",
    "new model",
    "open source",
    "preview",
    "release",
    "research",
    "security",
]

LOW_SIGNAL_TERMS = [
    "best ceo",
    "ceo tops",
    "deal",
    "discount",
    "glassdoor",
    "hands-on",
    "opinion",
    "ranked",
    "rumor",
    "sale",
    "some users",
    "trailer",
]


@dataclass
class FeedItem:
    title: str
    link: str
    source: str
    board: str
    published: str
    summary_raw: str
    tier: str


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def fetch_url(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "tech-news-workbench/1.0 (+https://github.com/nightcatki/tech-news)"
        },
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read()


def parse_date(value: str) -> str:
    if not value:
        return datetime.now(TZ).isoformat(timespec="seconds")
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return datetime.now(TZ).isoformat(timespec="seconds")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ).isoformat(timespec="seconds")


def child_text(node: ET.Element, names: Iterable[str]) -> str:
    for name in names:
        found = node.find(name)
        if found is not None and found.text:
            return found.text
    return ""


def atom_link(node: ET.Element) -> str:
    link = node.find("{http://www.w3.org/2005/Atom}link")
    if link is not None:
        return link.attrib.get("href", "")
    return ""


def parse_feed(content: bytes, source: str, default_board: str, tier: str) -> list[FeedItem]:
    root = ET.fromstring(content)
    items: list[FeedItem] = []

    rss_items = root.findall(".//item")
    atom_items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for item in rss_items:
        title = clean_text(child_text(item, ["title"]))
        link = clean_text(child_text(item, ["link", "guid"]))
        summary = clean_text(child_text(item, ["description", "summary"]))
        published = parse_date(child_text(item, ["pubDate", "published", "updated"]))
        if title and link:
            board = classify(title + " " + summary, default_board)
            items.append(FeedItem(title, link, source, board, published, summary, tier))

    for item in atom_items:
        title = clean_text(child_text(item, ["{http://www.w3.org/2005/Atom}title"]))
        link = atom_link(item)
        summary = clean_text(
            child_text(
                item,
                [
                    "{http://www.w3.org/2005/Atom}summary",
                    "{http://www.w3.org/2005/Atom}content",
                ],
            )
        )
        published = parse_date(
            child_text(
                item,
                [
                    "{http://www.w3.org/2005/Atom}published",
                    "{http://www.w3.org/2005/Atom}updated",
                ],
            )
        )
        if title and link:
            board = classify(title + " " + summary, default_board)
            items.append(FeedItem(title, link, source, board, published, summary, tier))

    return items


def classify(text: str, fallback: str) -> str:
    lowered = text.lower()
    scores = {
        board: sum(1 for keyword in keywords if keyword in lowered)
        for board, keywords in KEYWORDS.items()
    }
    board, score = max(scores.items(), key=lambda pair: pair[1])
    return board if score else fallback


def score_item(item: FeedItem) -> int:
    text = f"{item.title} {item.summary_raw}".lower()
    score = 5
    score += SOURCE_TIER_SCORE.get(item.tier, 0)
    score += min(3, sum(1 for kw in KEYWORDS.get(item.board, []) if kw in text))
    score += min(2, sum(1 for term in IMPORTANT_TERMS if term in text))
    if any(kw in text for kw in ["openai", "anthropic", "claude", "deepmind", "google", "nvidia"]):
        score += 1 if item.tier != "media" else 0
    if any(term in text for term in LOW_SIGNAL_TERMS):
        score -= 2
    if item.source == "NVIDIA Blog" and any(term in text for term in ["ceo", "glassdoor"]):
        score -= 4
    if item.tier == "research":
        score -= 1
    return max(1, min(10, score))


def make_summary(item: FeedItem) -> str:
    summary = item.summary_raw or item.title
    summary = clean_text(summary)
    if len(summary) > 170:
        summary = summary[:167].rstrip() + "..."
    return summary


def make_detail(item: FeedItem) -> str:
    if score_item(item) < 8:
        return ""
    detail = clean_text(item.summary_raw or item.title)
    if not detail:
        return ""
    if len(detail) > 420:
        detail = detail[:417].rstrip() + "..."
    return detail


def item_id(link: str) -> str:
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]


def collect_items(limit: int) -> list[FeedItem]:
    collected: list[FeedItem] = []
    seen: set[str] = set()
    for source, board, url, tier, per_feed_limit in SOURCES:
        try:
            parsed = parse_feed(fetch_url(url), source, board, tier)
        except (ET.ParseError, urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"warning: failed to fetch {source}: {exc}", file=sys.stderr)
            continue
        for item in parsed[:per_feed_limit]:
            key = item.link.split("?")[0]
            if key in seen:
                continue
            seen.add(key)
            collected.append(item)

    collected.sort(key=lambda item: (score_item(item), item.published), reverse=True)
    selected: list[FeedItem] = []
    source_counts: dict[str, int] = {}
    tier_counts: dict[str, int] = {}
    tier_caps = {"media": 3, "research": 7}
    source_caps = {
        "NVIDIA Developer": 3,
        "NVIDIA Blog": 2,
        "GitHub Changelog": 4,
    }

    for item in collected:
        if source_counts.get(item.source, 0) >= source_caps.get(item.source, 5):
            continue
        if tier_counts.get(item.tier, 0) >= tier_caps.get(item.tier, limit):
            continue
        selected.append(item)
        source_counts[item.source] = source_counts.get(item.source, 0) + 1
        tier_counts[item.tier] = tier_counts.get(item.tier, 0) + 1
        if len(selected) >= limit:
            break

    return selected


def build_payload(items: list[FeedItem], now: datetime) -> dict:
    date = now.date().isoformat()
    cards = [
        {
            "id": item_id(item.link),
            "board": item.board,
            "source": item.source,
            "title": item.title,
            "title_zh": item.title,
            "summary": make_summary(item),
            "detail": make_detail(item),
            "summary_raw": item.summary_raw,
            "score": score_item(item),
            "tier": item.tier,
            "published": item.published,
            "link": item.link,
            "lang": "en",
            "ai": False,
        }
        for item in items
    ]
    top_titles = "；".join(card["title_zh"] for card in cards[:3])
    digest = (
        f"今日抓取到 {len(cards)} 条科技新闻。重点关注：{top_titles}。"
        if cards
        else "今日暂未抓取到可展示的新闻，请稍后查看下一次自动更新。"
    )
    return {
        "date": date,
        "generated_at": now.isoformat(timespec="seconds"),
        "digest": digest,
        "boards": BOARDS,
        "items": cards,
        "policies": [],
    }


def update_date_index(date: str) -> None:
    index_path = DATA_DIR / "index.json"
    try:
        dates = json.loads(index_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        dates = []
    dates = [d for d in dates if d != "latest"]
    if date not in dates:
        dates.append(date)
    dates = sorted(dates)[-45:]
    index_path.write_text(
        json.dumps(dates, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=24)
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    now = datetime.now(TZ)
    payload = build_payload(collect_items(args.limit), now)
    date = payload["date"]

    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    (DATA_DIR / f"{date}.json").write_text(text, encoding="utf-8")
    (DATA_DIR / "latest.json").write_text(text, encoding="utf-8")
    update_date_index(date)
    print(f"generated data for {date}: {len(payload['items'])} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
