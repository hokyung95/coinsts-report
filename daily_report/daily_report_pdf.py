"""
========================================================================================
 [모듈 명]: daily_report/daily_report_pdf.py
 [구현 목적]:
   - 빗썸 일봉 시계열 데이터 기반으로 일목균형표 기준선이 하향 추세(우하향)인 상황에서
     MACD선이 상향 추세(우상향 상승 전환)를 보이는 코인을 포착 (상승 다이버전스 / 모멘텀 반전)
   - 포착된 코인에 대해 한 코인당 한 페이지로 일목균형표(진한 거래량 포함), MACD, RSI 3단 시각화 PDF 리포트 자동 생성
   - **저장 위치**: daily_report/report/report_daily_YYYYMMDDHHMMSS.pdf
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

def calc_slope(series, window=5):
    """최근 N개 봉에 대한 선형 회귀 기울기 계산"""
    if len(series) < window:
        return 0.0
    sub = series.iloc[-window:].values
    if np.isnan(sub).any() or sub[0] == 0:
        return 0.0
    x = np.arange(len(sub))
    norm_y = sub / sub[0]  # 정규화
    slope, _ = np.polyfit(x, norm_y, 1)
    return slope

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

def process_daily_candle_df(data):
    """일봉 JSON 데이터를 DataFrame으로 변환 및 일목(전환9, 기준26)/MACD/RSI 계산"""
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
        
    df['Close'] = df['trade_price']
    df['Volume'] = df['candle_acc_trade_volume'].astype(float) if 'candle_acc_trade_volume' in df.columns else 0.0
    
    # 일목균형표 계산 (표준 일봉: 전환선 9, 기준선 26, 선행스팬1 26, 선행스팬2 52)
    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 9)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 26)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(26)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 52).shift(26)
    
    # RSI 및 MACD
    df['RSI'] = calc_rsi(df['Close'], 14)
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calc_macd(df['Close'])
    return df

def fetch_and_analyze_daily_coin(m, count=200):
    """
    단일 코인의 일봉 시계열 데이터 수집 및 조건 분석
    포착 조건:
    1) 일목균형표 기준선(26) 하향 추세 (최근 5봉 기준선 감소 또는 기울기 < 0)
    2) MACD선 상향 추세 (최근 3~5봉 MACD 상승 또는 기울기 > 0)
    """
    market_code = m['market']
    korean_name = m['korean_name']
    english_name = m['english_name']
    
    headers = {"accept": "application/json"}
    url_daily = f"https://api.bithumb.com/v1/candles/days?market={market_code}&count={count}"
    
    try:
        res_daily = requests.get(url_daily, headers=headers, timeout=5)
        if res_daily.status_code == 200:
            data_daily = res_daily.json()
            if isinstance(data_daily, list) and len(data_daily) >= 60:
                df = process_daily_candle_df(data_daily)
                
                kijun = df['BaseLine']
                macd = df['MACD']
                close = df['Close']
                
                if len(df) < 30:
                    return None
                    
                # 1. 기준선 하향 추세 검사 (최근 5봉 기준: 현재 기준선 < 5봉전 기준선 OR 기울기 < 0)
                kijun_curr = kijun.iloc[-1]
                kijun_past = kijun.iloc[-5]
                kijun_slope = calc_slope(kijun, window=5)
                
                cond_kijun_down = (kijun_curr < kijun_past) or (kijun_slope < -0.0005)
                
                # 2. MACD선 상향 추세 검사 (최근 3~5봉 기준: 현재 MACD > 3봉전 MACD OR MACD 기울기 > 0)
                macd_curr = macd.iloc[-1]
                macd_past = macd.iloc[-3]
                macd_slope = calc_slope(macd, window=5)
                
                cond_macd_up = (macd_curr > macd_past) or (macd_slope > 0.001)
                
                if cond_kijun_down and cond_macd_up:
                    return {
                        'market': market_code,
                        'korean_name': korean_name,
                        'english_name': english_name,
                        'close_price': close.iloc[-1],
                        'conversion_line': round(df['ConversionLine'].iloc[-1], 2),
                        'base_line': round(kijun_curr, 2),
                        'kijun_slope': round(kijun_slope, 4),
                        'macd': round(macd_curr, 2),
                        'macd_slope': round(macd_slope, 4),
                        'rsi': round(df['RSI'].iloc[-1], 1),
                        'df': df
                    }
    except Exception:
        pass
    return None

def generate_daily_divergence_pdf(pdf_path=None, max_workers=6):
    """
    일봉 기준선 하향 & MACD 상향 포착 코인 대상 1코인 1페이지 3단 시각화 PDF 리포트 생성
    - PDF 저장 위치: daily_report/report/report_daily_YYYYMMDDHHMMSS.pdf
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    if pdf_path is None:
        save_dir = os.path.join(base_dir, "report")
        os.makedirs(save_dir, exist_ok=True)
        filename = f"report_daily_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_path = os.path.join(save_dir, filename)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(pdf_path)), exist_ok=True)

    markets = get_krw_markets()
    if not markets:
        print("조회된 KRW 마켓이 없습니다.")
        return None

    print(f"[1/3] 빗썸 {len(markets)}개 원화 코인 스캔 중 (조건: 일봉 기준선 하향 & MACD 상향, 스레드: {max_workers})...")
    
    captured_list = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_and_analyze_daily_coin, m): m for m in markets}
        for future in as_completed(futures):
            res = future.result()
            if res:
                captured_list.append(res)
                print(f" ★ 포착 코인: {res['korean_name']}({res['market']}) | 현재가: {res['close_price']:,}원 | MACD기울기: +{res['macd_slope']} | 기준선기울기: {res['kijun_slope']}")

    # 정렬: MACD 기울기 내림차순
    captured_list.sort(key=lambda x: x['macd_slope'], reverse=True)
    
    print(f"\n[2/3] 총 {len(captured_list)}개 포착 코인 PDF 생성 중... (저장경로: {pdf_path})")
    
    if not captured_list:
        print("조건(일봉 기준선 하향 & MACD 상향)을 만족하는 코인이 없습니다.")
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
                f"{c['conversion_line']:,}",
                f"{c['base_line']:,}",
                f"{c['kijun_slope']:.4f}",
                f"{c['macd']:,}",
                f"+{c['macd_slope']:.4f}",
                f"{c['rsi']:.1f}"
            ] for c in captured_list
        ]
        
        col_labels = ['마켓코드', '한글명', '영문명', '현재가(원)', '일봉전환선', '일봉기준선(26)', '기준선기울기', 'MACD', 'MACD기울기', 'RSI']

        for page_idx in range(0, len(summary_rows_all), chunk_size):
            chunk = summary_rows_all[page_idx : page_idx + chunk_size]
            fig_table, ax_table = plt.subplots(figsize=(11.69, 8.27))
            ax_table.axis('off')

            title_text = "빗썸 일봉 일목 기준선 하향 & MACD 상향 추세 포착 리포트"
            subtitle_text = f"분석 일시: {now_str} | 조건: 일봉 기준선(26) 하향추세 AND MACD(12,26) 상향추세 | 총 {len(captured_list)}개 코인 포착 (p.{page_idx//chunk_size + 1})"
            
            ax_table.text(0.5, 0.96, title_text, fontsize=14, fontweight='bold', ha='center', va='top', color='#1b4f72')
            ax_table.text(0.5, 0.92, subtitle_text, fontsize=9.5, color='gray', ha='center', va='top')

            table = ax_table.table(
                cellText=chunk,
                colLabels=col_labels,
                cellLoc='center',
                loc='center',
                bbox=[0.03, 0.06, 0.94, 0.82]
            )
            table.auto_set_font_size(False)
            table.set_fontsize(8.0)
            
            for col_i in range(len(col_labels)):
                cell = table[(0, col_i)]
                cell.set_facecolor('#1b4f72')
                cell.set_text_props(color='white', fontweight='bold')
                
            plt.tight_layout()
            pdf.savefig(fig_table)
            plt.close(fig_table)

        # -------------------------------------------------------------
        # 2. 개별 코인 차트 페이지 (한 코인당 한 페이지 3단 시각화)
        # -------------------------------------------------------------
        for idx, item in enumerate(captured_list, 1):
            fig, (ax_p, ax_m, ax_r) = plt.subplots(
                3, 1, figsize=(11.69, 8.27),
                gridspec_kw={'height_ratios': [3.0, 1.2, 1.2]},
                sharex=True
            )
            
            df = item['df']
            x = range(len(df))
            k_name = item['korean_name']
            m_code = item['market']
            price = item['close_price']
            
            # ---------------------------------------------------------
            # 1단: 일봉 가격 + 일목균형표(9,26,52) + 진한 거래량 (TwinX)
            # ---------------------------------------------------------
            ax_v = ax_p.twinx()
            v_colors = ['#c0392b' if df['Close'].iloc[i] >= (df['Close'].iloc[i-1] if i > 0 else df['Close'].iloc[i]) else '#2980b9' for i in range(len(df))]
            ax_v.bar(x, df['Volume'], color=v_colors, alpha=0.65, width=0.75, label='거래량')
            ax_v.set_ylim(0, df['Volume'].max() * 3.8 if df['Volume'].max() > 0 else 1)
            ax_v.set_ylabel("거래량", fontsize=8, color='gray')
            ax_v.tick_params(axis='y', labelsize=7, labelcolor='gray')
            ax_v.grid(False)
            
            ax_p.set_zorder(ax_v.get_zorder() + 1)
            ax_p.patch.set_visible(False)
            
            ax_p.plot(x, df['Close'], label='종가', color='black', linewidth=1.4)
            ax_p.plot(x, df['ConversionLine'], label='전환선(9)', color='#e31a1c', linewidth=1.2)
            ax_p.plot(x, df['BaseLine'], label='기준선(26)', color='#1f78b4', linewidth=1.4)
            ax_p.plot(x, df['Span1'], label='선행1(26)', color='#33a02c', linewidth=0.8, linestyle='--')
            ax_p.plot(x, df['Span2'], label='선행2(52)', color='#ff7f00', linewidth=0.8, linestyle='--')
            
            ax_p.fill_between(x, df['Span1'], df['Span2'], where=(df['Span1'] >= df['Span2']), color='#b2df8a', alpha=0.35, label='양운')
            ax_p.fill_between(x, df['Span1'], df['Span2'], where=(df['Span1'] < df['Span2']), color='#fb9a99', alpha=0.35, label='음운')
            
            title_str = f"[{idx}/{len(captured_list)}] {k_name} ({m_code}) - 일봉 일목균형표 & 거래량 | 현재가: {price:,}원 | 기준선기울기: {item['kijun_slope']} | MACD기울기: +{item['macd_slope']}"
            ax_p.set_title(title_str, fontsize=10, fontweight='bold', color='#1b4f72', pad=4)
            ax_p.set_ylabel("가격 (KRW)", fontsize=8.5)
            ax_p.legend(loc='upper left', fontsize=7.5, framealpha=0.85, ncol=3)
            ax_p.grid(True, linestyle=':', alpha=0.5)
            
            # ---------------------------------------------------------
            # 2단: MACD (12, 26, 9)
            # ---------------------------------------------------------
            ax_m.plot(x, df['MACD'], label='MACD(12,26)', color='#1f78b4', linewidth=1.1)
            ax_m.plot(x, df['MACD_Signal'], label='Signal(9)', color='#e31a1c', linewidth=1.1, linestyle='--')
            
            hist_colors = ['#e31a1c' if v >= 0 else '#1f78b4' for v in df['MACD_Hist']]
            ax_m.bar(x, df['MACD_Hist'], color=hist_colors, alpha=0.55, width=0.75, label='Oscillator')
            ax_m.axhline(0, color='gray', linestyle=':', linewidth=0.7)
            
            ax_m.set_ylabel("MACD", fontsize=8.5)
            ax_m.legend(loc='upper left', fontsize=7, framealpha=0.85, ncol=3)
            ax_m.grid(True, linestyle=':', alpha=0.5)
            
            # ---------------------------------------------------------
            # 3단: RSI (14)
            # ---------------------------------------------------------
            ax_r.plot(x, df['RSI'], label='RSI(14)', color='#8e44ad', linewidth=1.2)
            ax_r.axhline(70, color='#e31a1c', linestyle='--', linewidth=0.8, label='과매수(70)')
            ax_r.axhline(30, color='#1f78b4', linestyle='--', linewidth=0.8, label='과매도(30)')
            ax_r.set_ylim(0, 100)
            ax_r.set_ylabel("RSI", fontsize=8.5)
            ax_r.legend(loc='upper left', fontsize=7, framealpha=0.85, ncol=3)
            ax_r.grid(True, linestyle=':', alpha=0.5)
            
            plt.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

    full_pdf_path = os.path.abspath(pdf_path)
    print(f"\n[3/3] 성공! 일봉 기준선 하향 & MACD 상향 3단 시각화 PDF 리포트 생성 완료!")
    print(f" -> PDF 저장 위치: '{full_pdf_path}'")
    return full_pdf_path

if __name__ == "__main__":
    generate_daily_divergence_pdf()
