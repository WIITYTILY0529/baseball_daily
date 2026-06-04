import json
import os
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

SENT_FILE = "sent_articles.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def load_sent():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE) as f:
            return set(json.load(f))
    return set()


def save_sent(sent_set):
    with open(SENT_FILE, "w") as f:
        json.dump(sorted(sent_set), f, ensure_ascii=False, indent=2)


def is_recent_date(date_text, days=2):
    """날짜 텍스트가 최근 N일 이내인지 확인"""
    today = datetime.now()
    cutoff = today - timedelta(days=days)

    # "June 02, 2026" or "June 1, 2026" 형식
    for fmt in ("%B %d, %Y", "%B %d,%Y"):
        try:
            dt = datetime.strptime(date_text.strip(), fmt)
            return dt >= cutoff
        except ValueError:
            continue
    return False


def parse_iso_recent(dt_str, days=2):
    """ISO datetime 문자열이 최근 N일 이내인지 확인"""
    today = datetime.now()
    cutoff = today - timedelta(days=days)
    try:
        # "2026-05-27T07:41:11-07:00" -> 날짜 부분만 사용
        dt = datetime.fromisoformat(dt_str)
        return dt.replace(tzinfo=None) >= cutoff
    except (ValueError, TypeError):
        return False


def crawl_bp():
    """Baseball Prospectus 크롤링"""
    url = "https://www.baseballprospectus.com/articles/news/"
    articles = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"[BP] 요청 실패: {resp.status_code}")
            return articles

        soup = BeautifulSoup(resp.text, "html.parser")
        blocks = soup.select(".resultblock")

        for block in blocks:
            title_elem = block.select_one("[title]")
            date_elem = block.select_one(".date")

            if not title_elem or not date_elem:
                continue

            title = title_elem.get("title", "").strip()
            link = title_elem.get("href", "")
            date_text = date_elem.get_text(strip=True)

            if not title or not is_recent_date(date_text):
                continue

            articles.append({"source": "Baseball Prospectus", "title": title, "link": link, "date": date_text})

    except Exception as e:
        print(f"[BP] 에러: {e}")

    print(f"[BP] {len(articles)}건 수집")
    return articles


def crawl_fangraphs():
    """Fangraphs 크롤링"""
    url = "https://www.fangraphs.com/blog-roll"
    articles = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"[FG] 요청 실패: {resp.status_code}")
            return articles

        soup = BeautifulSoup(resp.text, "html.parser")
        date_sections = soup.select("h2[class*='section-title']")

        for section in date_sections:
            date_text = section.get_text(strip=True)

            if not is_recent_date(date_text):
                continue

            # 다음 형제 요소들에서 기사 제목 추출 (다음 h2 전까지)
            sibling = section.find_next_sibling()
            while sibling and sibling.name != "h2":
                headlines = sibling.select("h3[class*='blog-headline']")
                for h3 in headlines:
                    a_tag = h3.find("a")
                    if a_tag:
                        title = a_tag.get_text(strip=True)
                        link = a_tag.get("href", "")
                        if title:
                            articles.append({"source": "Fangraphs", "title": title, "link": link, "date": date_text})
                sibling = sibling.find_next_sibling()

    except Exception as e:
        print(f"[FG] 에러: {e}")

    print(f"[FG] {len(articles)}건 수집")
    return articles


def crawl_driveline():
    """Driveline Baseball 크롤링"""
    url = "https://www.drivelinebaseball.com/blog/"
    articles = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"[DL] 요청 실패: {resp.status_code}")
            return articles

        soup = BeautifulSoup(resp.text, "html.parser")
        posts = soup.select(".slider-post__header")

        for post in posts:
            title_elem = post.select_one(".slider-post__title a")
            time_elem = post.select_one("time.entry-date")

            if not title_elem or not time_elem:
                continue

            title = title_elem.get_text(strip=True)
            link = title_elem.get("href", "")
            dt_str = time_elem.get("datetime", "")
            date_display = time_elem.get_text(strip=True)

            if not title or not parse_iso_recent(dt_str):
                continue

            articles.append({"source": "Driveline", "title": title, "link": link, "date": date_display})

    except Exception as e:
        print(f"[DL] 에러: {e}")

    print(f"[DL] {len(articles)}건 수집")
    return articles


