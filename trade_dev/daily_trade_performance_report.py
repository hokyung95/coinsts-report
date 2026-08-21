"""
========================================================================================
 [모듈 명]: trade_dev/daily_trade_performance_report.py
 [구현 목적]:
   - 매일 00시 30분 전일(Yesterday) 매매 수익 및 계좌 포트폴리오 종합 분석 리포트 생성
   - 계좌 기준 정보: 총 자본금 250만원(2,500,000원), 1회 매수 20만원(200,000원)
   - DB (coinsts.db) 매수/매도 이력 및 계좌 포트폴리오 집계:
     * 전체 계좌 총 평가금액 (현금 + 코인 평가금액) 및 계좌 총 수익률 (%)
     * 전일 매도 승률 (Win Rate), 실현 손익 (Realized PnL KRW), 평균 수익률 (%)
     * 전일 매수 건수 및 투입 금액
     * 현재 보유 중인 종목 (HOLDING) 개수, 매수 수량, 진입가, 평가 손익 (%)
   - Matplotlib + PdfPages 기반 PDF 보고서 생성:
     `trade_dev/report/daily_trade_performance_YYYYMMDD.pdf`
   - Google Drive 연동 자동 업로드 (hhokyung@gmail.com / report_daily 폴더)
========================================================================================
"""

import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from datetime import datetime, timedelta

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# trade_dev 및 상위 루트 모듈 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import db_manager

