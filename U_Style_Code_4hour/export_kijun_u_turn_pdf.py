"""
========================================================================================
 [모듈 명]: U_Style_Code_4hour/export_kijun_u_turn_pdf.py
 [구현 목적]:
   - 빗썸 240분봉(4시간봉) 시계열 데이터 기반으로 일목균형표 기준선(30봉)
     U자형 턴어라운드가 최근 6봉(24시간) 이내 발생하고,
     일봉 기준 일목균형표 기준선(26) 각도가 1도 이상(양의 각도 >= 1.0°)인 코인을 스캔하여
     240분봉 일목균형표(진한 거래량 포함), MACD, RSI 3단 시각화 PDF 리포트 자동 생성
   - **저장 위치**: U_Style_Code_4hour/report/report_240m_kijun_u_turn_YYYYMMDDHHMMSS.pdf
========================================================================================
"""

import requests
import numpy as np
import pandas as pd
import time
import os
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

def get_krw_markets():
    url = "https://api.bithumb.com/v1/market/all"
    res = requests.get(url, headers={"accept": "application/json"}).json()
    return [{'market': m['market'], 'korean_name': m.get('korean_name', m['market']), 'english_name': m.get('english_name', m['market'])} for m in res if m['market'].startswith('KRW-')]

def calc_mid_point(high, low, window):
    return (high.rolling(window=window).max() + low.rolling(window=window).min()) / 2

def get_slope_and_angle(arr):
    """배열의 정규화 기울기 및 각도(도, Degree) 계산"""
    if len(arr) < 2 or arr.iloc[0] == 0:
        return 0.0, 0.0
    x = np.arange(len(arr))
    norm_arr = arr.values / arr.values[0]
    slope, _ = np.polyfit(x, norm_arr, 1)
    angle_deg = np.degrees(np.arctan(slope))
    return slope, angle_deg

def get_kijun_dynamic_angle(series):
    """
    일목균형표 기준선 각도 계산:
    현재 기준선 값이 이전 값들 중 '같지 않은 가장 최근 이전 값'보다 큰 경우,
    그 이전 값의 시작 위치부터 현재값까지의 구간으로 각도(도, Degree)를 계산.
    상승하지 않았거나(동일/하락) 이전 값이 없으면 (0.0, 0.0) 반환.
    """
    if len(series) < 2:
        return 0.0, 0.0
    clean_series = series.dropna()
    if len(clean_series) < 2:
        return 0.0, 0.0
        
    curr_val = clean_series.iloc[-1]
    prev_idx = None
    for i in range(len(clean_series) - 2, -1, -1):
        if not np.isclose(clean_series.iloc[i], curr_val):
            prev_idx = i
            break
            
    if prev_idx is None:
        return 0.0, 0.0
        
    prev_val = clean_series.iloc[prev_idx]
    if curr_val > prev_val:
        first_prev_idx = prev_idx
        while first_prev_idx > 0 and np.isclose(clean_series.iloc[first_prev_idx - 1], prev_val):
            first_prev_idx -= 1
        rise_segment = clean_series.iloc[first_prev_idx:]
        return get_slope_and_angle(rise_segment)
    else:
        return 0.0, 0.0

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    return 100 - (100 / (1 + (avg_gain / avg_loss)))

def calc_macd(series, short=12, long=26, signal=9):
    ema_short = series.ewm(span=short, adjust=False).mean()
    ema_long = series.ewm(span=long, adjust=False).mean()
    macd = ema_short - ema_long
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    return macd, macd_signal, macd - macd_signal

def process_240m_candle_df(data):
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
    df['Close'] = df['trade_price']
    df['Volume'] = df['candle_acc_trade_volume'].astype(float) if 'candle_acc_trade_volume' in df.columns else 0.0
    
    # 240분봉 일목 (10, 30, 60, 30)
    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 10)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 30)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(30)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 60).shift(30)
    df['RSI'] = calc_rsi(df['Close'], 14)
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calc_macd(df['Close'])
    return df

