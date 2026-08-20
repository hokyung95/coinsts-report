"""
========================================================================================
 [모듈 명]: onehour_report_pdf.py
 [구현 목적]:
   - 일봉 기준 일목균형표 전환선(9)이 기준선(30) 위에 위치하고,
     60분봉(1시간봉) 시계열 데이터 기준 일목균형표 전환선(9)이 기준선(30) 위에 위치한 코인을 포착
   - 60분봉 일목균형표(진한 거래량 포함), MACD, RSI 3단 시각화와
     일봉 일목균형표(진한 거래량 포함), MACD, RSI 3단 시각화를 같은 페이지에 나란히 PDF 리포트 생성
   - **저장 위치**: onehour_report/report/report_onehour_YYYYMMDDHHMMSS.pdf
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

# Matplotlib 한글 폰트 설정 (Windows 맑은 고딕)
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

def get_krw_markets():
    """빗썸에서 거래되는 모든 원화(KRW) 마켓 목록 및 한글명/영문명 조회"""
    url = "https://api.bithumb.com/v1/market/all"
    headers = {"accept": "application/json"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        markets = response.json()
        krw_markets = [
            {
                'market': m['market'],
                'korean_name': m.get('korean_name', m['market']),
                'english_name': m.get('english_name', m['market'])
            }
            for m in markets if m['market'].startswith('KRW-')
        ]
        return krw_markets
    except Exception as e:
        print(f"마켓 목록 조회 중 오류 발생: {e}")
        return []

def calc_mid_point(high, low, window):
    """지정된 기간 동안의 (최고가 + 최저가) / 2 계산"""
    return (high.rolling(window=window).max() + low.rolling(window=window).min()) / 2

def calc_rsi(series, period=14):
    """RSI 지수 계산"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calc_macd(series, short=12, long=26, signal=9):
    """MACD, Signal, Histogram 계산"""
    ema_short = series.ewm(span=short, adjust=False).mean()
    ema_long = series.ewm(span=long, adjust=False).mean()
    macd = ema_short - ema_long
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    macd_hist = macd - macd_signal
    return macd, macd_signal, macd_hist

def process_candle_df(data, kijun_window=30):
    """캔들 JSON 데이터를 DataFrame으로 변환 및 일목(기준선 30봉)/MACD/RSI 계산"""
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
        
    df['Close'] = df['trade_price']
    df['Volume'] = df['candle_acc_trade_volume'].astype(float) if 'candle_acc_trade_volume' in df.columns else 0.0
    
    # 일목균형표 계산 (전환선 9, 기준선 30, 선행스팬1 30, 선행스팬2 60)
    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 9)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], kijun_window)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(kijun_window)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], kijun_window * 2).shift(kijun_window)
    
    # RSI 및 MACD
    df['RSI'] = calc_rsi(df['Close'], 14)
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calc_macd(df['Close'])
    return df

