"""
========================================================================================
 [모듈 명]: trade_dev/email_notifier.py
 [구현 목적]:
   - 매시간 매수/매도 트레이딩 결과 및 매일 00:30 수익 분석 보고서를 hhokyung@gmail.com 으로 이메일 발송
   - Gmail SMTP (smtp.gmail.com:587) 사용
   - smtp_config.json 설정이 미완료된 경우 trade_dev/email_logs/ 에 이메일 알림 보관
========================================================================================
"""

import os
import sys
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(CURRENT_DIR, "smtp_config.json")
LOG_DIR = os.path.join(CURRENT_DIR, "email_logs")

def load_smtp_config():
    """SMTP 설정 파일 로드"""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                sender = data.get('sender_email', '').strip()
                password = data.get('sender_app_password', '').strip()
                if sender and password and password != "YOUR_GMAIL_APP_PASSWORD":
                    return data
        except Exception as e:
            print(f"SMTP 설정 로드 에러: {e}")
    return None

def send_email(subject, body_html, attachment_path=None, recipient_email="hhokyung@gmail.com"):
    """
    이메일 발송 처리
    - SMTP 설정이 완료된 경우 실제 Gmail로 발송
    - 설정 전일 경우 trade_dev/email_logs/ 폴더에 백업 저장
    """
    config = load_smtp_config()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if config is not None:
        smtp_server = config.get('smtp_server', 'smtp.gmail.com')
        smtp_port = int(config.get('smtp_port', 587))
        sender_email = config.get('sender_email', 'hhokyung@gmail.com')
        sender_password = config.get('sender_app_password', '')
        to_email = recipient_email or config.get('recipient_email', 'hhokyung@gmail.com')

        try:
            msg = MIMEMultipart()
            msg['From'] = f"CoinSTS Trader <{sender_email}>"
            msg['To'] = to_email
            msg['Subject'] = subject

            msg.attach(MIMEText(body_html, 'html', 'utf-8'))

            # 첨부파일 처리
            if attachment_path and os.path.exists(attachment_path):
                filename = os.path.basename(attachment_path)
                with open(attachment_path, 'rb') as f:
                    part = MIMEApplication(f.read(), Name=filename)
                    part['Content-Disposition'] = f'attachment; filename="{filename}"'
                    msg.attach(part)

            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
            server.quit()

            print(f" ★ [이메일 발송 성공] '{to_email}' -> 제목: {subject}", flush=True)
            return True
        except Exception as e:
            print(f"❌ 이메일 발송 실패: {e}", flush=True)

    # SMTP 설정 미완료 또는 실패 시 로컬 로그 보관
    os.makedirs(LOG_DIR, exist_ok=True)
    log_filename = f"email_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    log_file_path = os.path.join(LOG_DIR, log_filename)
    try:
        with open(log_file_path, 'w', encoding='utf-8') as f:
            f.write(f"<!-- Subject: {subject} | To: {recipient_email} | Time: {now_str} -->\n")
            f.write(body_html)
        print(f" ℹ️ [이메일 알림 보관 완료] Gmail 앱 비밀번호 설정 전 상태로 로컬에 보관되었습니다. ({log_file_path})", flush=True)
    except Exception:
        pass
    return False