def check_kijun_u_turn_240m(df, max_lookback_bars=6, flat_tolerance_pct=0.010):
    n = len(df)
    if n < 60: return False, None
    kijun = df['BaseLine']
    close = df['Close']
    
    for offset in range(max_lookback_bars):
        idx = n - 1 - offset
        if idx < 35: continue
        
        curr_k, prev1_k, prev2_k = kijun.iloc[idx], kijun.iloc[idx-1], kijun.iloc[idx-2]
        mid15_k, past30_k = kijun.iloc[idx-15], kijun.iloc[idx-30]
        
        if pd.isna(curr_k) or pd.isna(prev1_k) or pd.isna(mid15_k) or pd.isna(past30_k):
            continue

        cond1 = (mid15_k < past30_k)
        
        flat_window = kijun.iloc[idx-15 : idx-2]
        if len(flat_window) < 5: continue
        flat_diff = (flat_window.max() - flat_window.min()) / flat_window.min() if flat_window.min() > 0 else 1.0
        cond2 = (flat_diff <= flat_tolerance_pct)
        
        cond3 = (curr_k > prev1_k) or (prev1_k > prev2_k)
        
        curr_price = close.iloc[-1]
        event_price = close.iloc[idx]
        cond4 = (curr_price >= curr_k or event_price >= curr_k)
        
        if cond1 and cond2 and cond3 and cond4:
            candle_time = str(df['candle_date_time_kst'].iloc[idx]).replace('T', ' ')[:16] if 'candle_date_time_kst' in df.columns else f"{offset}봉 전"
            day_desc = "현재 240m봉" if offset == 0 else f"{offset}봉 전({candle_time})"
            return True, {
                'offset': offset,
                'candle_time': candle_time,
                'day_desc': day_desc,
                'idx': idx,
                'price': curr_price,
                'kijun': round(curr_k, 2),
                'rsi': round(df['RSI'].iloc[-1], 1),
                'macd': round(df['MACD'].iloc[-1], 2),
                'df': df
            }
    return False, None

def fetch_and_analyze(m, max_lookback_bars=6):
    url_240m = f"https://api.bithumb.com/v1/candles/minutes/240?market={m['market']}&count=200"
    try:
        res = requests.get(url_240m, headers={"accept": "application/json"}, timeout=5)
        if res.status_code == 200:
            df = process_240m_candle_df(res.json())
            ok, info = check_kijun_u_turn_240m(df, max_lookback_bars=max_lookback_bars)
            if ok:
                # 추가 조건: 일봉 기준 일목균형표 기준선(26) 각도가 1도 이상(>= 1.0°)인지 검사
                url_daily = f"https://api.bithumb.com/v1/candles/days?market={m['market']}&count=100"
                res_daily = requests.get(url_daily, headers={"accept": "application/json"}, timeout=5)
                if res_daily.status_code == 200:
                    daily_data = res_daily.json()
                    if isinstance(daily_data, list) and len(daily_data) >= 35:
                        df_daily = pd.DataFrame(daily_data).iloc[::-1].reset_index(drop=True)
                        for col in ['high_price', 'low_price']:
                            df_daily[col] = df_daily[col].astype(float)
                        df_daily['BaseLine'] = calc_mid_point(df_daily['high_price'], df_daily['low_price'], 26)
                        
                        # 동적 기준선 상승 구간 각도 계산
                        _, daily_kijun_angle = get_kijun_dynamic_angle(df_daily['BaseLine'])
                        
                        if daily_kijun_angle >= 1.0:
                            info['market'] = m['market']
                            info['korean_name'] = m['korean_name']
                            info['english_name'] = m['english_name']
                            info['daily_kijun_angle'] = round(daily_kijun_angle, 2)
                            return info
    except Exception:
        pass
    return None