def fetch_and_analyze_single_coin(m, count=200):
    """
    단일 코인의 60분봉 및 일봉 시계열 데이터 수집 및 분석
    포착 조건:
    1) 60분봉 일목 전환선(9) > 기준선(30)
    2) 일봉 일목 전환선(9) > 기준선(30)
    """
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
            if isinstance(data_1h, list) and len(data_1h) >= 60:
                df_1h = process_candle_df(data_1h, kijun_window=30)
                last_1h = df_1h.iloc[-1]
                
                tenkan_1h = last_1h['ConversionLine']
                kijun_1h = last_1h['BaseLine']
                
                # 60분봉 1차 필터: 전환선 > 기준선(30)
                if not pd.isna(tenkan_1h) and not pd.isna(kijun_1h) and tenkan_1h > kijun_1h:
                    res_daily = requests.get(url_daily, headers=headers, timeout=5)
                    if res_daily.status_code == 200:
                        data_daily = res_daily.json()
                        if isinstance(data_daily, list) and len(data_daily) >= 60:
                            df_daily = process_candle_df(data_daily, kijun_window=30)
                            last_daily = df_daily.iloc[-1]
                            
                            tenkan_daily = last_daily['ConversionLine']
                            kijun_daily = last_daily['BaseLine']
                            
                            # 일봉 2차 필터: 전환선 > 기준선(30)
                            if not pd.isna(tenkan_daily) and not pd.isna(kijun_daily) and tenkan_daily > kijun_daily:
                                # 거리 이격 비율 (%) 계산
                                diff_pct_1h = ((tenkan_1h - kijun_1h) / kijun_1h) * 100
                                diff_pct_daily = ((tenkan_daily - kijun_daily) / kijun_daily) * 100
                                
                                return {
                                    'market': market_code,
                                    'korean_name': korean_name,
                                    'english_name': english_name,
                                    'close_price': last_1h['Close'],
                                    'tenkan_1h': round(tenkan_1h, 2),
                                    'kijun_1h': round(kijun_1h, 2),
                                    'diff_pct_1h': round(diff_pct_1h, 2),
                                    'rsi_1h': round(last_1h['RSI'], 1) if not pd.isna(last_1h['RSI']) else 0.0,
                                    'macd_1h': round(last_1h['MACD'], 2) if not pd.isna(last_1h['MACD']) else 0.0,
                                    'tenkan_daily': round(tenkan_daily, 2),
                                    'kijun_daily': round(kijun_daily, 2),
                                    'diff_pct_daily': round(diff_pct_daily, 2),
                                    'rsi_daily': round(last_daily['RSI'], 1) if not pd.isna(last_daily['RSI']) else 0.0,
                                    'macd_daily': round(last_daily['MACD'], 2) if not pd.isna(last_daily['MACD']) else 0.0,
                                    'df_1h': df_1h,
                                    'df_daily': df_daily
                                }
    except Exception:
        pass
    return None

def plot_3tier_chart(axes_col, df, title_prefix, time_frame_label):
    """
    3단 시각화 서브플롯 그리기
    axes_col: [ax_price, ax_macd, ax_rsi]
    1단: 가격 + 일목균형표 + 진한 거래량
    2단: MACD
    3단: RSI
    """
    ax_p, ax_m, ax_r = axes_col
    x = range(len(df))
    
    # ---------------------------------------------------------
    # 1단: 가격 + 일목균형표(9, 30, 60) + 진한 거래량 (TwinX)
    # ---------------------------------------------------------
    ax_v = ax_p.twinx()
    # 진한 거래량 막대 색상 (상승: #c0392b 진한 빨강, 하락: #2980b9 진한 파랑)
    v_colors = ['#c0392b' if df['Close'].iloc[i] >= (df['Close'].iloc[i-1] if i > 0 else df['Close'].iloc[i]) else '#2980b9' for i in range(len(df))]
    ax_v.bar(x, df['Volume'], color=v_colors, alpha=0.65, width=0.75, label='거래량')
    ax_v.set_ylim(0, df['Volume'].max() * 3.8 if df['Volume'].max() > 0 else 1)
    ax_v.set_ylabel("거래량", fontsize=7.5, color='gray')
    ax_v.tick_params(axis='y', labelsize=6.5, labelcolor='gray')
    ax_v.grid(False)
    
    ax_p.set_zorder(ax_v.get_zorder() + 1)
    ax_p.patch.set_visible(False)
    
    ax_p.plot(x, df['Close'], label='종가', color='black', linewidth=1.3)
    ax_p.plot(x, df['ConversionLine'], label='전환선(9)', color='#e31a1c', linewidth=1.2)
    ax_p.plot(x, df['BaseLine'], label='기준선(30)', color='#1f78b4', linewidth=1.3)
    ax_p.plot(x, df['Span1'], label='선행1(30)', color='#33a02c', linewidth=0.8, linestyle='--')
    ax_p.plot(x, df['Span2'], label='선행2(60)', color='#ff7f00', linewidth=0.8, linestyle='--')
    
    # 구름대 채우기 (양운: 초록, 음운: 분홍)
    ax_p.fill_between(x, df['Span1'], df['Span2'], where=(df['Span1'] >= df['Span2']), color='#b2df8a', alpha=0.35, label='양운')
    ax_p.fill_between(x, df['Span1'], df['Span2'], where=(df['Span1'] < df['Span2']), color='#fb9a99', alpha=0.35, label='음운')
    
    ax_p.set_title(f"{title_prefix} - [{time_frame_label} 일목균형표(9,30) & 거래량]", fontsize=9.5, fontweight='bold', color='#1b4f72', pad=3)
    ax_p.set_ylabel("가격 (KRW)", fontsize=8)
    ax_p.tick_params(axis='y', labelsize=7.5)
    ax_p.legend(loc='upper left', fontsize=7, framealpha=0.85, ncol=3)
    ax_p.grid(True, linestyle=':', alpha=0.5)
    
    # ---------------------------------------------------------
    # 2단: MACD (12, 26, 9)
    # ---------------------------------------------------------
    ax_m.plot(x, df['MACD'], label='MACD(12,26)', color='#1f78b4', linewidth=1.0)
    ax_m.plot(x, df['MACD_Signal'], label='Signal(9)', color='#e31a1c', linewidth=1.0, linestyle='--')
    
    hist_colors = ['#e31a1c' if v >= 0 else '#1f78b4' for v in df['MACD_Hist']]
    ax_m.bar(x, df['MACD_Hist'], color=hist_colors, alpha=0.55, width=0.75, label='Oscillator')
    ax_m.axhline(0, color='gray', linestyle=':', linewidth=0.7)
    
    ax_m.set_ylabel("MACD", fontsize=8)
    ax_m.tick_params(axis='y', labelsize=7.5)
    ax_m.legend(loc='upper left', fontsize=6.5, framealpha=0.85, ncol=3)
    ax_m.grid(True, linestyle=':', alpha=0.5)
    
    # ---------------------------------------------------------
    # 3단: RSI (14)
    # ---------------------------------------------------------
    ax_r.plot(x, df['RSI'], label='RSI(14)', color='#8e44ad', linewidth=1.1)
    ax_r.axhline(70, color='#e31a1c', linestyle='--', linewidth=0.8, label='과매수(70)')
    ax_r.axhline(30, color='#1f78b4', linestyle='--', linewidth=0.8, label='과매도(30)')
    ax_r.set_ylim(0, 100)
    ax_r.set_ylabel("RSI", fontsize=8)
    ax_r.tick_params(axis='x', labelsize=7.5)
    ax_r.tick_params(axis='y', labelsize=7.5)
    ax_r.legend(loc='upper left', fontsize=6.5, framealpha=0.85, ncol=3)
    ax_r.grid(True, linestyle=':', alpha=0.5)

