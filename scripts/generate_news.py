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
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-4b:free")
TRANSLATE_BATCH_SIZE = 4

BOARDS = {
    "ai": "AI 大模型",
    "3dgs": "3DGS",
    "embodied": "具身智能",
    "company": "产品与公司",
}

SOURCES = [
    ("OpenAI Blog", "ai", "https://openai.com/news/rss.xml"),
    ("Google DeepMind", "ai", "https://deepmind.google/blog/rss.xml"),
    ("Google AI", "ai", "https://blog.google/technology/ai/rss/"),
    ("Hugging Face Blog", "ai", "https://huggingface.co/blog/feed.xml"),
    ("arXiv cs.AI", "ai", "https://export.arxiv.org/rss/cs.AI"),
    ("arXiv cs.CL", "ai", "https://export.arxiv.org/rss/cs.CL"),
    ("arXiv cs.CV", "3dgs", "https://export.arxiv.org/rss/cs.CV"),
    ("arXiv cs.RO", "embodied", "https://export.arxiv.org/rss/cs.RO"),
    ("TechCrunch", "company", "https://techcrunch.com/feed/"),
    ("The Verge", "company", "https://www.theverge.com/rss/index.xml"),
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
}


@dataclass
class FeedItem:
    title: str
    link: str
    source: str
    board: str
    published: str
    summary_raw: str


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


def parse_feed(content: bytes, source: str, default_board: str) -> list[FeedItem]:
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
            items.append(FeedItem(title, link, source, board, published, summary))

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
            items.append(FeedItem(title, link, source, board, published, summary))

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
    score += min(3, sum(1 for kw in KEYWORDS.get(item.board, []) if kw in text))
    if any(kw in text for kw in ["openai", "anthropic", "deepmind", "google", "nvidia"]):
        score += 1
    if item.source.startswith("arXiv"):
        score -= 1
    return max(1, min(10, score))


def make_summary(item: FeedItem) -> str:
    summary = item.summary_raw or item.title
    summary = clean_text(summary)
    if len(summary) > 170:
        summary = summary[:167].rstrip() + "..."
    return summary


def item_id(link: str) -> str:
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]


def extract_json_object(text: str) -> Optional[dict]:
    decoder = json.JSONDecoder()
    value = text or ""
    for idx, char in enumerate(value):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(value[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def openrouter_chat(api_key: str, prompt: str) -> str:
    body = {
        "model": OPENROUTER_MODEL,
        "temperature": 0.2,
        "max_tokens": 2500,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "You output valid JSON only. Do not include explanations, code fences, or reasoning text.",
            },
            {"role": "user", "content": prompt},
        ],
    }
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://nightcatki.github.io/tech-news/",
            "X-Title": "Tech News Workbench",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"]


def translate_prompt(cards: list[dict]) -> str:
    items = [
        {
            "id": card["id"],
            "title": card["title"],
            "source": card["source"],
            "summary": (card.get("summary_raw") or card.get("summary") or "")[:600],
        }
        for card in cards
    ]
    return f"""你是科技新闻编辑。请把下面的新闻批量处理成中文，并只输出严格 JSON，不要 Markdown 代码块。

输出格式：
{{"items":[{{"id":"原 id","title_zh":"中文标题（如原文已是中文则原样保留）","summary":"100字以内的中文摘要，讲清发生了什么、为什么重要","score":1到10的重要性评分}}]}}

要求：
- 每条输入都必须按原 id 返回一条结果。
- summary 使用中文，避免机器翻译腔。
- score 只填数字，面向关注 AI 大模型、3DGS、具身智能的读者评分。

输入新闻：
{json.dumps(items, ensure_ascii=False, indent=2)}"""


def translate_cards(cards: list[dict]) -> None:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print("OPENROUTER_API_KEY is not set; keeping source-language summaries.")
        return
    print(f"Translating with OpenRouter model {OPENROUTER_MODEL}.")

    translated_count = 0
    for start in range(0, len(cards), TRANSLATE_BATCH_SIZE):
        batch = cards[start : start + TRANSLATE_BATCH_SIZE]
        by_id = {card["id"]: card for card in batch}
        try:
            content = openrouter_chat(api_key, translate_prompt(batch))
            translated = extract_json_object(content)
            if not translated or not isinstance(translated.get("items"), list):
                raise ValueError("model did not return items JSON")
        except (KeyError, ValueError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            print(f"warning: failed to translate batch {start + 1}: {exc}", file=sys.stderr)
            continue

        for item in translated["items"]:
            try:
                card = by_id[str(item.get("id", ""))]
                card["title_zh"] = clean_text(str(item.get("title_zh") or card["title"]))
                card["summary"] = clean_text(str(item.get("summary") or card["summary"]))
                card["score"] = max(1, min(10, int(float(item.get("score") or card["score"]))))
                card["lang"] = "zh"
                card["ai"] = True
                translated_count += 1
            except (KeyError, TypeError, ValueError) as exc:
                print(f"warning: skipped translated item: {exc}", file=sys.stderr)
    print(f"translated {translated_count}/{len(cards)} items")


def collect_items(limit: int) -> list[FeedItem]:
    collected: list[FeedItem] = []
    seen: set[str] = set()
    for source, board, url in SOURCES:
        try:
            parsed = parse_feed(fetch_url(url), source, board)
        except (ET.ParseError, urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"warning: failed to fetch {source}: {exc}", file=sys.stderr)
            continue
        for item in parsed[:12]:
            key = item.link.split("?")[0]
            if key in seen:
                continue
            seen.add(key)
            collected.append(item)

    collected.sort(key=lambda item: (score_item(item), item.published), reverse=True)
    return collected[:limit]


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
            "summary_raw": item.summary_raw,
            "score": score_item(item),
            "published": item.published,
            "link": item.link,
            "lang": "en",
            "ai": False,
        }
        for item in items
    ]
    translate_cards(cards)
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
