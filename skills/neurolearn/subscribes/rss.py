"""YouTube channel RSS feed — fetch via urllib, parse via xml.etree.

YouTube exposes per-channel RSS at
https://www.youtube.com/feeds/videos.xml?channel_id=<UC...>
with ~15 most recent videos. Stable public format used for 10+ years.

Used in subscribes for fast discovery: ~10× faster than yt-dlp channel
scraping for most workloads. Falls back to yt-dlp when filters need
data not in RSS (duration, views, description).
"""
from __future__ import annotations

import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone


_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}


@dataclass
class RssEntry:
    video_id: str
    url: str
    title: str
    channel_id: str
    published: datetime


def rss_url_for_channel(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def fetch_rss(channel_id: str, *, timeout: float = 10.0) -> list[RssEntry]:
    """Fetch + parse RSS for a channel. Empty list on any error."""
    try:
        body = _http_get(rss_url_for_channel(channel_id), timeout=timeout)
    except (urllib.error.URLError, OSError):
        return []
    return parse_rss(body)


def parse_rss(xml_text: str) -> list[RssEntry]:
    """Parse YouTube channel RSS XML. Empty list on malformed input."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[RssEntry] = []
    for entry in root.findall("atom:entry", _NS):
        vid_el = entry.find("yt:videoId", _NS)
        title_el = entry.find("atom:title", _NS)
        pub_el = entry.find("atom:published", _NS)
        ch_el = entry.find("yt:channelId", _NS)
        if vid_el is None or vid_el.text is None:
            continue
        out.append(RssEntry(
            video_id=vid_el.text,
            url=f"https://www.youtube.com/watch?v={vid_el.text}",
            title=(title_el.text if title_el is not None else "") or "",
            channel_id=(ch_el.text if ch_el is not None else "") or "",
            published=_parse_iso(pub_el.text if pub_el is not None else None),
        ))
    return out


def entries_after(entries: list[RssEntry], cutoff: datetime) -> list[RssEntry]:
    """Return entries whose `published` is strictly after `cutoff`."""
    return [e for e in entries if e.published > cutoff]


def _http_get(url: str, *, timeout: float = 10.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "neurolearn/0.7"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _parse_iso(s: str | None) -> datetime:
    """Parse YouTube ISO 8601 timestamp. Returns epoch on failure."""
    if not s:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    # Replace trailing Z with +00:00 for fromisoformat compat
    cleaned = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
