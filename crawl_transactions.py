import re
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta


# 트랜잭션 유형 분류 패턴 (순서 중요 - 먼저 매칭되는 것이 우선)
TRANSACTION_TYPES = [
    ("Trade", r"traded"),
    ("DFA", r"designated .+ for assignment"),
    ("Waiver Claim", r"claimed .+ off waivers"),
    ("Released", r"released"),
    ("Signed (FA)", r"signed free agent"),
    ("Selected Contract", r"selected the contract of"),
    ("Optioned", r"optioned"),
    ("Recalled", r"recalled"),
    ("Placed on IL", r"placed .+ on the .+ injured list"),
    ("Activated from IL", r"activated .+ from the .+injured list"),
    ("Activated", r"activated .+ from the"),
    ("Transferred IL", r"transferred .+ injured list"),
    ("Rehab Assignment", r"rehab assignment"),
    ("Sent Outright", r"sent .+ outright"),
]


def classify_transaction(text):
    """트랜잭션 텍스트를 키워드 패턴으로 분류"""
    text_lower = text.lower()
    for label, pattern in TRANSACTION_TYPES:
        if re.search(pattern, text_lower):
            return label
    return "Other"


def crawl_mlb_transactions():
    """MLB 트랜잭션 크롤링 (하루 전 날짜)"""
    yesterday = datetime.now() - timedelta(days=1)
    date_str = yesterday.strftime("%Y/%m/%d")
    date_display = yesterday.strftime("%Y-%m-%d")

    url = f"https://www.mlb.com/transactions/{date_str}"
    print(f"크롤링 URL: {url}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36"
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"요청 실패: 상태 코드 {response.status_code}")
        return [], date_display

    soup = BeautifulSoup(response.text, "html.parser")
    descriptions = soup.select("table.roster__table td.description")

    if not descriptions:
        print("트랜잭션 데이터를 찾을 수 없습니다.")
        return [], date_display

    transactions = []
    for desc in descriptions:
        text = desc.get_text(separator=" ", strip=True)
        tx_type = classify_transaction(text)
        transactions.append({"type": tx_type, "description": text})

    print(f"총 {len(transactions)}건 크롤링 완료")
    return transactions, date_display


def build_email_body(transactions, date_display):
    """이메일 본문 생성 (HTML) - 유형별로 구분"""
    # 유형별 그룹핑
    grouped = {}
    for t in transactions:
        grouped.setdefault(t["type"], []).append(t)

    # 유형 표시 순서 (중요도순)
    type_order = [
        "Trade", "DFA", "Waiver Claim", "Released", "Signed (FA)",
        "Selected Contract", "Recalled", "Optioned",
        "Placed on IL", "Activated from IL", "Activated", "Transferred IL",
        "Rehab Assignment", "Sent Outright", "Other",
    ]

    type_class_map = {
        "Trade": "trade", "DFA": "dfa", "Released": "dfa",
        "Signed (FA)": "signed", "Waiver Claim": "signed",
        "Placed on IL": "il", "Activated from IL": "il",
        "Activated": "il", "Transferred IL": "il",
        "Optioned": "roster", "Recalled": "roster", "Selected Contract": "roster",
        "Rehab Assignment": "rehab", "Sent Outright": "roster",
    }

    type_emoji = {
        "Trade": "🔄", "DFA": "⚠️", "Waiver Claim": "📋", "Released": "🚪",
        "Signed (FA)": "✍️", "Selected Contract": "📢", "Recalled": "⬆️",
        "Optioned": "⬇️", "Placed on IL": "🏥", "Activated from IL": "💪",
        "Activated": "✅", "Transferred IL": "🔀",
        "Rehab Assignment": "🔧", "Sent Outright": "📤", "Other": "❓",
    }

    # HTML 이메일 본문
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, sans-serif; padding: 20px; color: #333; }}
            h1 {{ color: #002D72; border-bottom: 3px solid #E31937; padding-bottom: 10px; }}
            h2 {{ color: #002D72; margin-top: 30px; border-bottom: 1px solid #ddd; padding-bottom: 6px; }}
            .summary {{ background: #f5f5f5; padding: 15px; border-radius: 8px; margin: 15px 0; }}
            .summary span {{ display: inline-block; margin: 4px 8px; padding: 4px 12px;
                            background: #002D72; color: white; border-radius: 12px; font-size: 13px; }}
            .section {{ margin-bottom: 25px; }}
            ul {{ padding-left: 20px; }}
            li {{ padding: 4px 0; font-size: 14px; line-height: 1.6; }}
            .type-badge {{ display: inline-block; padding: 3px 10px; border-radius: 4px;
                          font-size: 12px; font-weight: bold; color: white; margin-right: 6px; }}
            .trade {{ background: #E31937; }}
            .dfa {{ background: #FF6B35; }}
            .signed {{ background: #28a745; }}
            .il {{ background: #6c757d; }}
            .roster {{ background: #007bff; }}
            .rehab {{ background: #17a2b8; }}
            .other {{ background: #999; }}
        </style>
    </head>
    <body>
        <h1>⚾ MLB 트랜잭션 ({date_display})</h1>
        <p>총 <strong>{len(transactions)}건</strong>의 트랜잭션이 발생했습니다.</p>

        <div class="summary">
            <strong>📊 유형별 요약:</strong><br>
    """

    for tx_type in type_order:
        if tx_type in grouped:
            html += f'<span>{type_emoji.get(tx_type, "")} {tx_type}: {len(grouped[tx_type])}건</span>'

    html += "</div>"

    # 유형별 섹션
    for tx_type in type_order:
        if tx_type not in grouped:
            continue
        items = grouped[tx_type]
        css_class = type_class_map.get(tx_type, "other")
        emoji = type_emoji.get(tx_type, "")

        html += f"""
        <div class="section">
            <h2>{emoji} {tx_type} ({len(items)}건)</h2>
            <ul>
        """
        for t in items:
            desc = re.sub(r"^\d{2}/\d{2}/\d{2}\s*", "", t["description"])
            html += f"<li>{desc}</li>"

        html += """
            </ul>
        </div>
        """

    html += """
        <br>
        <p style="color: #999; font-size: 12px;">
            이 메일은 자동으로 발송되었습니다. (MLB Transactions Crawler)
        </p>
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
        print("❌ 환경변수가 설정되지 않았습니다:")
        print("   GMAIL_ADDRESS, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, recipient, msg.as_string())
        print(f"✅ 이메일 발송 완료 → {recipient}")
        return True
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")
        return False


def main():
    transactions, date_display = crawl_mlb_transactions()

    if not transactions:
        subject = f"⚾ MLB 트랜잭션 ({date_display}) - 데이터 없음"
        html_body = f"<p>{date_display}에 등록된 트랜잭션이 없습니다.</p>"
    else:
        subject = f"⚾ MLB 트랜잭션 ({date_display}) - {len(transactions)}건"
        html_body = build_email_body(transactions, date_display)

    # 환경변수가 있으면 이메일 발송, 없으면 콘솔 출력
    if os.environ.get("GMAIL_ADDRESS"):
        send_email(subject, html_body)
    else:
        print("\n[이메일 미발송 - 환경변수 미설정, 콘솔 출력 모드]")
        print(f"\n제목: {subject}")
        print(f"\n총 {len(transactions)}건")
        for i, t in enumerate(transactions, 1):
            print(f"  {i}. [{t['type']}] {t['description']}")


if __name__ == "__main__":
    main()
