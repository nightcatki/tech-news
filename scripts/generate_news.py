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
    ("NVIDIA Blog", "ai", "https://blogs.nvidia.com/feed/", "primary", 8),
    ("NVIDIA Developer", "ai", "https://developer.nvidia.com/blog/feed/", "primary", 8),
    ("GitHub Changelog", "company", "https://github.blog/changelog/feed/", "primary", 10),
    ("AWS News Blog", "company", "https://aws.amazon.com/blogs/aws/feed/", "primary", 8),
    ("Microsoft Dev Blogs", "company", "https://devblogs.microsoft.com/feed/", "primary", 8),
    ("GitHub Security Blog", "company", "https://github.blog/security/feed/", "primary", 8),
    ("CISA Advisories", "company", "https://www.cisa.gov/cybersecurity-advisories/all.xml", "advisory", 8),
    # B tier: useful research feeds, but noisier than official announcements.
    ("arXiv cs.AI", "ai", "https://export.arxiv.org/rss/cs.AI", "research", 6),
    ("arXiv cs.CL", "ai", "https://export.arxiv.org/rss/cs.CL", "research", 6),
    ("arXiv cs.CV", "3dgs", "https://export.arxiv.org/rss/cs.CV", "research", 6),
    ("arXiv cs.RO", "embodied", "https://export.arxiv.org/rss/cs.RO", "research", 6),
    # C tier: media is kept only as a backup signal.
    ("TechCrunch", "company", "https://techcrunch.com/feed/", "media", 4),
    ("The Verge", "company", "https://www.theverge.com/rss/index.xml", "media", 4),
]

POLICY_RSS_SOURCES = [
    ("White House Presidential Actions", "https://www.whitehouse.gov/presidential-actions/feed/"),
    ("NIST Information Technology", "https://www.nist.gov/news-events/information%20technology/rss.xml"),
]

FEDERAL_REGISTER_URL = (
    "https://www.federalregister.gov/api/v1/documents.json"
    "?per_page=20&order=newest&conditions%5Bterm%5D=artificial%20intelligence"
)

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

SIGNAL_KEYWORDS = [
    "api",
    "aws",
    "azure",
    "changelog",
    "cli",
    "cloud",
    "codex",
    "copilot",
    "cuda",
    "developer",
    "github",
    "gpu",
    "inference",
    "nvidia",
    "sdk",
    "security",
    "training",
    "typescript",
]

POLICY_KEYWORDS = [
    "ai",
    "algorithm",
    "artificial intelligence",
    "chip",
    "cloud",
    "compute",
    "cyber",
    "data",
    "deepfake",
    "digital",
    "export control",
    "frontier model",
    "model",
    "privacy",
    "semiconductor",
]

POLICY_EXCLUDE_KEYWORDS = [
    "airplane",
    "airworthiness",
    "aviation",
    "boeing",
    "citizenship",
    "event date",
    "substance use",
    "webinar",
]

POLICY_SUMMARY_HINTS = {
    "white house": "美国行政层面的科技政策或总统行动，可能影响 AI、芯片、安全与政府采购方向。",
    "federal register": "美国联邦正式法规/公告渠道，适合关注合规义务、征求意见和监管落地。",
    "federal trade commission": "美国 FTC 消费者保护和竞争监管动态，可能影响 AI 产品宣传、隐私和平台责任。",
    "nist": "美国 NIST 标准与测评动态，通常影响 AI 安全、网络安全、标准化和企业合规实践。",
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

# Extra scoring terms keep developer, infrastructure, and security updates visible
# without turning them into separate top-level tabs.
KEYWORDS["company"].extend(
    [
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
        "aws",
        "azure",
        "cloud",
        "cuda",
        "gpu",
        "inference",
        "nvidia",
        "training",
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
    ]
)


@dataclass
class FeedItem:
    title: str
    link: str
    source: str
    board: str
    published: str
    summary_raw: str
    tier: str


@dataclass
class PolicyItem:
    title: str
    link: str
    source: str
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


def fetch_json_url(url: str) -> dict:
    return json.loads(fetch_url(url).decode("utf-8"))


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


def iso_to_dt(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(TZ)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)


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


def parse_policy_feed(content: bytes, source: str) -> list[PolicyItem]:
    return [
        PolicyItem(
            title=item.title,
            link=item.link,
            source=source,
            published=item.published,
            summary_raw=item.summary_raw,
        )
        for item in parse_feed(content, source, "company", "advisory")
    ]


def parse_federal_register(payload: dict) -> list[PolicyItem]:
    items: list[PolicyItem] = []
    for row in payload.get("results", []):
        title = clean_text(str(row.get("title") or ""))
        link = clean_text(str(row.get("html_url") or row.get("pdf_url") or ""))
        summary = clean_text(str(row.get("abstract") or ""))
        published = parse_date(str(row.get("publication_date") or ""))
        if title and link:
            items.append(PolicyItem(title, link, "Federal Register", published, summary))
    return items


def classify(text: str, fallback: str) -> str:
    lowered = text.lower()
    scores = {
        board: sum(1 for keyword in keywords if keyword in lowered)
        for board, keywords in KEYWORDS.items()
    }
    board, score = max(scores.items(), key=lambda pair: pair[1])
    return board if score else fallback


def has_keyword(text: str, keyword: str) -> bool:
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def is_policy_relevant(item: PolicyItem, cutoff: datetime, now: datetime) -> bool:
    published = iso_to_dt(item.published)
    if published < cutoff or published > now:
        return False
    text = f"{item.title} {item.summary_raw}".lower()
    if any(has_keyword(text, keyword) for keyword in POLICY_EXCLUDE_KEYWORDS):
        return False
    return any(has_keyword(text, keyword) for keyword in POLICY_KEYWORDS)


def policy_meaning(source: str) -> str:
    lowered = source.lower()
    for key, hint in POLICY_SUMMARY_HINTS.items():
        if key in lowered:
            return hint
    return "科技政策或监管动态，建议关注其对 AI 产品、数据合规、算力供应和企业部署的影响。"


def make_policy_what(item: PolicyItem) -> str:
    summary = clean_text(item.summary_raw)
    if len(summary) > 150:
        summary = summary[:147].rstrip() + "..."
    return f"发布/更新：{item.title}。" + (f" {summary}" if summary else "")


def collect_policies(now: datetime, limit: int = 5) -> list[dict]:
    cutoff = now - timedelta(days=7)
    collected: list[PolicyItem] = []
    seen: set[str] = set()

    for source, url in POLICY_RSS_SOURCES:
        try:
            parsed = parse_policy_feed(fetch_url(url), source)
        except (ET.ParseError, urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"warning: failed to fetch policy source {source}: {exc}", file=sys.stderr)
            continue
        collected.extend(parsed[:10])

    try:
        collected.extend(parse_federal_register(fetch_json_url(FEDERAL_REGISTER_URL)))
    except (json.JSONDecodeError, urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"warning: failed to fetch policy source Federal Register: {exc}", file=sys.stderr)

    filtered: list[PolicyItem] = []
    for item in collected:
        key = item.link.split("?")[0]
        if key in seen or not is_policy_relevant(item, cutoff, now):
            continue
        seen.add(key)
        filtered.append(item)

    filtered.sort(key=lambda item: item.published, reverse=True)
    return [
        {
            "title": item.title,
            "source": item.source,
            "what": make_policy_what(item),
            "meaning": policy_meaning(item.source),
            "published": item.published,
            "link": item.link,
        }
        for item in filtered[:limit]
    ]


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
        "policies": collect_policies(now),
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
