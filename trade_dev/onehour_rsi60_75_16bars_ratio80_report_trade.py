"""
========================================================================================
 [모듈 명]: trade_dev/onehour_rsi60_75_16bars_ratio80_report_trade.py
 [구현 목적]:
   - 빗썸 거래 전체 원화(KRW) 마켓 코인을 대상으로 1시간봉 스캔
   - [포착 조건]:
     ① 최근 16개 1시간봉 중 60 <= RSI <= 75 인 봉 수 >= 13개 (80% 이상)
     ② 직전 3개봉(N-18~N-16) RSI <= 60.0 모두 만족
   - [트레이딩 실행 프로세스 순서]:
     1) [1/4] 빗썸 전체 마켓 1시간봉/일봉 시계열 및 기술 지표 수집
     2) [2/4] PHASE 1: 매수 전 보유 종목 매도 선(先)처리 (bithumb_trader.process_auto_sells)
              - ① 고가/종가 >= +50.0% 익절
              - ② 종가 < 일목 전환선(9) 하회 매도
              - ③ 저가 <= -3.0% 스탑로스 청산
     3) [3/4] PHASE 2: 신규 포착 코인 중복 검증 & 후(後)매수 집행 (bithumb_trader.process_auto_buys)
              - 이미 HOLDING 중인 코인 중복 매수 방지 및 DB 저장
     4) [4/4] PHASE 3: 듀얼 3단 시각화 PDF 리포트 생성 및 Google Drive 자동 업로드
   - 저장 위치: trade_dev/report/onehour_rsi60_75_16bars_ratio80_report_YYYYMMDDHHMMSS.pdf
========================================================================================
"""

import requests
import numpy as np
import pandas as pd
import time
import os
import sys
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Matplotlib 한글 폰트 설정
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
import bithumb_trader

def get_krw_markets():
    """빗썸 원화(KRW) 마켓 목록 조회"""
    url = "https://api.bithumb.com/v1/market/all"
    headers = {"accept": "application/json"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        markets = response.json()
        return [
            {
                'market': m['market'],
                'korean_name': m.get('korean_name', m['market']),
                'english_name': m.get('english_name', m['market'])
            }
            for m in markets if m['market'].startswith('KRW-')
        ]
    except Exception as e:
        print(f"마켓 목록 조회 에러: {e}")
        return []

def calc_mid_point(high, low, window):
    return (high.rolling(window=window).max() + low.rolling(window=window).min()) / 2

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))

def calc_macd(series, short=12, long=26, signal=9):
    ema_short = series.ewm(span=short, adjust=False).mean()
    ema_long = series.ewm(span=long, adjust=False).mean()
    macd = ema_short - ema_long
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    macd_hist = macd - macd_signal
    return macd, macd_signal, macd_hist

def process_candle_df(data):
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
        
    df['Close'] = df['trade_price']
    df['Volume'] = df['candle_acc_trade_volume'].astype(float) if 'candle_acc_trade_volume' in df.columns else 0.0
    
    # 일목균형표
    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 9)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 26)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(26)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 52).shift(26)
    
    # RSI & MACD
    df['RSI'] = calc_rsi(df['Close'], 14)
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calc_macd(df['Close'])
    return df

