from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


DEFAULT_MERCHANT_URL = (
    "https://www.onebiji.com/hykb_tools/comm/lkwgmerchant/preview.php?id=1&immgj=0"
)
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_REFRESH_TIMES = ("08:00", "12:00", "16:00", "20:00")
DEFAULT_WINDOW_MINUTES = 20


@dataclass
class Config:
    merchant_url: str
    ntfy_server: str
    ntfy_topic: str
    ntfy_token: str | None
    timezone: str
    refresh_times: list[str]
    refresh_window_minutes: int
    watch_items: list[str]
    state_path: Path
    history_path: Path
    request_timeout_seconds: int
    force_run: bool
    notify_on_first_run: bool


class MerchantError(Exception):
    pass


def env_or_default(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def load_config() -> Config:
    ntfy_topic = os.getenv("NTFY_TOPIC", "").strip()
    if not ntfy_topic:
        raise MerchantError("Missing required environment variable: NTFY_TOPIC")

    watch_items_raw = os.getenv("WATCH_ITEMS", "")
    watch_items = [item.strip() for item in watch_items_raw.split(",") if item.strip()]

    refresh_times_raw = os.getenv("REFRESH_TIMES", ",".join(DEFAULT_REFRESH_TIMES))
    refresh_times = [item.strip() for item in refresh_times_raw.split(",") if item.strip()]

    return Config(
        merchant_url=env_or_default("MERCHANT_URL", DEFAULT_MERCHANT_URL),
        ntfy_server=env_or_default("NTFY_SERVER", "https://ntfy.sh").rstrip("/"),
        ntfy_topic=ntfy_topic,
        ntfy_token=os.getenv("NTFY_TOKEN", "").strip() or None,
        timezone=env_or_default("TIMEZONE", DEFAULT_TIMEZONE),
        refresh_times=refresh_times,
        refresh_window_minutes=int(
            os.getenv("REFRESH_WINDOW_MINUTES", str(DEFAULT_WINDOW_MINUTES))
        ),
        watch_items=watch_items,
        state_path=Path(os.getenv("STATE_PATH", "data/latest.json")),
        history_path=Path(os.getenv("HISTORY_PATH", "data/history.jsonl")),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20")),
        force_run=os.getenv("FORCE_RUN", "").lower() in {"1", "true", "yes", "on"},
        notify_on_first_run=os.getenv("NOTIFY_ON_FIRST_RUN", "true").lower()
        in {"1", "true", "yes", "on"},
    )


def now_in_zone(timezone_name: str) -> datetime:
    return datetime.now(ZoneInfo(timezone_name))


def should_run(config: Config, current_time: datetime) -> bool:
    if config.force_run:
        return True

    current_minutes = current_time.hour * 60 + current_time.minute
    window = config.refresh_window_minutes

    for item in config.refresh_times:
        scheduled = parse_hhmm(item)
        scheduled_minutes = scheduled.hour * 60 + scheduled.minute
        if abs(current_minutes - scheduled_minutes) <= window:
            return True

    return False


def parse_hhmm(value: str) -> time:
    hour_str, minute_str = value.split(":", 1)
    return time(hour=int(hour_str), minute=int(minute_str))


def fetch_page(config: Config) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
        )
    }
    response = requests.get(
        config.merchant_url,
        headers=headers,
        timeout=config.request_timeout_seconds,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def parse_current_slot(soup: BeautifulSoup) -> dict[str, Any]:
    time_items = soup.select(".time-list li")
    if not time_items:
        raise MerchantError("Failed to find time slots in merchant page")

    for index, element in enumerate(time_items, start=1):
        classes = element.get("class", [])
        if "on" not in classes:
            continue

        values = [em.get_text(strip=True) for em in element.select("em")]
        start = values[0] if len(values) > 0 else ""
        end = values[1] if len(values) > 1 else ""
        return {
            "index": int(element.get("data-index", index)),
            "label": f"{start}-{end}" if start and end else f"slot-{index}",
            "start": start,
            "end": end,
        }

    first = time_items[0]
    values = [em.get_text(strip=True) for em in first.select("em")]
    return {
        "index": int(first.get("data-index", 1)),
        "label": f"{values[0]}-{values[1]}" if len(values) >= 2 else "slot-1",
        "start": values[0] if len(values) >= 1 else "",
        "end": values[1] if len(values) >= 2 else "",
    }


def parse_items(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    slot = parse_current_slot(soup)
    selector = f".shop-list li.show_{slot['index']}"
    raw_items = soup.select(selector)

    items: list[dict[str, Any]] = []
    for slot_position, element in enumerate(raw_items, start=1):
        classes = element.get("class", [])
        if "show_none_tip" in classes:
            continue

        name = extract_text(element.select_one(".shop_name"))
        price_text = extract_text(element.select_one(".shop_price")).replace("价格：", "").strip()
        limit_text = extract_limit_text(element)
        if not name:
            continue

        items.append(
            {
                "slot": slot_position,
                "name": name,
                "price_text": price_text,
                "price_value": parse_price(price_text),
                "limit_text": limit_text,
                "limit_value": parse_limit(limit_text),
                "end_timestamp": parse_int(element.get("data-time")),
                "image_url": element.select_one(".gitem img").get("src", "").strip()
                if element.select_one(".gitem img")
                else "",
            }
        )

    if not items:
        raise MerchantError(f"Failed to parse any items for {slot['label']}")

    return {"slot": slot, "items": items}


def extract_limit_text(element: Any) -> str:
    limit_em = element.select_one(".gitem em")
    if not limit_em:
        return ""
    return limit_em.get_text(strip=True)


def extract_text(element: Any) -> str:
    if element is None:
        return ""
    return element.get_text(strip=True)


def parse_price(price_text: str) -> int | None:
    text = price_text.lower().replace("洛克贝", "").strip()
    if not text:
        return None

    multiplier = 1
    if text.endswith("w"):
        multiplier = 10000
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 10000
        text = text[:-1]

    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def parse_limit(limit_text: str) -> int | None:
    match = re.search(r"(\d+)", limit_text)
    if not match:
        return None
    return int(match.group(1))


def parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def load_previous_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def comparable_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "slot": data["slot"],
        "items": [
            {
                "slot": item["slot"],
                "name": item["name"],
                "price_text": item["price_text"],
                "price_value": item["price_value"],
                "limit_text": item["limit_text"],
                "limit_value": item["limit_value"],
            }
            for item in data["items"]
        ],
    }


def has_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return True
    return comparable_payload(previous) != comparable_payload(current)


def format_message(data: dict[str, Any], watch_items: list[str]) -> tuple[str, str, list[str]]:
    slot_label = data["slot"]["label"]
    title = f"远行商人已刷新 {slot_label}"

    matched = [item["name"] for item in data["items"] if item["name"] in watch_items]
    lines = []
    if matched:
        title = f"远行商人命中关注商品 {slot_label}"
        lines.append(f"关注商品：{', '.join(matched)}")

    for item in data["items"]:
        price = item["price_text"] or "未知价格"
        limit_text = item["limit_text"] or "限购未知"
        lines.append(f"{item['slot']}. {item['name']} | {price} | {limit_text}")

    return title, "\n".join(lines), matched


def send_ntfy(config: Config, title: str, message: str, matched_items: list[str]) -> None:
    url = f"{config.ntfy_server}/{config.ntfy_topic}"
    headers = {
        "Title": title,
        "Tags": "shopping_bags,video_game",
        "Priority": "default",
    }
    if matched_items:
        headers["Priority"] = "high"
        headers["Tags"] = "rotating_light,shopping_bags,video_game"
    if config.ntfy_token:
        headers["Authorization"] = f"Bearer {config.ntfy_token}"

    response = requests.post(
        url,
        data=message.encode("utf-8"),
        headers=headers,
        timeout=config.request_timeout_seconds,
    )
    response.raise_for_status()


def save_state(config: Config, data: dict[str, Any]) -> None:
    config.state_path.parent.mkdir(parents=True, exist_ok=True)
    config.history_path.parent.mkdir(parents=True, exist_ok=True)

    config.state_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with config.history_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(data, ensure_ascii=False) + "\n")


