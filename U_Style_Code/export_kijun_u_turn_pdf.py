"""
========================================================================================
 [모듈 명]: U_Style_Code/export_kijun_u_turn_pdf.py
 [구현 목적]:
   - 암호화폐 30일 일목균형표 기준선(30일) U자형 턴어라운드가 
     **최근 2일전부터 오늘 현재까지(0일전, 1일전, 2일전)** 발생한 코인을 스캔하여
     일목균형표(진한 거래량 포함), MACD, RSI 차트 PDF 리포트 자동 생성
   - **저장 위치**: U_Style_Code/report/report_kijun_u_turn_recent_YYYYMMDDHHMMSS.pdf
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

def process_daily_candle_df(data):
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
    df['Close'] = df['trade_price']
    df['Volume'] = df['candle_acc_trade_volume'].astype(float) if 'candle_acc_trade_volume' in df.columns else 0.0
    
    # 30일 코인 전용 일목 (10, 30, 60, 30)
    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 10)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 30)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(30)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 60).shift(30)
    df['RSI'] = calc_rsi(df['Close'], 14)
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calc_macd(df['Close'])
    return df

def check_kijun_u_turn_recent_days(df, max_lookback_days=2, flat_tolerance_pct=0.010):
    """최근 2일전~오늘현재까지 (offset 0, 1, 2) U자 턴어라운드 탐색"""
    n = len(df)
    if n < 60: return False, None
    kijun = df['BaseLine']
    close = df['Close']
    
    for offset in range(max_lookback_days + 1):
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
            event_date = str(df['candle_date_time_kst'].iloc[idx])[:10] if 'candle_date_time_kst' in df.columns else f"{offset}일 전"
            day_desc = "오늘(0일전)" if offset == 0 else f"{offset}일전({event_date})"
            return True, {
                'offset': offset,
                'event_date': event_date,
                'day_desc': day_desc,
                'idx': idx,
                'price': curr_price,
                'kijun': round(curr_k, 2),
                'rsi': round(df['RSI'].iloc[-1], 1),
                'macd': round(df['MACD'].iloc[-1], 2),
                'df': df
            }
    return False, None

def fetch_and_analyze(m, max_lookback_days=2):
    url = f"https://api.bithumb.com/v1/candles/days?market={m['market']}&count=200"
    try:
        res = requests.get(url, headers={"accept": "application/json"}, timeout=5)
        if res.status_code == 200:
            df = process_daily_candle_df(res.json())
            ok, info = check_kijun_u_turn_recent_days(df, max_lookback_days=max_lookback_days)
            if ok:
                info['market'] = m['market']
                info['korean_name'] = m['korean_name']
                info['english_name'] = m['english_name']
                return info
    except Exception:
        pass
    return None

def generate_u_turn_pdf(pdf_path=None, lookback_days=2, max_workers=6):
    # PDF 저장 위치: U_Style_Code/report 폴더 하위로 변경
    if pdf_path is None:
        save_dir = "d:/pyprj/coinsts/U_Style_Code/report"
        os.makedirs(save_dir, exist_ok=True)
        pdf_path = os.path.join(save_dir, f"report_kijun_u_turn_recent_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf")
    else:
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    markets = get_krw_markets()
    print(f"[1/2] 최근 {lookback_days}일전~오늘현재 범위 30일 기준선 U자형 턴어라운드 스캔 중...")
    
    matched = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_and_analyze, m, lookback_days): m for m in markets}
        for f in as_completed(futures):
            res = f.result()
            if res:
                matched.append(res)
                print(f" ★ 포착 [{res['day_desc']}]: {res['korean_name']}({res['market']}) | 현재가: {res['price']:,}원")

    matched.sort(key=lambda x: (x['offset'], x['korean_name']))

    if not matched:
        print("조건을 만족하는 종목이 없습니다.")
        return None

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with PdfPages(pdf_path) as pdf:
        # 요약 표
        fig_tbl, ax_tbl = plt.subplots(figsize=(11.69, 8.27))
        ax_tbl.axis('off')
        ax_tbl.text(0.5, 0.95, "최근 2일전 ~ 오늘 현재 30일 기준선 U자형 턴어라운드 리포트", fontsize=14, fontweight='bold', ha='center')
        ax_tbl.text(0.5, 0.91, f"분석 일시: {now_str} | 최근 3일간 턴어라운드 포착 총 {len(matched)}개", fontsize=9.5, color='gray', ha='center')

        rows = [[c['market'], c['korean_name'], c['day_desc'], f"{c['price']:,}", f"{c['kijun']:,}", f"{c['rsi']:.1f}", f"{c['macd']:,}"] for c in matched]
        tbl = ax_tbl.table(cellText=rows, colLabels=['마켓코드', '한글명', '포착 시점', '현재가(원)', '기준선(30일)', 'RSI', 'MACD'], cellLoc='center', loc='center', bbox=[0.05, 0.1, 0.9, 0.75])
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8.5)
        for col_i in range(7):
            tbl[(0, col_i)].set_facecolor('#8e44ad')
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
            ax_p.scatter(e_idx, df['BaseLine'].iloc[e_idx], color='gold', s=140, zorder=6, edgecolors='red', linewidth=1.5, label=f"30일U자턴어라운드[{item['day_desc']}]")

            ax_p.set_title(f"[{idx}/{len(matched)}] {item['korean_name']} ({item['market']}) - 30일 일목 [포착: {item['day_desc']}] | 현재가: {item['price']:,}원 | 30일기준선: {item['kijun']:,}원", fontsize=10.5, fontweight='bold', color='#4a235a')
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
    print(f"\n[성공] 최근 2일전~오늘 U자형 턴어라운드 PDF 리포트 생성 완료!\n -> 저장 위치: '{full_pdf_path}'")
    return full_pdf_path

if __name__ == "__main__":
    generate_u_turn_pdf(lookback_days=2)
