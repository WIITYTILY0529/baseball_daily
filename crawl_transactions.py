import re
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone


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
    """MLB 트랜잭션 크롤링 (KST 기준 하루 전 날짜)"""
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    yesterday_kst = now_kst - timedelta(days=1)
    date_str = yesterday_kst.strftime("%Y/%m/%d")
    date_display = yesterday_kst.strftime("%Y-%m-%d")

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
    """이메일 본문 생성 (HTML) - 유형별로 구분, 깔끔한 보고서 스타일"""
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

    # HTML 이메일 본문
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
            .summary-table {{ width: 100%; border-collapse: collapse; margin: 12px 0 24px 0; }}
            .summary-table td {{ padding: 5px 12px; font-size: 13px; }}
            .summary-table td:first-child {{ font-weight: 600; color: #333; }}
            .summary-table td:last-child {{ text-align: right; color: #555; }}
            .section {{ margin-bottom: 20px; }}
            ul {{ padding-left: 18px; margin: 6px 0; }}
            li {{ padding: 3px 0; font-size: 13px; line-height: 1.6; color: #333; }}
            .footer {{ margin-top: 30px; padding-top: 12px; border-top: 1px solid #e0e0e0;
                      font-size: 11px; color: #999; }}
        </style>
    </head>
    <body>
        <h1>MLB Transactions Report</h1>
        <p class="meta">{date_display} | Total {len(transactions)} transactions</p>

        <table class="summary-table">
    """

    for tx_type in type_order:
        if tx_type in grouped:
            html += f"<tr><td>{tx_type}</td><td>{len(grouped[tx_type])}</td></tr>"

    html += "</table>"

    # 유형별 섹션
    for tx_type in type_order:
        if tx_type not in grouped:
            continue
        items = grouped[tx_type]

        html += f"""
        <div class="section">
            <h2>{tx_type} ({len(items)})</h2>
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
        <div class="footer">
            This email was generated automatically. Source: mlb.com/transactions
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
        print("[ERROR] 환경변수가 설정되지 않았습니다:")
        print("  GMAIL_ADDRESS, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL")
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
    transactions, date_display = crawl_mlb_transactions()

    if not transactions:
        subject = f"MLB Transactions ({date_display}) - No Data"
        html_body = f"<p>No transactions recorded on {date_display}.</p>"
    else:
        subject = f"MLB Transactions ({date_display}) - {len(transactions)} moves"
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