def generate_daily_trade_performance_report(target_date_str=None, pdf_path=None):
    """
    전일 매매 성과 분석 PDF 보고서 생성 및 구글 드라이브 업로드
    """
    if target_date_str is None:
        target_date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    db_manager.init_db()
    summary = db_manager.get_daily_performance_summary(target_date_str)
    acc = db_manager.get_account_portfolio_summary()
    
    sold_summary = summary['sold_summary']
    buy_summary = summary['buy_summary']
    sold_trades = summary['sold_trades']
    holding_trades = acc['holding_positions']
    win_rate = summary['win_rate']

    if pdf_path is None:
        save_dir = os.path.join(current_dir, "report")
        os.makedirs(save_dir, exist_ok=True)
        filename = f"daily_trade_performance_{target_date_str.replace('-', '')}.pdf"
        pdf_path = os.path.join(save_dir, filename)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(pdf_path)), exist_ok=True)

    print(f"\n[일일 매매 수익 분석 리포트] {target_date_str} 기준 산출 중...", flush=True)
    print(f" - 총 자본금: {acc['initial_capital']:,.0f}원 | 가용 현금: {acc['available_cash_krw']:,.0f}원")
    print(f" - 총 계좌 평가액: {acc['total_account_eval_krw']:,.0f}원 (계좌 총 수익률: {acc['total_account_return_pct']:+.2f}%)")
    print(f" - 매도 완료 건수: {sold_summary['total_sold_count']}건 (승률: {win_rate}%) | 실현 손익: {sold_summary['total_pnl_krw']:+,.0f}원")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with PdfPages(pdf_path) as pdf:
        fig, ax = plt.subplots(figsize=(12, 8.5))
        ax.axis('off')

        # 1. 제목 및 서브타이틀
        title_text = f"CoinSTS 일일 매매 성과 및 계좌 수익 분석 리포트 [{target_date_str}]"
        subtitle_text = f"발행 일시: {now_str} | 대상 일자: {target_date_str} | 총 자본금: 250만원 (1회 매수: 20만원)"
        ax.text(0.5, 0.96, title_text, fontsize=15, fontweight='bold', ha='center', va='top', color='#1b4f72')
        ax.text(0.5, 0.92, subtitle_text, fontsize=9.5, color='gray', ha='center', va='top')

        # 2. 계좌 총괄 성과 요약 박스
        metrics_text = (
            f" [계좌 자본금 & 포트폴리오 총괄 요약 대시보드]\n"
            f" ----------------------------------------------------------------------\n"
            f" - 총 계좌 자본금   : {acc['initial_capital']:,.0f} 원   (1회 매수 설정 금액: {acc['buy_amount_per_coin']:,.0f}원)\n"
            f" - 가용 현금 잔액   : {acc['available_cash_krw']:,.0f} 원   (보유코인 매수원금: {acc['holding_invested_krw']:,.0f}원)\n"
            f" - 총 계좌 평가금액 : {acc['total_account_eval_krw']:,.0f} 원   (계좌 총 수익률: {acc['total_account_return_pct']:+.2f} % / 손익: {acc['total_account_pnl_krw']:+,.0f}원)\n"
            f" - 전일 매도 청산   : {sold_summary['total_sold_count']} 건   (승률: {win_rate:.1f}% / 실현손익: {sold_summary['total_pnl_krw']:+,.0f}원)\n"
            f" - 전일 신규 매수   : {buy_summary['new_buy_count']} 건   (투입 원화: {buy_summary['new_buy_krw']:,.0f}원)\n"
            f" - 현재 보유 코인 수 : {acc['holding_count']} 개 종목"
        )
        ax.text(0.05, 0.88, metrics_text, fontsize=10.0, family='monospace', bbox=dict(boxstyle='round,pad=0.6', facecolor='#eaf2f8', edgecolor='#2980b9', alpha=0.9), va='top')

        # 3. 매도 청산 종목 내역 표 (Sold Trades Table)
        ax.text(0.05, 0.64, "■ 전일 매도 청산 거래 내역 (Sold History)", fontsize=11, fontweight='bold', color='#154360', va='top')

        col_labels_sold = ['마켓코드', '한글명', '매수가(원)', '매도가(원)', '투입원화(원)', '정산원화(원)', '수익률(%)', '매도 사유', '매수일시', '매도일시']
        
        if sold_trades:
            table_rows_sold = [
                [
                    t['market'], t['korean_name'], f"{t['buy_price']:,.1f}", f"{t['sell_price']:,.1f}",
                    f"{t['buy_amount_krw']:,.0f}", f"{t['sell_amount_krw']:,.0f}", f"{t['pnl_pct']:+.2f}%",
                    t['exit_reason'], t['created_at'][5:16], t['updated_at'][5:16]
                ] for t in sold_trades[:10]
            ]
        else:
            table_rows_sold = [["-" for _ in col_labels_sold]]
            table_rows_sold[0][1] = "전일 매도 청산 내역 없음"

        table_sold = ax.table(
            cellText=table_rows_sold,
            colLabels=col_labels_sold,
            cellLoc='center',
            loc='center',
            bbox=[0.05, 0.36, 0.90, 0.25]
        )
        table_sold.auto_set_font_size(False)
        table_sold.set_fontsize(7.5)

        for col_i in range(len(col_labels_sold)):
            cell = table_sold[(0, col_i)]
            cell.set_facecolor('#2980b9')
            cell.set_text_props(color='white', fontweight='bold')

        # 4. 현재 보유 종목 표 (Holding Positions Table - 수량 및 매수금액 20만원 표기)
        ax.text(0.05, 0.29, f"■ 현재 보유 중인 코인 목록 (Active Holding Positions - 총 {len(holding_trades)}개 종목)", fontsize=11, fontweight='bold', color='#154360', va='top')
        
        col_labels_holding = ['마켓코드', '한글명', '진입가(원)', '매수금액(원)', '보유 코인수량', '구분', '매수일시']
        if holding_trades:
            table_rows_holding = [
                [
                    h['market'], h['korean_name'], f"{float(h['buy_price']):,.1f}", f"{float(h['buy_amount_krw']):,.0f}",
                    f"{float(h['buy_volume']):,.4f}", "모의매수" if h['is_dry_run'] else "실전매수", h['created_at'][5:16]
                ] for h in holding_trades[:10]
            ]
        else:
            table_rows_holding = [["-" for _ in col_labels_holding]]
            table_rows_holding[0][1] = "현재 보유 중인 코인 없음"

        table_holding = ax.table(
            cellText=table_rows_holding,
            colLabels=col_labels_holding,
            cellLoc='center',
            loc='center',
            bbox=[0.05, 0.05, 0.90, 0.22]
        )
        table_holding.auto_set_font_size(False)
        table_holding.set_fontsize(7.5)

        for col_i in range(len(col_labels_holding)):
            cell = table_holding[(0, col_i)]
            cell.set_facecolor('#16a085')
            cell.set_text_props(color='white', fontweight='bold')

        plt.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)

    full_pdf_path = os.path.abspath(pdf_path)
    print(f" -> 전일 매매 성과 PDF 생성 완료: '{full_pdf_path}'", flush=True)

    # Google Drive 업로드 (report_daily 폴더)
    gdrive_url = None
    try:
        from upload_to_gdrive import upload_pdf_to_gdrive
        gdrive_url = upload_pdf_to_gdrive(full_pdf_path, folder_name="report_daily", user_email="hhokyung@gmail.com")
        if gdrive_url:
            print(f" -> Google Drive 업로드 완료 링크: {gdrive_url}", flush=True)
    except Exception as e:
        print(f"Google Drive 업로드 중 오류 발생: {e}", flush=True)

    # 이메일 알림 발송 (hhokyung@gmail.com)
    try:
        import email_notifier
        email_notifier.send_daily_performance_email(acc_summary=acc, sold_summary=summary, pdf_path=full_pdf_path, gdrive_url=gdrive_url, recipient_email="hhokyung@gmail.com")
    except Exception as e:
        print(f"이메일 알림 발송 중 오류: {e}", flush=True)

    return full_pdf_path

if __name__ == "__main__":
    generate_daily_trade_performance_report()
