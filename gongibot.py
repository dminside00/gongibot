import os
import json
import re
import requests
import time
from urllib.parse import unquote_plus

# ── 설정 로드 ──────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
# 쉼표로 구분된 여러 ID를 리스트로 변환 (예: "12345,-10067890")
RAW_CHATS = os.environ.get("TELEGRAM_CHAT", "")
TARGET_CHATS = [c.strip() for c in RAW_CHATS.split(",") if c.strip()]

# 명령어 제어 권한을 가진 마스터 ID (첫 번째 ID를 관리자로 간주)
ADMIN_CHAT = TARGET_CHATS[0] if TARGET_CHATS else ""

# ── 네이버 카페 설정 ──────────────────────
CAFE_ID = 21160703

BOARDS = {
    "종합":      {"menu_id": 2510, "enabled": True, "header": "🔴 종합"},
    "중앙공기업": {"menu_id": 861,  "enabled": True, "header": "🏢 중앙"},
    "지방공기업": {"menu_id": 2486, "enabled": True, "header": "🏛 지방"},
    "인턴계약직": {"menu_id": 2488, "enabled": True, "header": "📄 인턴"},
    "학교병원":  {"menu_id": 2487, "enabled": True, "header": "🏥 학병"},
}

# ── 네이버 블로그 설정 ────────────────────
BLOG_TARGETS = [
    {
        "name":        "최신채용공고",
        "blog_id":     "ekfzhaduddj",
        "category_no": 15,
        "header":      "🟢 정리",
    },
]

SEEN_FILE   = "seen_posts.json"
CONFIG_FILE = "boards_config.json"

ALL_SOURCE_KEYS = list(BOARDS.keys()) + [b["name"] for b in BLOG_TARGETS]


# ── seen / config 관리 ────────────────────

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return {k: True for k in ALL_SOURCE_KEYS}
                return json.loads(content)
        except Exception as e:
            print(f"[경고] 설정 파일 읽기 실패: {e}")
    return {k: True for k in ALL_SOURCE_KEYS}