def generate_240m_u_turn_pdf(pdf_path=None, lookback_bars=6, max_workers=6):
    if pdf_path is None:
        save_dir = "d:/pyprj/coinsts/U_Style_Code_4hour/report"
        os.makedirs(save_dir, exist_ok=True)
        pdf_path = os.path.join(save_dir, f"report_240m_kijun_u_turn_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf")
    else:
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    markets = get_krw_markets()
    print(f"[1/2] 빗썸 {len(markets)}개 코인 240분봉 기준선 U자형 턴어라운드 & 일봉기준선각도>=1.0° 스캔 중...")
    
    matched = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_and_analyze, m, lookback_bars): m for m in markets}
        for f in as_completed(futures):
            res = f.result()
            if res:
                matched.append(res)
                print(f" ★ 240m 포착 [{res['day_desc']}]: {res['korean_name']}({res['market']}) | 일봉기준선각도: {res['daily_kijun_angle']:+.2f}° | 현재가: {res['price']:,}원")

    matched.sort(key=lambda x: (x['offset'], -x['daily_kijun_angle'], x['korean_name']))

    if not matched:
        print("조건(240m U자턴 & 일봉기준선각도>=1.0°)을 만족하는 종목이 없습니다.")
        return None

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with PdfPages(pdf_path) as pdf:
        # 요약 표
        fig_tbl, ax_tbl = plt.subplots(figsize=(11.69, 8.27))
        ax_tbl.axis('off')
        ax_tbl.text(0.5, 0.95, "빗썸 240분봉(4시간) 일목 기준선 U자턴 & 일봉 기준선각도(>=1.0°) 리포트", fontsize=14, fontweight='bold', ha='center')
        ax_tbl.text(0.5, 0.91, f"분석 일시: {now_str} | 조건: 240분봉 기준선(30) U자턴(최근 {lookback_bars}봉) & 일봉 기준선 각도 >= 1.0° | 총 {len(matched)}개", fontsize=9.5, color='gray', ha='center')

        rows = [[c['market'], c['korean_name'], c['day_desc'], f"{c['price']:,}", f"{c['kijun']:,}", f"{c['daily_kijun_angle']:+.2f}°", f"{c['rsi']:.1f}", f"{c['macd']:,}"] for c in matched]
        tbl = ax_tbl.table(cellText=rows, colLabels=['마켓코드', '한글명', '포착 240m 시점', '현재가(원)', '240m기준선(30)', '일봉 기준선 각도', 'RSI', 'MACD'], cellLoc='center', loc='center', bbox=[0.05, 0.1, 0.9, 0.75])
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8.5)
        for col_i in range(8):
            tbl[(0, col_i)].set_facecolor('#117a65')
            tbl[(0, col_i)].set_text_props(color='white', fontweight='bold')
        pdf.savefig(fig_tbl)
        plt.close(fig_tbl)

        # 코인별 3단 차트
        for idx, item in enumerate(matched, 1):
            fig, (ax_p, ax_m, ax_r) = plt.subplots(3, 1, figsize=(11.69, 8.27), gridspec_kw={'height_ratios': [3.0, 1.2, 1.2]}, sharex=True)
            df = item['df']
            x = range(len(df))

            # 1. 가격 + 진한 거래량
            ax_v = ax_p.twinx()
            v_cols = ['#e31a1c' if df['Close'].iloc[i] >= (df['Close'].iloc[i-1] if i > 0 else df['Close'].iloc[i]) else '#1f78b4' for i in range(len(df))]
            ax_v.bar(x, df['Volume'], color=v_cols, alpha=0.55, width=0.75)
            ax_v.set_ylim(0, df['Volume'].max() * 3.8 if df['Volume'].max() > 0 else 1)
            ax_v.grid(False)

            ax_p.set_zorder(ax_v.get_zorder() + 1)
            ax_p.patch.set_visible(False)
            ax_p.plot(x, df['Close'], label='종가', color='black', linewidth=1.4)
            ax_p.plot(x, df['ConversionLine'], label='전환선(10)', color='#e31a1c', linewidth=1.2)
            ax_p.plot(x, df['BaseLine'], label='기준선(30)', color='#1f78b4', linewidth=1.4)
            ax_p.plot(x, df['Span1'], label='선행1(30)', color='#33a02c', linewidth=0.8, linestyle='--')
            ax_p.plot(x, df['Span2'], label='선행2(60)', color='#ff7f00', linewidth=0.8, linestyle='--')
            ax_p.fill_between(x, df['Span1'], df['Span2'], where=(df['Span1'] >= df['Span2']), color='#b2df8a', alpha=0.3)
            ax_p.fill_between(x, df['Span1'], df['Span2'], where=(df['Span1'] < df['Span2']), color='#fb9a99', alpha=0.3)

            # 포착 지점 표시
            e_idx = item['idx']
            ax_p.scatter(e_idx, df['BaseLine'].iloc[e_idx], color='gold', s=140, zorder=6, edgecolors='red', linewidth=1.5, label=f"240mU자턴[{item['day_desc']}]")

            ax_p.set_title(f"[{idx}/{len(matched)}] {item['korean_name']} ({item['market']}) - 240m 일목 [포착: {item['day_desc']}] | 현재가: {item['price']:,}원 | 240m기준선: {item['kijun']:,}원 | 일봉기준선각도: {item['daily_kijun_angle']:+.2f}°", fontsize=10, fontweight='bold', color='#0e6251')
            ax_p.set_ylabel("가격 (KRW)", fontsize=8.5)
            ax_p.legend(loc='upper left', fontsize=7.5, ncol=3)
            ax_p.grid(True, linestyle=':', alpha=0.5)

            # 2. MACD
            ax_m.plot(x, df['MACD'], color='#1f78b4', linewidth=1.1)
            ax_m.plot(x, df['MACD_Signal'], color='#e31a1c', linewidth=1.1, linestyle='--')
            ax_m.bar(x, df['MACD_Hist'], color=['#e31a1c' if v >= 0 else '#1f78b4' for v in df['MACD_Hist']], alpha=0.5, width=0.8)
            ax_m.axhline(0, color='gray', linestyle=':', linewidth=0.7)
            ax_m.set_ylabel("MACD", fontsize=8.5)
            ax_m.grid(True, linestyle=':', alpha=0.5)

            # 3. RSI
            ax_r.plot(x, df['RSI'], color='#8e44ad', linewidth=1.2)
            ax_r.axhline(70, color='#e31a1c', linestyle='--')
            ax_r.axhline(30, color='#1f78b4', linestyle='--')
            ax_r.set_ylim(0, 100)
            ax_r.set_ylabel("RSI", fontsize=8.5)
            ax_r.grid(True, linestyle=':', alpha=0.5)

            plt.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

    full_pdf_path = os.path.abspath(pdf_path)
    print(f"\n[성공] 240분봉 U자형 턴어라운드 PDF 리포트 생성 완료!\n -> 저장 위치: '{full_pdf_path}'")
    return full_pdf_path

if __name__ == "__main__":
    generate_240m_u_turn_pdf(lookback_bars=6)