def build_payload(config: Config, parsed: dict[str, Any], fetched_at: datetime) -> dict[str, Any]:
    return {
        "source": "onebiji_html",
        "source_url": config.merchant_url,
        "fetched_at": fetched_at.isoformat(),
        "slot": parsed["slot"],
        "items": parsed["items"],
    }


def main() -> int:
    try:
        config = load_config()
        current_time = now_in_zone(config.timezone)
        print(
            "Config loaded:",
            json.dumps(
                {
                    "timezone": config.timezone,
                    "refresh_times": config.refresh_times,
                    "refresh_window_minutes": config.refresh_window_minutes,
                    "force_run": config.force_run,
                    "notify_on_first_run": config.notify_on_first_run,
                    "ntfy_server": config.ntfy_server,
                    "ntfy_topic": config.ntfy_topic,
                },
                ensure_ascii=False,
            ),
        )
        print(f"Current time: {current_time.isoformat()}")
        if not should_run(config, current_time):
            print("Skipping run because current time is outside the refresh window.")
            return 0

        html = fetch_page(config)
        parsed = parse_items(html)
        payload = build_payload(config, parsed, current_time)
        previous = load_previous_state(config.state_path)
        print(
            f"Parsed slot {payload['slot']['label']} with {len(payload['items'])} items."
        )

        if not has_changed(previous, payload):
            print("Merchant data has not changed.")
            return 0

        is_first_run = previous is None
        print(f"Previous state exists: {not is_first_run}")
        title, message, matched_items = format_message(payload, config.watch_items)

        if not is_first_run or config.notify_on_first_run:
            send_ntfy(config, title, message, matched_items)
            print("Notification sent.")
        else:
            print("Initial state saved without sending notification.")

        save_state(config, payload)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
