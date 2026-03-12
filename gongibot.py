import os
import json
import requests
import time

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT  = os.environ["TELEGRAM_CHAT"]

# ── 네이버 카페 설정 ──────────────────────
CAFE_ID = 21160703

BOARDS = {
    "종합":      {"menu_id": 2510, "enabled": True, "header": "🔴 종합 공고"},
    "중앙공기업": {"menu_id": 861,  "enabled": True, "header": "🏢 중앙공기업"},
    "지방공기업": {"menu_id": 2486, "enabled": True, "header": "🏛 지방공기업"},
    "인턴계약직": {"menu_id": 2488, "enabled": True, "header": "📄 인턴/계약직"},
    "학교병원":  {"menu_id": 2487, "enabled": True, "header": "🏥 학교/병원"},
}

# ── 네이버 블로그 설정 ────────────────────
BLOG_TARGETS = [
    {
        "name":        "최신채용공고",
        "blog_id":     "ekfzhaduddj",
        "category_no": 15,
        "header":      "📋 최신 채용공고",
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
            print(f"[경고] 설정 파일 읽기 실패, 기본값 사용: {e}")
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
                # 구버전 리스트 형태 호환
                if isinstance(data, list):
                    print("[안내] 기존 seen_posts.json을 새 형식으로 변환합니다.")
                    new_data = {k: [] for k in ALL_SOURCE_KEYS}
                    new_data["종합"] = data
                    save_seen(new_data)
                    return new_data
                # 새 소스 키 누락 시 보완
                for k in ALL_SOURCE_KEYS:
                    data.setdefault(k, [])
                return data
        except Exception as e:
            print(f"[경고] seen_posts 파일 읽기 실패, 기본값 사용: {e}")
    return {k: [] for k in ALL_SOURCE_KEYS}

def save_seen(seen: dict):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


# ── 텔레그램 ──────────────────────────────

def send_telegram(text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id":                  TELEGRAM_CHAT,
                "text":                     text,
                "parse_mode":               "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        ).raise_for_status()
    except Exception as e:
        print(f"[오류] 텔레그램 전송 실패: {e}")


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
    """
    네이버 블로그 카테고리별 글 목록 조회
    반환: [{"post_id": str, "title": str, "link": str}, ...]
    """
    url = "https://blog.naver.com/PostTitleListAsync.naver"
    params = {
        "blogId":       blog_id,
        "categoryNo":   category_no,
        "currentPage":  1,
        "countPerPage": 20,
        "viewdate":     "",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Referer":    f"https://blog.naver.com/{blog_id}",
        "Accept":     "application/json, text/javascript, */*",
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        posts = []
        for item in data.get("postList", []):
            post_id = str(item.get("logNo", ""))
            title   = unquote_plus(item.get("title", "(제목 없음)")).strip()
            link    = f"https://blog.naver.com/{blog_id}/{post_id}"
            if post_id:
                posts.append({"post_id": post_id, "title": title, "link": link})
        return posts
    except Exception as e:
        print(f"[오류] 블로그 {blog_id} 카테고리 {category_no} 조회 실패: {e}")
        return []


# ── 모니터링 ──────────────────────────────

def monitor_boards():
    config = load_config()
    seen   = load_seen()
    is_first_run = all(len(v) == 0 for v in seen.values())
    total_new = 0

    # ── 카페 게시판 ──
    for board_name, board_info in BOARDS.items():
        if not config.get(board_name, True):
            continue

        menu_id = board_info["menu_id"]
        print(f"\n[카페 {board_name}] 확인 중...")

        articles = fetch_cafe_articles(menu_id)
        if not articles:
            print("  ⚠️ 게시글을 가져오지 못했습니다.")
            continue

        if is_first_run:
            seen[board_name] = [str(a["articleId"]) for a in articles]
            print(f"  ✓ {len(articles)}개 기존 글 등록")
            continue

        seen_ids     = set(seen.get(board_name, []))
        new_articles = [a for a in articles if str(a["articleId"]) not in seen_ids]
        new_articles.reverse()

        for a in new_articles:
            aid   = str(a["articleId"])
            title = a.get("subject", "(제목 없음)")
            url   = f"https://cafe.naver.com/ca-fe/cafes/{CAFE_ID}/articles/{aid}"
            text  = f"{board_info['header']}\n★ {title}\n<a href=\"{url}\">바로가기</a>"
            send_telegram(text)
            print(f"  📤 전송: {title}")
            seen[board_name].append(aid)
            total_new += 1
            time.sleep(0.5)

        if not new_articles:
            print("  ✓ 새 글 없음")

    # ── 블로그 ──
    for target in BLOG_TARGETS:
        name        = target["name"]
        blog_id     = target["blog_id"]
        category_no = target["category_no"]
        header      = target["header"]

        if not config.get(name, True):
            continue

        print(f"\n[블로그 {name}] 확인 중...")

        posts = fetch_blog_posts(blog_id, category_no)
        if not posts:
            print("  ⚠️ 게시글을 가져오지 못했습니다.")
            continue

        if is_first_run:
            seen[name] = [p["post_id"] for p in posts]
            print(f"  ✓ {len(posts)}개 기존 글 등록")
            continue

        seen_ids  = set(seen.get(name, []))
        new_posts = [p for p in posts if p["post_id"] not in seen_ids]
        new_posts.reverse()

        for p in new_posts:
            text = f"{header}\n★ {p['title']}\n<a href=\"{p['link']}\">바로가기</a>"
            send_telegram(text)
            print(f"  📤 전송: {p['title']}")
            seen[name].append(p["post_id"])
            total_new += 1
            time.sleep(0.5)

        if not new_posts:
            print("  ✓ 새 글 없음")

    save_seen(seen)
    save_config(config)

    if is_first_run:
        print("\n✅ 첫 실행 완료. 이후부터 새 글 알림 시작.")
    else:
        print(f"\n✅ 모니터링 완료. 총 {total_new}개 새 글 알림.")


# ── 텔레그램 명령어 처리 ──────────────────

def handle_telegram_commands():
    last_update_id = 0
    print("\n🤖 텔레그램 봇 시작 (명령어 대기 중)")
    print("명령어: /help, /status, /on [이름], /off [이름]")
    print("Ctrl+C로 종료\n")

    while True:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": last_update_id + 1, "timeout": 30},
                timeout=35,
            )
            data = resp.json()
            if not data.get("ok"):
                continue

            for update in data.get("result", []):
                last_update_id = update["update_id"]
                message = update.get("message", {})
                chat_id = message.get("chat", {}).get("id")
                text    = message.get("text", "")

                if str(chat_id) != str(TELEGRAM_CHAT):
                    continue

                config = load_config()

                if text == "/help":
                    board_list = "\n".join(f"• {k}" for k in ALL_SOURCE_KEYS)
                    send_telegram(
                        f"📚 <b>공고 알리미 사용법</b>\n\n"
                        f"<b>🔹 명령어</b>\n"
                        f"/help - 도움말\n"
                        f"/status - 활성화 상태\n"
                        f"/on [이름] - 알림 켜기\n"
                        f"/off [이름] - 알림 끄기\n\n"
                        f"<b>🔹 소스 목록</b>\n{board_list}"
                    )

                elif text == "/status":
                    lines = "\n".join(
                        f"{'✅' if config.get(k, True) else '❌'} {k}"
                        for k in ALL_SOURCE_KEYS
                    )
                    send_telegram(f"📊 <b>활성화 상태</b>\n\n{lines}")

                elif text.startswith("/on ") or text.startswith("/off "):
                    parts = text.split(None, 1)
                    if len(parts) != 2:
                        send_telegram("❌ 사용법: /on 이름 또는 /off 이름")
                        continue
                    cmd, target = parts
                    enable = (cmd == "/on")
                    if target not in ALL_SOURCE_KEYS:
                        send_telegram(f"❌ 알 수 없는 소스입니다.\n\n사용 가능: {', '.join(ALL_SOURCE_KEYS)}")
                        continue
                    config[target] = enable
                    save_config(config)
                    action = "활성화" if enable else "비활성화"
                    send_telegram(f"{'✅' if enable else '❌'} <b>{target}</b> {action}됨")

        except KeyboardInterrupt:
            print("\n👋 봇 종료")
            break
        except Exception as e:
            print(f"[오류] {e}")
            time.sleep(5)


# ── 진입점 ────────────────────────────────

def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "bot":
        handle_telegram_commands()
    else:
        monitor_boards()

if __name__ == "__main__":
    main()