def build_email_body(articles):
    """이메일 본문 생성 - 소스별 구분"""
    grouped = {}
    for a in articles:
        grouped.setdefault(a["source"], []).append(a)

    today = datetime.now().strftime("%Y-%m-%d")

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, Arial, sans-serif; padding: 24px; color: #1a1a1a;
                   max-width: 700px; margin: 0 auto; line-height: 1.5; }}
            h1 {{ font-size: 20px; color: #1a1a1a; border-bottom: 2px solid #002D72;
                 padding-bottom: 8px; margin-bottom: 16px; font-weight: 600; }}
            h2 {{ font-size: 15px; color: #002D72; margin: 24px 0 8px 0;
                 padding-bottom: 4px; border-bottom: 1px solid #e0e0e0; font-weight: 600; }}
            .meta {{ font-size: 13px; color: #555; margin-bottom: 20px; }}
            ul {{ padding-left: 18px; margin: 6px 0; }}
            li {{ padding: 4px 0; font-size: 13px; line-height: 1.6; color: #333; }}
            .date-tag {{ font-size: 11px; color: #888; margin-left: 6px; }}
            .footer {{ margin-top: 30px; padding-top: 12px; border-top: 1px solid #e0e0e0;
                      font-size: 11px; color: #999; }}
        </style>
    </head>
    <body>
        <h1>Baseball Articles Report</h1>
        <p class="meta">{today} | {len(articles)} new articles</p>
    """

    source_order = ["Baseball Prospectus", "Fangraphs", "Driveline"]
    for source in source_order:
        if source not in grouped:
            continue
        items = grouped[source]
        html += f"<h2>{source} ({len(items)})</h2><ul>"
        for a in items:
            if a.get("link"):
                html += f'<li><a href="{a["link"]}" style="color: #002D72; text-decoration: none;">{a["title"]}</a> <span class="date-tag">{a["date"]}</span></li>'
            else:
                html += f'<li>{a["title"]} <span class="date-tag">{a["date"]}</span></li>'
        html += "</ul>"

    html += """
        <div class="footer">
            This email was generated automatically.
        </div>
    </body>
    </html>
    """
    return html


def send_email(subject, html_body):
    """Gmail SMTP로 이메일 발송"""
    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("RECIPIENT_EMAIL")

    if not all([gmail_address, gmail_password, recipient]):
        print("[ERROR] 환경변수 미설정: GMAIL_ADDRESS, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL")
        return False

    recipients = [r.strip() for r in recipient.split(",")]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, recipients, msg.as_string())
        print(f"[OK] 이메일 발송 완료 -> {recipients}")
        return True
    except Exception as e:
        print(f"[FAIL] 이메일 발송 실패: {e}")
        return False


def main():
    # 1. 크롤링
    all_articles = []
    all_articles.extend(crawl_bp())
    all_articles.extend(crawl_fangraphs())
    all_articles.extend(crawl_driveline())

    # 2. 중복 제거 (이미 보낸 기사 제외)
    sent = load_sent()
    new_articles = [a for a in all_articles if a["title"] not in sent]

    print(f"\n전체 {len(all_articles)}건 중 신규 {len(new_articles)}건")

    if not new_articles:
        print("새 기사 없음. 이메일 미발송.")
        return

    # 3. 이메일 발송
    today = datetime.now().strftime("%Y-%m-%d")
    subject = f"Baseball Articles ({today}) - {len(new_articles)} new"
    html_body = build_email_body(new_articles)

    if os.environ.get("GMAIL_ADDRESS"):
        send_email(subject, html_body)
    else:
        print(f"\n[콘솔 출력 모드]")
        print(f"제목: {subject}\n")
        for a in new_articles:
            print(f"  [{a['source']}] {a['title']} ({a['date']})")

    # 4. 보낸 기사 기록 업데이트
    for a in new_articles:
        sent.add(a["title"])
    save_sent(sent)


if __name__ == "__main__":
    main()