def generate_onehour_pdf_report(pdf_path=None, max_workers=6):
    """
    60분봉 & 일봉 기준선(30) 포착 코인 대상 듀얼 3단 시각화 PDF 리포트 생성
    - PDF 저장 위치: onehour_report/report/report_onehour_YYYYMMDDHHMMSS.pdf
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    if pdf_path is None:
        save_dir = os.path.join(base_dir, "onehour_report", "report")
        os.makedirs(save_dir, exist_ok=True)
        filename = f"report_onehour_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_path = os.path.join(save_dir, filename)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(pdf_path)), exist_ok=True)

    markets = get_krw_markets()
    if not markets:
        print("조회된 KRW 마켓이 없습니다.")
        return None

    print(f"[1/3] 빗썸 {len(markets)}개 원화 코인 스캔 중 (60분봉 & 일봉 전환선 > 기준선(30) 조건, 스레드: {max_workers})...")
    
    captured_list = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_and_analyze_single_coin, m): m for m in markets}
        for future in as_completed(futures):
            res = future.result()
            if res:
                captured_list.append(res)
                print(f" ★ 포착 코인: {res['korean_name']}({res['market']}) | 현재가: {res['close_price']:,}원 | 60m이격: +{res['diff_pct_1h']}% | 일봉이격: +{res['diff_pct_daily']}%")

    # 정렬: 60분봉 이격률 및 일봉 이격률 내림차순
    captured_list.sort(key=lambda x: (x['diff_pct_1h'], x['diff_pct_daily']), reverse=True)
    
    print(f"\n[2/3] 총 {len(captured_list)}개 포착 코인 PDF 생성 중... (저장경로: {pdf_path})")
    
    if not captured_list:
        print("조건(60분봉 & 일봉 전환선>기준선(30))을 만족하는 코인이 없습니다.")
        return None

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with PdfPages(pdf_path) as pdf:
        # -------------------------------------------------------------
        # 1. 요약 표 (Summary Table) 페이지
        # -------------------------------------------------------------
        chunk_size = 20
        summary_rows_all = [
            [
                c['market'],
                c['korean_name'],
                c['english_name'],
                f"{c['close_price']:,}",
                f"{c['tenkan_1h']:,}",
                f"{c['kijun_1h']:,}",
                f"+{c['diff_pct_1h']}%",
                f"{c['tenkan_daily']:,}",
                f"{c['kijun_daily']:,}",
                f"+{c['diff_pct_daily']}%",
                f"{c['rsi_1h']:.1f}",
                f"{c['macd_1h']:,}"
            ] for c in captured_list
        ]
        
        col_labels = ['마켓코드', '한글명', '영문명', '현재가(원)', '60m전환선', '60m기준선(30)', '60m이격률', '일봉전환선', '일봉기준선(30)', '일봉이격률', '60m RSI', '60m MACD']

        for page_idx in range(0, len(summary_rows_all), chunk_size):
            chunk = summary_rows_all[page_idx : page_idx + chunk_size]
            fig_table, ax_table = plt.subplots(figsize=(14, 8.5))
            ax_table.axis('off')

            title_text = "빗썸 60분봉 & 일봉 멀티타임프레임 일목균형표(기준선 30) 리포트"
            subtitle_text = f"분석 일시: {now_str} | 조건: 60분봉 (전환선 > 기준선(30)) AND 일봉 (전환선 > 기준선(30)) | 총 {len(captured_list)}개 코인 포착 (p.{page_idx//chunk_size + 1})"
            
            ax_table.text(0.5, 0.96, title_text, fontsize=15, fontweight='bold', ha='center', va='top', color='#1a5276')
            ax_table.text(0.5, 0.92, subtitle_text, fontsize=10, color='gray', ha='center', va='top')

            table = ax_table.table(
                cellText=chunk,
                colLabels=col_labels,
                cellLoc='center',
                loc='center',
                bbox=[0.02, 0.05, 0.96, 0.82]
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

        # -------------------------------------------------------------
        # 2. 개별 코인 차트 페이지 (한 페이지에 60분봉 3단 + 일봉 3단 나란히 배치)
        # -------------------------------------------------------------
        for idx, item in enumerate(captured_list, 1):
            fig, axes = plt.subplots(
                3, 2, figsize=(16, 9.5),
                gridspec_kw={'height_ratios': [3.0, 1.2, 1.2], 'wspace': 0.18, 'hspace': 0.25}
            )
            
            k_name = item['korean_name']
            e_name = item['english_name']
            m_code = item['market']
            price = item['close_price']
            
            title_page = f"[{idx}/{len(captured_list)}] {k_name} ({e_name} / {m_code})  |  현재가: {price:,}원  |  [포착] 60분봉 & 일봉 일목 전환선 > 기준선(30)"
            fig.suptitle(title_page, fontsize=12, fontweight='bold', color='#0e6251', y=0.98)
            
            # 좌측: 60분봉 3단 시각화 (Col 0)
            plot_3tier_chart(
                axes_col=[axes[0, 0], axes[1, 0], axes[2, 0]],
                df=item['df_1h'],
                title_prefix=f"{k_name}",
                time_frame_label="60분봉(1시간봉)"
            )
            
            # 우측: 일봉 3단 시각화 (Col 1)
            plot_3tier_chart(
                axes_col=[axes[0, 1], axes[1, 1], axes[2, 1]],
                df=item['df_daily'],
                title_prefix=f"{k_name}",
                time_frame_label="일봉(Daily)"
            )
            
            plt.subplots_adjust(top=0.93, bottom=0.06, left=0.05, right=0.95)
            pdf.savefig(fig)
            plt.close(fig)

    full_pdf_path = os.path.abspath(pdf_path)
    print(f"\n[3/3] 성공! 60분봉 & 일봉 멀티타임프레임 3단 시각화 PDF 리포트 생성 완료!")
    print(f" -> PDF 저장 위치: '{full_pdf_path}'")
    return full_pdf_path

if __name__ == "__main__":
    generate_onehour_pdf_report()
