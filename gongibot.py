#!/usr/bin/env python3
"""네이버 카페 게시판 새 글을 텔레그램으로 알림 전송하는 봇."""

from __future__ import annotations

import json
import logging
import os
TELEGRAM_TOKEN  = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT   = os.environ["TELEGRAM_CHAT"]
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class CafeArticle:
    article_id: int
    title: str
    url: str


class ConfigError(Exception):
    """환경 변수 누락/형식 오류."""


class NaverCafeTelegramBot:
    def __init__(self) -> None:
        self.club_id = self._read_int_env("NAVER_CAFE_CLUB_ID")
        self.menu_id = self._read_int_env("NAVER_CAFE_MENU_ID")
        self.telegram_token = self._read_env("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = self._read_env("TELEGRAM_CHAT_ID")
        self.poll_interval_seconds = self._read_int_env("POLL_INTERVAL_SECONDS", default=60)
        self.state_file = Path(os.getenv("STATE_FILE", "state.json"))

        self.user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
        self.referer = f"https://m.cafe.naver.com/ca-fe/web/cafes/{self.club_id}/menus/{self.menu_id}"

        self.last_article_id = self._load_last_article_id()

    @staticmethod
    def _read_env(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise ConfigError(f"환경 변수 {name} 가 필요합니다.")
        return value

    @staticmethod
    def _read_int_env(name: str, default: int | None = None) -> int:
        raw = os.getenv(name)
        if raw is None:
            if default is None:
                raise ConfigError(f"환경 변수 {name} 가 필요합니다.")
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ConfigError(f"환경 변수 {name} 는 정수여야 합니다. (현재: {raw})") from exc

    def _load_last_article_id(self) -> int | None:
        if not self.state_file.exists():
            return None
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            article_id = data.get("last_article_id")
            if isinstance(article_id, int):
                return article_id
        except json.JSONDecodeError:
            logging.warning("상태 파일이 손상되어 초기화합니다: %s", self.state_file)
        return None

    def _save_last_article_id(self, article_id: int) -> None:
        payload = {"last_article_id": article_id}
        self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _http_get_text(self, base_url: str, params: dict[str, Any], timeout: int = 10) -> str:
        query = urlencode(params)
        request = Request(
            url=f"{base_url}?{query}",
            headers={"User-Agent": self.user_agent, "Referer": self.referer},
            method="GET",
        )
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")

    def _http_post_form_json(self, url: str, form: dict[str, str], timeout: int = 10) -> dict[str, Any]:
        body = urlencode(form).encode("utf-8")
        request = Request(
            url=url,
            data=body,
            headers={"User-Agent": self.user_agent, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
            return json.loads(text)

    def fetch_latest_articles(self, per_page: int = 20) -> list[CafeArticle]:
        url = "https://apis.naver.com/cafe-web/cafe2/ArticleListV2dot1.json"
        params = {
            "search.clubid": self.club_id,
            "search.menuid": self.menu_id,
            "search.boardtype": "L",
            "search.page": 1,
            "search.perPage": per_page,
            "ad": "false",
            "uuid": "",
        }

        raw = self._http_get_text(url, params)
        payload = self._parse_json_or_jsonp(raw)
        message = payload.get("message", {})
        article_list = message.get("result", {}).get("articleList", [])

        articles: list[CafeArticle] = []
        for item in article_list:
            article_id = item.get("articleid")
            title = item.get("subject")
            if not isinstance(article_id, int) or not isinstance(title, str):
                continue
            article_url = (
                f"https://cafe.naver.com/ArticleRead.nhn?clubid={self.club_id}&articleid={article_id}"
            )
            articles.append(CafeArticle(article_id=article_id, title=title.strip(), url=article_url))

        return articles

    @staticmethod
    def _parse_json_or_jsonp(raw: str) -> dict[str, Any]:
        raw = raw.strip()
        if raw.startswith("{"):
            return json.loads(raw)

        start = raw.find("(")
        end = raw.rfind(")")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("JSON/JSONP 응답 파싱 실패")

        return json.loads(raw[start + 1 : end])

    def send_telegram(self, article: CafeArticle) -> None:
        endpoint = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        message = f"🆕 새 글\n- 제목: {article.title}\n- 링크: {article.url}"
        data = self._http_post_form_json(
            endpoint,
            {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "disable_web_page_preview": "true",
            },
        )
        if not data.get("ok"):
            raise RuntimeError(f"텔레그램 전송 실패: {data}")

    def run_once(self) -> None:
        articles = self.fetch_latest_articles()
        if not articles:
            logging.info("글 목록이 비어 있습니다.")
            return

        latest_id = max(article.article_id for article in articles)

        if self.last_article_id is None:
            self.last_article_id = latest_id
            self._save_last_article_id(latest_id)
            logging.info("초기 실행: 가장 최신 글 ID(%s)를 기준점으로 저장했습니다.", latest_id)
            return

        new_articles = [a for a in articles if a.article_id > self.last_article_id]
        if not new_articles:
            logging.info("새 글이 없습니다. (last=%s)", self.last_article_id)
            return

        new_articles.sort(key=lambda x: x.article_id)
        for article in new_articles:
            self.send_telegram(article)
            logging.info("전송 완료: %s (%s)", article.title, article.article_id)

        self.last_article_id = max(article.article_id for article in new_articles)
        self._save_last_article_id(self.last_article_id)

    def run_forever(self) -> None:
        logging.info(
            "감시 시작: club_id=%s menu_id=%s interval=%ss",
            self.club_id,
            self.menu_id,
            self.poll_interval_seconds,
        )
        while True:
            try:
                self.run_once()
            except Exception:
                logging.exception("처리 중 오류 발생")
            time.sleep(self.poll_interval_seconds)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        bot = NaverCafeTelegramBot()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc

    bot.run_forever()


if __name__ == "__main__":
    main()



