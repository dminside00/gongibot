#!/usr/bin/env python3
"""네이버 카페 새 글 알림 텔레그램 봇.

- 1시간 간격으로 특정 카페 메뉴의 게시글 목록을 조회합니다.
- 마지막으로 확인한 게시글 ID보다 큰 글이 있으면 텔레그램으로 알림을 전송합니다.
"""

from __future__ import annotations

import html
import json
import os
import time
from dataclasses import dataclass
from typing import List
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# 요청하신 값(필요하면 환경변수로 덮어쓰기 가능)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8537012484:AAGwlM_Xh-PaLJJ1Bn2ax6fG3x6TlRvEZCc")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5983760560")
CAFE_ID = int(os.getenv("NAVER_CAFE_ID", "21160703"))
MENU_ID = int(os.getenv("NAVER_MENU_ID", "2510"))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "3600"))
STATE_FILE = os.getenv("STATE_FILE", "last_seen_article_id.txt")


@dataclass
class Article:
    article_id: int
    subject: str

    @property
    def url(self) -> str:
        return f"https://cafe.naver.com/ca-fe/cafes/{CAFE_ID}/articles/{self.article_id}"


def fetch_article_list() -> List[Article]:
    """네이버 카페 게시글 목록 JSON을 조회해 최신순으로 반환합니다."""
    api_url = (
        "https://apis.naver.com/cafe-web/cafe2/ArticleListV2dot1.json"
        f"?search.clubid={CAFE_ID}"
        f"&search.menuid={MENU_ID}"
        "&search.page=1"
        "&search.perPage=50"
        "&search.sortBy=date"
        "&search.orderBy=desc"
    )

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": f"https://cafe.naver.com/f-e/cafes/{CAFE_ID}/menus/{MENU_ID}?viewType=L",
        "Accept": "application/json, text/plain, */*",
    }

    req = Request(api_url, headers=headers)
    with urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    article_list = payload.get("message", {}).get("result", {}).get("articleList", [])

    parsed: List[Article] = []
    for item in article_list:
        article_id = item.get("articleId")
        subject = item.get("subject")
        if article_id is None or subject is None:
            continue
        parsed.append(Article(article_id=int(article_id), subject=str(subject).strip()))

    return parsed


def send_telegram_message(text: str) -> None:
    """텔레그램으로 HTML 형식 메시지를 보냅니다."""
    endpoint = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urlencode(
        {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")

    req = Request(endpoint, data=data, method="POST")
    with urlopen(req, timeout=20) as response:
        body = json.loads(response.read().decode("utf-8"))

    if not body.get("ok"):
        raise RuntimeError(f"텔레그램 전송 실패: {body}")


def load_last_seen_article_id() -> int | None:
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def save_last_seen_article_id(article_id: int) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(str(article_id))


def build_notice_message(article: Article) -> str:
    safe_title = html.escape(article.subject)
    safe_url = html.escape(article.url, quote=True)
    return f"[공고 알림]\n★{safe_title}\n<a href=\"{safe_url}\">링크</a>"


def run() -> None:
    print("네이버 카페 알림 봇 시작")
    print(f"- cafe_id={CAFE_ID}, menu_id={MENU_ID}")
    print(f"- poll_interval={POLL_INTERVAL_SECONDS}s")

    last_seen = load_last_seen_article_id()

    while True:
        try:
            articles = fetch_article_list()
            if not articles:
                print("게시글 목록이 비어 있습니다.")
            else:
                latest_id = max(a.article_id for a in articles)

                if last_seen is None:
                    last_seen = latest_id
                    save_last_seen_article_id(last_seen)
                    print(f"초기화 완료. 마지막 게시글 ID={last_seen}")
                else:
                    new_articles = [a for a in articles if a.article_id > last_seen]

                    if new_articles:
                        # 오래된 것부터 순서대로 전송
                        new_articles.sort(key=lambda x: x.article_id)
                        for article in new_articles:
                            send_telegram_message(build_notice_message(article))
                            print(f"전송 완료: {article.article_id} / {article.subject}")

                        last_seen = max(a.article_id for a in new_articles)
                        save_last_seen_article_id(last_seen)
                    else:
                        print("새 글 없음")

        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as e:
            print(f"오류 발생: {e}")
        except Exception as e:  # 예기치 못한 오류 대비
            print(f"예상치 못한 오류: {e}")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()