def fetch_and_analyze_single_coin(m, count=200):
    market_code = m['market']
    korean_name = m['korean_name']
    english_name = m['english_name']
    
    headers = {"accept": "application/json"}
    url_1h = f"https://api.bithumb.com/v1/candles/minutes/60?market={market_code}&count={count}"
    url_daily = f"https://api.bithumb.com/v1/candles/days?market={market_code}&count={count}"
    
    try:
        res_1h = requests.get(url_1h, headers=headers, timeout=5)
        if res_1h.status_code == 200:
            data_1h = res_1h.json()
            if isinstance(data_1h, list) and len(data_1h) >= 40:
                df_1h = process_candle_df(data_1h)
                
                recent_16_rsi = df_1h['RSI'].iloc[-16:]
                valid_rsi_mask = (recent_16_rsi >= 60.0) & (recent_16_rsi <= 75.0)
                rsi_60_75_count = int(valid_rsi_mask.sum())
                rsi_60_75_ratio = (rsi_60_75_count / 16.0) * 100.0
                
                prev_3_rsi = df_1h['RSI'].iloc[-19:-16]
                prev_3_low_rsi_valid = (prev_3_rsi <= 60.0).all()
                
                last_1h = df_1h.iloc[-1]
                c_now = float(last_1h['Close'])
                h_now = float(last_1h['high_price'])
                l_now = float(last_1h['low_price'])
                t_now = float(last_1h['ConversionLine']) if not pd.isna(last_1h['ConversionLine']) else c_now
                
                is_captured = (rsi_60_75_count >= 13) and prev_3_low_rsi_valid
                
                df_daily = None
                rsi_daily_val = 0.0
                tenkan_daily_val = 0.0
                
                if is_captured:
                    res_daily = requests.get(url_daily, headers=headers, timeout=5)
                    if res_daily.status_code == 200:
                        data_daily = res_daily.json()
                        if isinstance(data_daily, list) and len(data_daily) >= 30:
                            df_daily = process_candle_df(data_daily)
                            last_daily = df_daily.iloc[-1]
                            rsi_daily_val = round(last_daily['RSI'], 1) if not pd.isna(last_daily['RSI']) else 0.0
                            tenkan_daily_val = round(last_daily['ConversionLine'], 2) if not pd.isna(last_daily['ConversionLine']) else 0.0

                is_above_tenkan = (c_now >= t_now)
                tenkan_diff_pct = ((c_now - t_now) / t_now * 100.0) if t_now > 0 else 0.0

                coin_info = {
                    'market': market_code,
                    'korean_name': korean_name,
                    'english_name': english_name,
                    'close_price': c_now,
                    'high_price': h_now,
                    'low_price': l_now,
                    'rsi_60_75_count': rsi_60_75_count,
                    'rsi_60_75_ratio': round(rsi_60_75_ratio, 1),
                    'prev_3_max_rsi': round(prev_3_rsi.max(), 1) if len(prev_3_rsi) > 0 else 0.0,
                    'is_above_tenkan': is_above_tenkan,
                    'tenkan_diff_pct': round(tenkan_diff_pct, 2),
                    'rsi_1h': round(last_1h['RSI'], 1) if not pd.isna(last_1h['RSI']) else 0.0,
                    'tenkan_1h': round(t_now, 2),
                    'rsi_daily': rsi_daily_val,
                    'tenkan_daily': tenkan_daily_val,
                    'is_captured': is_captured,
                    'df_1h': df_1h,
                    'df_daily': df_daily
                }
                return coin_info
    except Exception:
        pass
    return None

def plot_3tier_chart(axes_col, df, title_prefix, time_frame_label):
    ax_p, ax_m, ax_r = axes_col
    x = range(len(df))
    
    ax_v = ax_p.twinx()
    v_colors = ['#c0392b' if df['Close'].iloc[i] >= (df['Close'].iloc[i-1] if i > 0 else df['Close'].iloc[i]) else '#2980b9' for i in range(len(df))]
    ax_v.bar(x, df['Volume'], color=v_colors, alpha=0.65, width=0.75)
    ax_v.set_ylim(0, df['Volume'].max() * 3.8 if df['Volume'].max() > 0 else 1)
    ax_v.set_ylabel("거래량", fontsize=7.5, color='gray')
    ax_v.tick_params(axis='y', labelsize=6.5, labelcolor='gray')
    ax_v.grid(False)
    
    ax_p.set_zorder(ax_v.get_zorder() + 1)
    ax_p.patch.set_visible(False)
    
    ax_p.plot(x, df['Close'], label='종가', color='black', linewidth=1.3)
    ax_p.plot(x, df['ConversionLine'], label='전환선(9)', color='#e31a1c', linewidth=1.2)
    ax_p.plot(x, df['BaseLine'], label='기준선(26)', color='#1f78b4', linewidth=1.3)
    ax_p.plot(x, df['Span1'], label='선행1(26)', color='#33a02c', linewidth=0.8, linestyle='--')
    ax_p.plot(x, df['Span2'], label='선행2(52)', color='#ff7f00', linewidth=0.8, linestyle='--')
    
    ax_p.fill_between(x, df['Span1'], df['Span2'], where=(df['Span1'] >= df['Span2']), color='#b2df8a', alpha=0.35)
    ax_p.fill_between(x, df['Span1'], df['Span2'], where=(df['Span1'] < df['Span2']), color='#fb9a99', alpha=0.35)
    
    ax_p.set_title(f"{title_prefix} - [{time_frame_label} 일목균형표(9,26) & 거래량]", fontsize=9.5, fontweight='bold', color='#1b4f72', pad=3)
    ax_p.set_ylabel("가격 (KRW)", fontsize=8)
    ax_p.tick_params(axis='y', labelsize=7.5)
    ax_p.legend(loc='upper left', fontsize=7, framealpha=0.85, ncol=3)
    ax_p.grid(True, linestyle=':', alpha=0.5)
    
    ax_m.plot(x, df['MACD'], label='MACD(12,26)', color='#1f78b4', linewidth=1.0)
    ax_m.plot(x, df['MACD_Signal'], label='Signal(9)', color='#e31a1c', linewidth=1.0, linestyle='--')
    hist_colors = ['#e31a1c' if v >= 0 else '#1f78b4' for v in df['MACD_Hist']]
    ax_m.bar(x, df['MACD_Hist'], color=hist_colors, alpha=0.55, width=0.75)
    ax_m.axhline(0, color='gray', linestyle=':', linewidth=0.7)
    ax_m.set_ylabel("MACD", fontsize=8)
    ax_m.tick_params(axis='y', labelsize=7.5)
    ax_m.legend(loc='upper left', fontsize=6.5, framealpha=0.85, ncol=3)
    ax_m.grid(True, linestyle=':', alpha=0.5)
    
    ax_r.plot(x, df['RSI'], label='RSI(14)', color='#8e44ad', linewidth=1.2)
    ax_r.axhspan(60, 75, color='#f39c12', alpha=0.25)
    ax_r.axhline(75, color='#e31a1c', linestyle='--', linewidth=0.8)
    ax_r.axhline(60, color='#d35400', linestyle=':', linewidth=0.8)
    ax_r.axhline(30, color='#1f78b4', linestyle='--', linewidth=0.8)
    ax_r.set_ylim(0, 100)
    ax_r.set_ylabel("RSI", fontsize=8)
    ax_r.tick_params(axis='x', labelsize=7.5)
    ax_r.tick_params(axis='y', labelsize=7.5)
    ax_r.legend(loc='upper left', fontsize=6.5, framealpha=0.85, ncol=4)
    ax_r.grid(True, linestyle=':', alpha=0.5)

