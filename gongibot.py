import os
import json
import requests
import time
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT  = os.environ["TELEGRAM_CHAT"]
CAFE_ID        = 21160703

# 게시판 설정
BOARDS = {
    "종합": {"menu_id": 2510, "enabled": True, "header": "🔴 종합 공고"},
    "중앙공기업": {"menu_id": 861, "enabled": True, "header": "🏢 중앙공기업"},
    "지방공기업": {"menu_id": 2486, "enabled": True, "header": "🏛 지방공기업"},
    "인턴계약직": {"menu_id": 2488, "enabled": True, "header": "📄 인턴/계약직"},
    "학교병원": {"menu_id": 2487, "enabled": True, "header": "🏥 학교/병원"},
}

SEEN_FILE = "seen_posts.json"
CONFIG_FILE = "boards_config.json"

def load_config() -> dict:
    """게시판 설정 로드"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:  # 빈 파일
                    return {name: board["enabled"] for name, board in BOARDS.items()}
                return json.loads(content)
        except (json.JSONDecodeError, Exception) as e:
            print(f"[경고] 설정 파일 읽기 실패, 기본값 사용: {e}")
            return {name: board["enabled"] for name, board in BOARDS.items()}
    return {name: board["enabled"] for name, board in BOARDS.items()}

def save_config(config: dict):
    """게시판 설정 저장"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def load_seen() -> dict:
    """각 게시판별로 본 글 ID 로드"""
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:  # 빈 파일
                    return {name: [] for name in BOARDS.keys()}
                
                data = json.loads(content)
                
                # 기존 리스트 형태인 경우 (이전 버전과의 호환성)
                if isinstance(data, list):
                    print("[안내] 기존 seen_posts.json을 새 형식으로 변환합니다.")
                    # 기존 데이터는 "종합" 게시판으로 간주
                    new_data = {name: [] for name in BOARDS.keys()}
                    new_data["종합"] = data
                    save_seen(new_data)
                    return new_data
                
                # 딕셔너리 형태인 경우
                return data
        except (json.JSONDecodeError, Exception) as e:
            print(f"[경고] seen_posts 파일 읽기 실패, 기본값 사용: {e}")
            return {name: [] for name in BOARDS.keys()}
    return {name: [] for name in BOARDS.keys()}

def save_seen(seen: dict):
    """각 게시판별로 본 글 ID 저장"""
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)

def fetch_articles(menu_id: int) -> list:
    """특정 게시판의 글 목록 가져오기"""
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
        print(f"[오류] 게시판 {menu_id} 조회 실패: {e}")
        return []

def send_telegram(text: str):
    """텔레그램 메시지 전송"""
    try:
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
    except Exception as e:
        print(f"[오류] 텔레그램 전송 실패: {e}")

def monitor_boards():
    """모든 게시판 모니터링"""
    config = load_config()
    seen = load_seen()
    is_first_run = all(len(v) == 0 for v in seen.values())
    
    total_new = 0
    
    for board_name, board_info in BOARDS.items():
        # 비활성화된 게시판은 건너뛰기
        if not config.get(board_name, True):
            continue
            
        menu_id = board_info["menu_id"]
        print(f"\n[{board_name}] 게시판 확인 중...")
        
        articles = fetch_articles(menu_id)
        if not articles:
            print(f"  ⚠️ 게시글을 가져오지 못했습니다.")
            continue
        
        # 첫 실행: 기존 글만 등록
        if is_first_run:
            seen[board_name] = [str(a["articleId"]) for a in articles]
            print(f"  ✓ {len(articles)}개 기존 글 등록")
            continue
        
        # 새 글 확인
        seen_ids = set(seen.get(board_name, []))
        new_articles = [a for a in articles if str(a["articleId"]) not in seen_ids]
        new_articles.reverse()  # 오래된 글부터 알림
        
        # 새 글 알림
        for a in new_articles:
            aid = str(a["articleId"])
            title = a.get("subject", "(제목 없음)")
            url = f"https://cafe.naver.com/ca-fe/cafes/{CAFE_ID}/articles/{aid}"
            
            header = board_info["header"]
            text = f"{header}\n★ {title}\n<a href=\"{url}\">바로가기</a>"
            send_telegram(text)
            print(f"  📤 전송: {title}")
            
            seen[board_name].append(aid)
            total_new += 1
            time.sleep(0.5)  # 전송 간격
        
        if not new_articles:
            print(f"  ✓ 새 글 없음")
    
    save_seen(seen)
    save_config(config)
    
    if is_first_run:
        print(f"\n✅ 첫 실행 완료. 이후부터 새 글 알림 시작.")
    else:
        print(f"\n✅ 모니터링 완료. 총 {total_new}개 새 글 알림.")

