import os
import json
import requests

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT  = os.environ["TELEGRAM_CHAT"]
CAFE_ID        = 21160703
MENU_ID        = 2510
SEEN_FILE      = "seen_posts.json"


def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False)


def fetch_articles() -> list:
    url = "https://apis.naver.com/cafe-web/cafe2/ArticleListV2dot1.json"
    params = {
        "search.clubid":    CAFE_ID,
        "search.menuid":    MENU_ID,
        "search.boardtype": "L",
        "search.page":      1,
        "search.perPage":   20,
        "ad":               "false",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Referer": f"https://cafe.naver.com/f-e/cafes/{CAFE_ID}/menus/{MENU_ID}",
    }
    resp = requests.get(url, params=params, headers=headers, timeout=15)
    print("상태코드:", resp.status_code)
    print("응답내용:", resp.text[:1000])
    resp.raise_for_status()
    return resp.json().get("message", {}).get("result", {}).get("articleList", [])


def send_telegram(title: str, url: str):
    text = f"[공고 알림]\n★{title}\n<a href=\"{url}\">링크</a>"
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=15,
    ).raise_for_status()
    print(f"전송 완료: {title}")


def main():
    seen = load_seen()
    is_first_run = len(seen) == 0

    articles = fetch_articles()
    if not articles:
        print("게시글을 가져오지 못했습니다.")
        return

    if is_first_run:
        for a in articles:
            seen.add(str(a["articleId"]))
        save_seen(seen)
        print(f"첫 실행: {len(seen)}개 기존 글 등록 완료. 이후 새 글부터 알림.")
        return

    new_articles = [a for a in articles if str(a["articleId"]) not in seen]
    new_articles.reverse()

    for a in new_articles:
        aid = str(a["articleId"])
        title = a.get("subject", "(제목 없음)")
        url = f"https://cafe.naver.com/ca-fe/cafes/{CAFE_ID}/articles/{aid}"
        send_telegram(title, url)
        seen.add(aid)

    save_seen(seen)
    print("새 글 없음." if not new_articles else f"{len(new_articles)}개 알림 완료.")


if __name__ == "__main__":
    main()