def send_hourly_trade_email(sold_items, bought_items, gdrive_url=None, recipient_email="hhokyung@gmail.com"):
    """
    시간별 매도/매수 트레이딩 수행 결과 이메일 알림
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"[CoinSTS 매매 알림] {datetime.now().strftime('%m/%d %H:%M')} - 매도 {len(sold_items)}건, 매수 {len(bought_items)}건 완료"

    sold_rows_html = ""
    if sold_items:
        for s in sold_items:
            sold_rows_html += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{s['korean_name']} ({s['market']})</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{s['buy_price']:,.1f} 원</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{s['sell_price']:,.1f} 원</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: center; color: {'red' if s['pnl_pct']>=0 else 'blue'}; fontweight: bold;">{s['pnl_pct']:+.2f} %</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{s['exit_reason']}</td>
            </tr>
            """
    else:
        sold_rows_html = "<tr><td colspan='5' style='padding: 8px; text-align: center; color: gray;'>금회 매도 청산 코인 없음</td></tr>"

    bought_rows_html = ""
    if bought_items:
        for b in bought_items:
            bought_rows_html += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{b['korean_name']} ({b['market']})</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{b['buy_price']:,.1f} 원</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{b['buy_amount_krw']:,.0f} 원</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{b['buy_volume']:,.4f} 코인</td>
            </tr>
            """
    else:
        bought_rows_html = "<tr><td colspan='4' style='padding: 8px; text-align: center; color: gray;'>금회 신규 매수 코인 없음 (중복 또는 가용 잔액)</td></tr>"

    gdrive_link_html = f'<p><b>📄 Google Drive PDF 보고서:</b> <a href="{gdrive_url}" target="_blank">{gdrive_url}</a></p>' if gdrive_url else ""

    html_content = f"""
    <div style="font-family: '맑은 고딕', sans-serif; max-width: 700px; margin: 0 auto; border: 1px solid #2980b9; padding: 20px; border-radius: 8px;">
        <h2 style="color: #1b4f72; border-bottom: 2px solid #2980b9; padding-bottom: 10px;">CoinSTS시간별 매매 처리 알림 리포트</h2>
        <p style="color: gray; font-size: 13px;">실행 일시: {now_str} | 수신자: {recipient_email}</p>
        
        <h3 style="color: #c0392b; margin-top: 20px;">■ 금회 매도 청산 내역 ({len(sold_items)}건)</h3>
        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
                <tr style="background-color: #f2f4f4;">
                    <th style="padding: 8px; border: 1px solid #ddd;">코인명</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">매수가</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">매도가</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">수익률</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">매도 사유</th>
                </tr>
            </thead>
            <tbody>
                {sold_rows_html}
            </tbody>
        </table>

        <h3 style="color: #27ae60; margin-top: 25px;">■ 금회 신규 매수 내역 ({len(bought_items)}건 / 20만원 기준)</h3>
        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
                <tr style="background-color: #f2f4f4;">
                    <th style="padding: 8px; border: 1px solid #ddd;">코인명</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">매수가</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">투입 금액</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">체결 코인 수량</th>
                </tr>
            </thead>
            <tbody>
                {bought_rows_html}
            </tbody>
        </table>

        <div style="margin-top: 25px; background-color: #eaf2f8; padding: 15px; border-radius: 5px;">
            {gdrive_link_html}
        </div>
        <p style="font-size: 11px; color: gray; margin-top: 20px; text-align: center;">본 메일은 CoinSTS 자동 트레이딩 시스템에서 자동으로 발송되었습니다.</p>
    </div>
    """
    return send_email(subject, html_content, recipient_email=recipient_email)

def send_daily_performance_email(acc_summary, sold_summary, pdf_path=None, gdrive_url=None, recipient_email="hhokyung@gmail.com"):
    """
    매일 00:30 전일 매매 수익 분석 결과 이메일 알림
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target_date = sold_summary.get('target_date', datetime.now().strftime("%Y-%m-%d"))
    subject = f"[CoinSTS 일일 수익 분석 보고서] {target_date} - 계좌 총평가액 {acc_summary['total_account_eval_krw']:,.0f}원 (수익률 {acc_summary['total_account_return_pct']:+.2f}%)"

    gdrive_link_html = f'<p><b>📄 Google Drive PDF 수익 분석 보고서:</b> <a href="{gdrive_url}" target="_blank">{gdrive_url}</a></p>' if gdrive_url else ""

    html_content = f"""
    <div style="font-family: '맑은 고딕', sans-serif; max-width: 700px; margin: 0 auto; border: 1px solid #16a085; padding: 20px; border-radius: 8px;">
        <h2 style="color: #0e6251; border-bottom: 2px solid #16a085; padding-bottom: 10px;">CoinSTS 일일 매매 수익 종합 분석 보고서</h2>
        <p style="color: gray; font-size: 13px;">발행 일시: {now_str} | 대상 일자: {target_date} | 수신자: {recipient_email}</p>
        
        <div style="background-color: #e8f8f5; border: 1px solid #a3e4d7; padding: 15px; border-radius: 6px; margin-top: 15px;">
            <h3 style="margin-top: 0; color: #117a65;">■ 계좌 포트폴리오 대시보드 (자본금 250만원 기준)</h3>
            <ul style="font-size: 14px; line-height: 1.8; color: #2c3e50;">
                <li><b>총 자본금:</b> {acc_summary['initial_capital']:,.0f} 원</li>
                <li><b>가용 현금 잔액:</b> {acc_summary['available_cash_krw']:,.0f} 원</li>
                <li><b>총 계좌 평가금액:</b> <span style="font-size: 16px; color: {'red' if acc_summary['total_account_pnl_krw']>=0 else 'blue'}; fontweight: bold;">{acc_summary['total_account_eval_krw']:,.0f} 원</span> (수익률: {acc_summary['total_account_return_pct']:+.2f} %)</li>
                <li><b>전일 매도 청산 건수:</b> {sold_summary.get('sold_summary', {}).get('total_sold_count', 0)} 건 (승률: {sold_summary.get('win_rate', 0):.1f} %)</li>
                <li><b>현재 보유 코인 수:</b> {acc_summary['holding_count']} 개 종목 (매수원금: {acc_summary['holding_invested_krw']:,.0f}원)</li>
            </ul>
        </div>

        <div style="margin-top: 25px; background-color: #f4f6f7; padding: 15px; border-radius: 5px;">
            {gdrive_link_html}
        </div>
        <p style="font-size: 11px; color: gray; margin-top: 20px; text-align: center;">본 메일은 CoinSTS 자동 트레이딩 시스템에서 매일 00:30에 자동으로 발송됩니다.</p>
    </div>
    """
    return send_email(subject, html_content, attachment_path=pdf_path, recipient_email=recipient_email)

if __name__ == "__main__":
    print("이메일 알림 모듈 테스트")