def handle_telegram_commands():
    """텔레그램 명령어 처리 (polling 방식)"""
    last_update_id = 0
    
    print("\n🤖 텔레그램 봇 시작 (명령어 대기 중)")
    print("명령어: /help, /status, /on [게시판], /off [게시판]")
    print("Ctrl+C로 종료\n")
    
    while True:
        try:
            # 새 메시지 확인
            resp = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": last_update_id + 1, "timeout": 30},
                timeout=35
            )
            data = resp.json()
            
            if not data.get("ok"):
                continue
            
            for update in data.get("result", []):
                last_update_id = update["update_id"]
                message = update.get("message", {})
                chat_id = message.get("chat", {}).get("id")
                text = message.get("text", "")
                
                # 설정된 채팅방에서만 처리
                if str(chat_id) != str(TELEGRAM_CHAT):
                    continue
                
                # 명령어 처리
                config = load_config()
                
                if text == "/help":
                    help_text = """📚 <b>네이버 카페 공고 알리미 사용법</b>

<b>🔹 명령어 목록</b>
/help - 이 도움말 보기
/status - 게시판 활성화 상태 확인
/on [게시판] - 특정 게시판 알림 켜기
/off [게시판] - 특정 게시판 알림 끄기

<b>🔹 게시판 목록</b>
• 종합
• 중앙공기업
• 지방공기업
• 인턴계약직
• 학교병원

<b>🔹 사용 예시</b>
/on 종합
/off 인턴계약직
/status

<b>💡 팁</b>
• 모든 게시판은 기본적으로 활성화되어 있습니다
• 필요 없는 게시판은 /off로 끄세요
• 설정은 자동으로 저장됩니다"""
                    send_telegram(help_text)
                
                elif text == "/status":
                    status_text = "📊 <b>게시판 상태</b>\n\n"
                    for name in BOARDS.keys():
                        emoji = "✅" if config.get(name, True) else "❌"
                        status_text += f"{emoji} {name}\n"
                    status_text += "\n사용법:\n/on 게시판명 - 활성화\n/off 게시판명 - 비활성화"
                    send_telegram(status_text)
                
                elif text.startswith("/on ") or text.startswith("/off "):
                    parts = text.split(None, 1)
                    if len(parts) != 2:
                        send_telegram("❌ 사용법: /on 게시판명 또는 /off 게시판명")
                        continue
                    
                    cmd, board = parts
                    enable = (cmd == "/on")
                    
                    if board not in BOARDS:
                        available = ", ".join(BOARDS.keys())
                        send_telegram(f"❌ 알 수 없는 게시판입니다.\n\n사용 가능: {available}")
                        continue
                    
                    config[board] = enable
                    save_config(config)
                    
                    emoji = "✅" if enable else "❌"
                    action = "활성화" if enable else "비활성화"
                    send_telegram(f"{emoji} <b>{board}</b> 게시판 {action}됨")
                    print(f"[명령] {board} 게시판 {action}")
        
        except KeyboardInterrupt:
            print("\n👋 봇 종료")
            break
        except Exception as e:
            print(f"[오류] {e}")
            time.sleep(5)

def main():
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "bot":
        # 봇 모드: 명령어 처리
        handle_telegram_commands()
    else:
        # 모니터링 모드: 새 글 확인
        monitor_boards()

if __name__ == "__main__":
    main()