def run_onehour_trade_pipeline(pdf_path=None, max_workers=8, is_dry_run=True):
    """
    통합 스캐너 및 트레이딩 연동 파이프라인
    """
    db_manager.init_db()

    base_dir = current_dir
    if pdf_path is None:
        save_dir = os.path.join(base_dir, "report")
        os.makedirs(save_dir, exist_ok=True)
        filename = f"onehour_rsi60_75_16bars_ratio80_report_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_path = os.path.join(save_dir, filename)

    markets = get_krw_markets()
    if not markets:
        print("KRW 마켓 목록을 불러올 수 없습니다.")
        return None

    print(f"\n[1/4] 빗썸 {len(markets)}개 원화 코인 시계열 수집 중 (스레드: {max_workers})...", flush=True)
    
    all_coins_dict = {}
    captured_list = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_and_analyze_single_coin, m): m for m in markets}
        for future in as_completed(futures):
            res = future.result()
            if res:
                all_coins_dict[res['market']] = res
                if res['is_captured']:
                    captured_list.append(res)
                    # DB에 포착 신호 저장
                    db_manager.save_captured_signal(res)
                    state_str = "전환선 상위" if res['is_above_tenkan'] else "전환선 아래"
                    print(f" ★ 포착 코인: {res['korean_name']}({res['market']}) | 현재가: {res['close_price']:,}원 | 16h RSI(60~75): {res['rsi_60_75_ratio']}%({res['rsi_60_75_count']}/16봉) | 상태: {state_str}({res['tenkan_diff_pct']}%)")

    captured_list.sort(key=lambda x: (x['rsi_60_75_count'], x['rsi_1h']), reverse=True)

    # -------------------------------------------------------------
    # [2/4] PHASE 1: 매수 전 매도 선(先)처리
    # -------------------------------------------------------------
    print(f"\n[2/4] PHASE 1: 매수 전 보유 종목 매도 선(先)처리 진행...", flush=True)
    sold_items = bithumb_trader.process_auto_sells(all_coins_dict, is_dry_run=is_dry_run)

    # -------------------------------------------------------------
    # [3/4] PHASE 2: 신규 포착 코인 중복 검증 & 후(後)매수 집행
    # -------------------------------------------------------------
    print(f"\n[3/4] PHASE 2: 신규 포착 코인 후(後)매수 집행 진행...", flush=True)
    bought_items = bithumb_trader.process_auto_buys(captured_list, max_buy_coins=10, buy_amount_per_coin=200000, is_dry_run=is_dry_run)

    # -------------------------------------------------------------
    # [4/4] PHASE 3: PDF 보고서 생성 & 구글 드라이브 업로드
    # -------------------------------------------------------------
    print(f"\n[4/4] PHASE 3: PDF 리포트 생성 중... ({pdf_path})", flush=True)
    
    if not captured_list:
        print("조건을 만족하는 신규 포착 코인이 없어 요약 및 매매 내역 기본 리포트로 출력합니다.")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with PdfPages(pdf_path) as pdf:
        # 요약 표 생성
        chunk_size = 20
        summary_rows_all = [
            [
                c['market'], c['korean_name'], c['english_name'], f"{c['close_price']:,}",
                f"{c['rsi_60_75_ratio']}% ({c['rsi_60_75_count']}/16봉)", f"{c['prev_3_max_rsi']:.1f}",
                "상위" if c['is_above_tenkan'] else "이탈(하회)", f"{c['tenkan_diff_pct']:+.2f}%",
                f"{c['rsi_1h']:.1f}", f"{c['tenkan_1h']:,}", f"{c['rsi_daily']:.1f}", f"{c['tenkan_daily']:,}"
            ] for c in captured_list
        ]
        col_labels = ['마켓코드', '한글명', '영문명', '현재가(원)', '16h RSI(60~75)', '직전3봉MaxRSI', '전환선위치', '전환선이격률', '60m RSI', '60m전환선', '일봉 RSI', '일봉전환선']

        if not summary_rows_all:
            summary_rows_all = [["-" for _ in col_labels]]
            summary_rows_all[0][1] = "포착 코인 없음"

        for page_idx in range(0, len(summary_rows_all), chunk_size):
            chunk = summary_rows_all[page_idx : page_idx + chunk_size]
            fig_table, ax_table = plt.subplots(figsize=(14, 8.5))
            ax_table.axis('off')

            title_text = "빗썸 1시간봉 최근 16봉 RSI (60~75) 포착 & 자동 트레이딩 리포트"
            subtitle_text = f"분석 일시: {now_str} | 총 {len(captured_list)}개 포착 | 금회 매도: {len(sold_items)}건, 매수: {len(bought_items)}건 (p.{page_idx//chunk_size + 1})"
            
            ax_table.text(0.5, 0.96, title_text, fontsize=14, fontweight='bold', ha='center', va='top', color='#1a5276')
            ax_table.text(0.5, 0.92, subtitle_text, fontsize=10, color='gray', ha='center', va='top')

            table = ax_table.table(
                cellText=chunk, colLabels=col_labels, cellLoc='center', loc='center', bbox=[0.02, 0.05, 0.96, 0.82]
            )
            table.auto_set_font_size(False)
            table.set_fontsize(8.0)
            
            for col_i in range(len(col_labels)):
                cell = table[(0, col_i)]
                cell.set_facecolor('#1a5276')
                cell.set_text_props(color='white', fontweight='bold')
                
            plt.tight_layout()
            pdf.savefig(fig_table)
            plt.close(fig_table)

        # 개별 코인 차트
        for idx, item in enumerate(captured_list[:25], 1):
            if item['df_daily'] is None:
                continue

            fig, axes = plt.subplots(
                3, 2, figsize=(16, 9.5),
                gridspec_kw={'height_ratios': [3.0, 1.2, 1.2], 'wspace': 0.18, 'hspace': 0.25}
            )
            k_name = item['korean_name']
            e_name = item['english_name']
            m_code = item['market']
            price = item['close_price']
            state_text = "전환선 상위" if item['is_above_tenkan'] else "전환선 하회이탈"
            
            title_page = f"[{idx}/{len(captured_list[:25])}] {k_name} ({e_name} / {m_code})  |  현재가: {price:,}원  |  [포착] 16h RSI(60~75): {item['rsi_60_75_ratio']}% ({item['rsi_60_75_count']}/16봉) | 상태: {state_text}"
            fig.suptitle(title_page, fontsize=11.5, fontweight='bold', color='#0e6251', y=0.98)
            
            plot_3tier_chart([axes[0, 0], axes[1, 0], axes[2, 0]], item['df_1h'], k_name, "60분봉")
            plot_3tier_chart([axes[0, 1], axes[1, 1], axes[2, 1]], item['df_daily'], k_name, "일봉")
            
            plt.subplots_adjust(top=0.93, bottom=0.06, left=0.05, right=0.95)
            pdf.savefig(fig)
            plt.close(fig)

    full_pdf_path = os.path.abspath(pdf_path)
    print(f"\n★ 파이프라인 집행 완료! PDF 저장 위치: '{full_pdf_path}'", flush=True)

    # Google Drive 업로드
    try:
        from upload_to_gdrive import upload_pdf_to_gdrive
        gdrive_url = upload_pdf_to_gdrive(full_pdf_path, folder_name="report_hour", user_email="hhokyung@gmail.com")
        if gdrive_url:
            print(f" -> Google Drive 업로드 완료 링크: {gdrive_url}", flush=True)
    except Exception as e:
        print(f"Google Drive 업로드 오류: {e}", flush=True)

    return full_pdf_path

if __name__ == "__main__":
    run_onehour_trade_pipeline(is_dry_run=True)