def save_config(config: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def load_seen() -> dict:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return {k: [] for k in ALL_SOURCE_KEYS}
                data = json.loads(content)
                if isinstance(data, list):
                    new_data = {k: [] for k in ALL_SOURCE_KEYS}
                    new_data["종합"] = data
                    return new_data
                for k in ALL_SOURCE_KEYS:
                    data.setdefault(k, [])
                return data
        except Exception as e:
            print(f"[경고] seen_posts 읽기 실패: {e}")
    return {k: [] for k in ALL_SOURCE_KEYS}

def save_seen(seen: dict):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


# ── 텔레그램 (다중 전송) ──────────────────────

def send_telegram(text: str):
    """설정된 모든 TARGET_CHATS로 메시지를 전송합니다."""
    for chat_id in TARGET_CHATS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id":                  chat_id,
                    "text":                      text,
                    "parse_mode":                "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            ).raise_for_status()
        except Exception as e:
            print(f"[오류] 텔레그램 전송 실패 (대상: {chat_id}): {e}")


# ── 네이버 카페 크롤링 ────────────────────

def fetch_cafe_articles(menu_id: int) -> list:
    url = "https://apis.naver.com/cafe-web/cafe2/ArticleListV2dot1.json"
    params = {
        "search.clubid":    CAFE_ID,
        "search.menuid":    menu_id,
        "search.boardtype": "L",
        "search.page":      1,
        "search.perPage":   20,
        "ad":               "false",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Referer": f"https://cafe.naver.com/f-e/cafes/{CAFE_ID}/menus/{menu_id}",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("result", {}).get("articleList", [])
    except Exception as e:
        print(f"[오류] 카페 게시판 {menu_id} 조회 실패: {e}")
        return []


# ── 네이버 블로그 크롤링 ──────────────────

def fetch_blog_posts(blog_id: str, category_no: int) -> list:
    url = "https://blog.naver.com/PostTitleListAsync.naver"
    params = {
        "blogId":       blog_id,
        "categoryNo":   category_no,
        "currentPage":  1,
        "countPerPage": 20,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Referer":    f"https://blog.naver.com/{blog_id}",
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        cleaned = re.sub(r'\\([^"\\/bfnrtu0-9])', r'\1', resp.text)
        data = json.loads(cleaned)
        posts = []
        for item in data.get("postList", []):
            post_id = str(item.get("logNo", ""))
            title   = unquote_plus(item.get("title", "(제목 없음)")).strip()
            link    = f"https://blog.naver.com/{blog_id}/{post_id}"
            if post_id:
                posts.append({"post_id": post_id, "title": title, "link": link})
        return posts
    except Exception as e:
        print(f"[오류] 블로그 {blog_id} 조회 실패: {e}")
        return []


# ── 모니터링 ──────────────────────────────

def monitor_boards():
    config = load_config()
    seen   = load_seen()
    is_first_run = all(len(v) == 0 for v in seen.values())
    total_new = 0

    # 카페 확인
    for board_name, board_info in BOARDS.items():
        if not config.get(board_name, True): continue
        articles = fetch_cafe_articles(board_info["menu_id"])
        if is_first_run:
            seen[board_name] = [str(a["articleId"]) for a in articles]
            continue
        seen_ids = set(seen.get(board_name, []))
        new_articles = [a for a in articles if str(a["articleId"]) not in seen_ids]
        new_articles.reverse()
        for a in new_articles:
            aid = str(a["articleId"])
            url = f"https://cafe.naver.com/ca-fe/cafes/{CAFE_ID}/articles/{aid}"
            text = f"{board_info['header']}\n★ {a.get('subject', '(제목 없음)')}\n<a href=\"{url}\">바로가기</a>"
            send_telegram(text)
            seen[board_name].append(aid)
            total_new += 1
            time.sleep(0.5)

    # 블로그 확인
    for target in BLOG_TARGETS:
        name = target["name"]
        if not config.get(name, True): continue
        posts = fetch_blog_posts(target["blog_id"], target["category_no"])
        if is_first_run:
            seen[name] = [p["post_id"] for p in posts]
            continue
        seen_ids = set(seen.get(name, []))
        new_posts = [p for p in posts if p["post_id"] not in seen_ids]
        new_posts.reverse()
        for p in new_posts:
            text = f"{target['header']}\n★ {p['title']}\n<a href=\"{p['link']}\">바로가기</a>"
            send_telegram(text)
            seen[name].append(p["post_id"])
            total_new += 1
            time.sleep(0.5)

    save_seen(seen)
    if is_first_run: print("✅ 초기 데이터 등록 완료.")
    else: print(f"✅ 모니터링 완료 ({total_new}개 전송)")


# ── 명령어 처리 (관리자 제한) ──────────────────

def handle_telegram_commands():
    last_update_id = 0
    print(f"🤖 봇 명령어 대기 중 (관리자 ID: {ADMIN_CHAT})")

    while True:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": last_update_id + 1, "timeout": 30},
                timeout=35,
            )
            data = resp.json()
            if not data.get("ok"): continue

            for update in data.get("result", []):
                last_update_id = update["update_id"]
                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id", ""))
                text    = message.get("text", "")

                # 관리자 방에서 온 명령어만 처리 (채널 메시지 등 무시)
                if chat_id != ADMIN_CHAT:
                    continue

                config = load_config()

                if text == "/help":
                    board_list = "\n".join(f"• {k}" for k in ALL_SOURCE_KEYS)
                    send_telegram(f"📚 <b>관리 메뉴</b>\n\n/status - 상태 확인\n/on 이름 - 켜기\n/off 이름 - 끄기\n\n<b>목록:</b>\n{board_list}")

                elif text == "/status":
                    lines = "\n".join(f"{'✅' if config.get(k, True) else '❌'} {k}" for k in ALL_SOURCE_KEYS)
                    send_telegram(f"📊 <b>활성화 상태</b>\n\n{lines}")

                elif text.startswith("/on ") or text.startswith("/off "):
                    parts = text.split(None, 1)
                    if len(parts) == 2:
                        cmd, target = parts
                        if target in ALL_SOURCE_KEYS:
                            config[target] = (cmd == "/on")
                            save_config(config)
                            send_telegram(f"{'✅' if config[target] else '❌'} <b>{target}</b> 변경됨")

        except Exception as e:
            print(f"[오류] {e}")
            time.sleep(5)


def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "bot":
        handle_telegram_commands()
    else:
        monitor_boards()

if __name__ == "__main__":
    main()
