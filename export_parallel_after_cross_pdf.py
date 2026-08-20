"""
========================================================================================
 [모듈 명]: export_parallel_after_cross_pdf.py
 [구현 목적]:
   - 빗썸(Bithumb) 원화(KRW) 마켓에 상장된 전 코인의 일봉(Daily) 시계열 200개 데이터를 스캔하여,
     과거 일목균형표 전환선(9)이 기준선(26)을 골든크로스(상향돌파)한 이후
     전환선과 기준선이 수치 괴리율 1.5% 이내로 90% 이상 동일/평행 밀착 유지된 코인을 포착합니다.
   - 포착된 코인의 일목균형표(거래량 포함), MACD, RSI 차트를 한 페이지로 결합한 3단 시각화 리포트를
     PDF 문서(report_daily/report_parallel_cross_YYYYMMDDHHMMSS.pdf)로 자동 발행합니다.

 [핵심 분석 조건]:
   1. 골든크로스 발생: 최근 200봉 이내 전환선(9)이 기준선(26)을 상향 돌파 (prev_tenkan <= prev_kijun AND curr_tenkan > curr_kijun)
   2. 평행 밀착 유지율: 골든크로스 직후 관찰 구간(12봉) 중 두 지표선의 수치 괴리율(|전환선-기준선|/기준선 <= 1.5%)이
      90% 이상 유지되는 코인 선별

 [PDF 구성 사양]:
   - Page 1: 전체 포착 코인 통계 요약 표 (마켓코드, 한글명, 현재가, 크로스일자, 경과일, 평행유지율, RSI, MACD)
   - Page 2~N (1코인 1페이지):
     1) 상단: 일봉 일목균형표 차트 + **이중 Y축 거래량 바 차트** (종가, 전환선, 기준선, 구름대 + 거래량 + 황금마커 + 평행구간 하이라이트)
     2) 중단: 일봉 MACD 차트 (MACD Line, Signal Line, Oscillator Histogram)
     3) 하단: 일봉 RSI 차트 (RSI 지수선, 과매수 70 / 과매도 30 레벨선)

 [사용 및 실행 방법]:
   - 터미널 실행: python export_parallel_after_cross_pdf.py
   - 모듈 임포트: from export_parallel_after_cross_pdf import generate_parallel_cross_pdf_report
========================================================================================
"""

import requests
import numpy as np
import pandas as pd
import time
import os
import argparse
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
    response = requests.get(url, headers=headers)
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

def calc_mid_point(high, low, window):
    """지정된 기간 동안의 (최고가 + 최저가) / 2 계산"""
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

def calc_rsi(series, period=14):
    """RSI 지수 계산"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
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
    """일봉 JSON 데이터를 DataFrame으로 변환 및 일목/MACD/RSI/거래량 계산"""
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
        
    df['Close'] = df['trade_price']
    if 'candle_acc_trade_volume' in df.columns:
        df['Volume'] = df['candle_acc_trade_volume'].astype(float)
    else:
        df['Volume'] = 0.0

    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 9)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 26)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(26)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 52).shift(26)
    df['RSI'] = calc_rsi(df['Close'], 14)
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calc_macd(df['Close'])
    return df

def analyze_parallel_after_cross(df, min_parallel_ratio=0.90, max_gap_pct=0.015, eval_window_bars=12):
    """
    일봉 200개 데이터 중 어느 시점에 전환선이 기준선을 골든크로스 한 후,
    그 이후 구간(eval_window_bars 봉) 동안 전환선과 기준선이 괴리율 max_gap_pct(1.5%) 이내로
    평행/동일하게 유지된 비율이 min_parallel_ratio(90%) 이상인 코인 탐색
    """
    n = len(df)
    matched_events = []
    
    for i in range(30, n - 2):
        prev_t = df['ConversionLine'].iloc[i-1]
        prev_k = df['BaseLine'].iloc[i-1]
        curr_t = df['ConversionLine'].iloc[i]
        curr_k = df['BaseLine'].iloc[i]
        
        if pd.isna(prev_t) or pd.isna(prev_k) or pd.isna(curr_t) or pd.isna(curr_k):
            continue
            
        # 1. 골든크로스 발생 (전환선이 기준선을 위로 돌파)
        if (prev_t <= prev_k) and (curr_t > curr_k):
            # 골든크로스 발생 직후 eval_window_bars 봉 구간 추적
            eval_end = min(i + eval_window_bars, n)
            eval_df = df.iloc[i:eval_end]
            
            if len(eval_df) >= 4:
                gaps = np.abs(eval_df['ConversionLine'] - eval_df['BaseLine']) / eval_df['BaseLine']
                parallel_ratio = (gaps <= max_gap_pct).mean()
                
                if parallel_ratio >= min_parallel_ratio:
                    cross_date = str(df['candle_date_time_kst'].iloc[i])[:10] if 'candle_date_time_kst' in df.columns else f"{n-1-i}일 전"
                    matched_events.append({
                        'cross_index': i,
                        'cross_date': cross_date,
                        'bars_ago': n - 1 - i,
                        'eval_bars': len(eval_df),
                        'parallel_ratio': round(parallel_ratio * 100, 1),
                        'avg_gap_pct': round(gaps.mean() * 100, 2)
                    })
                    
    if matched_events:
        best_event = matched_events[-1]
        return True, best_event
    return False, None

def fetch_and_analyze_single_coin(m, count=200):
    """단일 코인 일봉 데이터 조회 및 골든크로스 후 평행 유지 분석"""
    market_code = m['market']
    korean_name = m['korean_name']
    english_name = m['english_name']
    
    headers = {"accept": "application/json"}
    url_daily = f"https://api.bithumb.com/v1/candles/days?market={market_code}&count={count}"
    
    try:
        res = requests.get(url_daily, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) >= 60:
                df = process_daily_candle_df(data)
                is_matched, event_info = analyze_parallel_after_cross(df)
                
                if is_matched:
                    last_row = df.iloc[-1]
                    price = last_row['Close']
                    tenkan = last_row['ConversionLine']
                    kijun = last_row['BaseLine']
                    
                    past_kijun = df['BaseLine'].iloc[-10:]
                    _, kijun_angle = get_slope_and_angle(past_kijun.dropna())
                    
                    span1, span2 = last_row['Span1'], last_row['Span2']
                    if not pd.isna(span1) and not pd.isna(span2):
                        cloud_top = max(span1, span2)
                        cloud_bottom = min(span1, span2)
                        if price > cloud_top:
                            cloud_pos = "구름위(양호)"
                        elif price < cloud_bottom:
                            cloud_pos = "구름아래(주의)"
                        else:
                            cloud_pos = "구름내부"
                    else:
                        cloud_pos = "-"
                        
                    return {
                        'market': market_code,
                        'korean_name': korean_name,
                        'english_name': english_name,
                        'close_price': price,
                        'conversion_line': round(tenkan, 2),
                        'base_line': round(kijun, 2),
                        'kijun_angle': round(kijun_angle, 2),
                        'cross_date': event_info['cross_date'],
                        'bars_ago': event_info['bars_ago'],
                        'cross_index': event_info['cross_index'],
                        'eval_bars': event_info['eval_bars'],
                        'parallel_ratio': event_info['parallel_ratio'],
                        'avg_gap_pct': event_info['avg_gap_pct'],
                        'rsi': round(last_row['RSI'], 1) if not pd.isna(last_row['RSI']) else 0.0,
                        'macd': round(last_row['MACD'], 2) if not pd.isna(last_row['MACD']) else 0.0,
                        'cloud_pos': cloud_pos,
                        'df': df
                    }
    except Exception:
        pass
    return None

def generate_parallel_cross_pdf_report(pdf_path=None, max_coins=None, max_workers=6, upload_gdrive=True):
    """
    골든크로스 후 전환선-기준선 90% 이상 평행 유지 코인 PDF 리포트 생성 및 저장 (일목+거래량 포함)
    """
    if pdf_path is None:
        save_dir = "d:/pyprj/coinsts/report_daily"
        os.makedirs(save_dir, exist_ok=True)
        filename = f"report_parallel_cross_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_path = os.path.join(save_dir, filename)
    else:
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    markets = get_krw_markets()
    if max_coins:
        markets = markets[:max_coins]

    print(f"[1/3] 총 {len(markets)}개 원화 코인 [골든크로스 후 전환선-기준선 90%이상 평행 유지] 분석 중 (스레드수: {max_workers})...")
    
    captured_list = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_and_analyze_single_coin, m): m for m in markets}
        for future in as_completed(futures):
            res = future.result()
            if res:
                captured_list.append(res)
                print(f" ★ 포착 코인: {res['korean_name']}({res['english_name']} / {res['market']}) | 크로스일자: {res['cross_date']} ({res['bars_ago']}일전) | 평행유지율: {res['parallel_ratio']}%")
                
    captured_list.sort(key=lambda x: (x['bars_ago'], -x['parallel_ratio']))
    
    print(f"\n[2/3] 총 {len(captured_list)}개 포착 코인 [일목균형표(거래량포함) + MACD + RSI] 3단 시각화 PDF 생성 중...")
    
    if not captured_list:
        print("조건을 만족하는 코인이 없어 PDF 생성을 중단합니다.")
        return None

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with PdfPages(pdf_path) as pdf:
        # -------------------------------------------------------------
        # 표지 및 요약 표 페이지
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
                c['cross_date'],
                f"{c['bars_ago']}일 전",
                f"{c['parallel_ratio']}%",
                f"{c['rsi']:.1f}",
                f"{c['macd']:,}"
            ] for c in captured_list
        ]
        
        col_labels = ['마켓코드', '한글명', '영문명', '현재가(원)', '전환선(9)', '기준선(26)', '크로스 일자', '경과일', '평행 유지율', 'RSI', 'MACD']

        for page_idx in range(0, len(summary_rows_all), chunk_size):
            chunk = summary_rows_all[page_idx : page_idx + chunk_size]
            fig_table, ax_table = plt.subplots(figsize=(11.69, 8.27))
            ax_table.axis('off')

            title_text = "빗썸 일목균형표 골든크로스 후 전환선-기준선 90%이상 평행유지 리포트"
            subtitle_text = f"분석 일시: {now_str} | 조건: 전환선>기준선 골든크로스 후 두 선의 수치 괴리율 90%이상 동일/평행 유지 | 총 {len(captured_list)}개 (p.{page_idx//chunk_size + 1})"
            
            ax_table.text(0.5, 0.96, title_text, fontsize=14, fontweight='bold', ha='center', va='top')
            ax_table.text(0.5, 0.92, subtitle_text, fontsize=9.5, color='gray', ha='center', va='top')

            table = ax_table.table(
                cellText=chunk,
                colLabels=col_labels,
                cellLoc='center',
                loc='center',
                bbox=[0.02, 0.05, 0.96, 0.82]
            )
            table.auto_set_font_size(False)
            table.set_fontsize(8)
            
            for col_i in range(len(col_labels)):
                cell = table[(0, col_i)]
                cell.set_facecolor('#117a65')
                cell.set_text_props(color='white', fontweight='bold')
                
            plt.tight_layout()
            pdf.savefig(fig_table)
            plt.close(fig_table)

        # -------------------------------------------------------------
        # 개별 코인 차트 페이지 (3단 Subplot: 일목균형표+거래량, MACD, RSI)
        # -------------------------------------------------------------
        for idx, coin_data in enumerate(captured_list, 1):
            fig, (ax_price, ax_macd, ax_rsi) = plt.subplots(
                3, 1, figsize=(11.69, 8.27),
                gridspec_kw={'height_ratios': [3.0, 1.2, 1.2]},
                sharex=True
            )
            
            k_name = coin_data['korean_name']
            e_name = coin_data['english_name']
            m_code = coin_data['market']
            price = coin_data['close_price']
            df = coin_data['df']
            x_range = range(len(df))
            
            # ---------------------------------------------------------
            # 1. 일봉 일목균형표 차트 + 이중 Y축 거래량(Volume) 바 차트
            # ---------------------------------------------------------
            # (1-A) 거래량(Volume) 이중 Y축 렌더링 (진한 색상 표기: alpha=0.55)
            ax_vol = ax_price.twinx()
            vol_colors = ['#e31a1c' if df['Close'].iloc[i] >= (df['Close'].iloc[i-1] if i > 0 else df['Close'].iloc[i]) else '#1f78b4' for i in range(len(df))]
            ax_vol.bar(x_range, df['Volume'], color=vol_colors, alpha=0.55, width=0.75, label='거래량')
            max_vol = df['Volume'].max() if df['Volume'].max() > 0 else 1.0
            ax_vol.set_ylim(0, max_vol * 3.8)  # 거래량이 차트 하단 1/4 영역 이하에 오도록 범위 조율
            ax_vol.set_ylabel("거래량", fontsize=7.5, color='#555555')
            ax_vol.tick_params(axis='y', labelcolor='#555555', labelsize=7)
            ax_vol.grid(False)

            # (1-B) 일목균형표 주 가격 차트 렌더링
            ax_price.set_zorder(ax_vol.get_zorder() + 1)
            ax_price.patch.set_visible(False) # 배경 투명화 처리로 하단 거래량 바가 비치도록 설정
            
            ax_price.plot(x_range, df['Close'], label='일봉 종가', color='black', linewidth=1.4)
            ax_price.plot(x_range, df['ConversionLine'], label='전환선(9)', color='#e31a1c', linewidth=1.2)
            ax_price.plot(x_range, df['BaseLine'], label='기준선(26)', color='#1f78b4', linewidth=1.2)
            ax_price.plot(x_range, df['Span1'], label='선행스팬1', color='#33a02c', linewidth=0.8, linestyle='--')
            ax_price.plot(x_range, df['Span2'], label='선행스팬2', color='#ff7f00', linewidth=0.8, linestyle='--')
            
            ax_price.fill_between(
                x_range, df['Span1'], df['Span2'],
                where=(df['Span1'] >= df['Span2']),
                color='#b2df8a', alpha=0.35, label='양운'
            )
            ax_price.fill_between(
                x_range, df['Span1'], df['Span2'],
                where=(df['Span1'] < df['Span2']),
                color='#fb9a99', alpha=0.35, label='음운'
            )

            # 골든크로스 발생 지점 표시
            c_idx = coin_data['cross_index']
            c_price = df['ConversionLine'].iloc[c_idx]
            ax_price.scatter(
                c_idx, c_price, color='gold', s=130, zorder=6, edgecolors='red', linewidth=1.5,
                label=f"골든크로스({coin_data['cross_date']})"
            )
            
            # 평행 유지 구간 배경 하이라이트
            eval_end_idx = min(c_idx + coin_data['eval_bars'], len(df))
            ax_price.axvspan(c_idx, eval_end_idx, color='yellow', alpha=0.2, label=f"평행유지구간({coin_data['parallel_ratio']}%)")

            title_str = (
                f"[{idx}/{len(captured_list)}] {k_name} ({e_name} / {m_code})  -  [일봉 일목균형표 + 거래량 차트]\n"
                f"현재종가: {price:,}원 | 골든크로스일자: {coin_data['cross_date']} ({coin_data['bars_ago']}일전) | 전환선-기준선 평행유지율: {coin_data['parallel_ratio']}%"
            )
            ax_price.set_title(title_str, fontsize=10.5, fontweight='bold', color='#0e6251', pad=6)
            ax_price.set_ylabel("가격 (KRW)", fontsize=8.5)
            ax_price.legend(loc='upper left', fontsize=7.5, framealpha=0.85, ncol=4)
            ax_price.grid(True, linestyle=':', alpha=0.5)

            # ---------------------------------------------------------
            # 2. 일봉 MACD 차트
            # ---------------------------------------------------------
            ax_macd.plot(x_range, df['MACD'], label='MACD(12,26)', color='#1f78b4', linewidth=1.1)
            ax_macd.plot(x_range, df['MACD_Signal'], label='Signal(9)', color='#e31a1c', linewidth=1.1, linestyle='--')
            
            colors_hist = ['#e31a1c' if val >= 0 else '#1f78b4' for val in df['MACD_Hist']]
            ax_macd.bar(x_range, df['MACD_Hist'], color=colors_hist, alpha=0.4, width=0.8, label='Oscillator')
            ax_macd.axhline(0, color='gray', linestyle=':', linewidth=0.7)
            
            ax_macd.set_ylabel("MACD", fontsize=8.5)
            ax_macd.legend(loc='upper left', fontsize=7.5, framealpha=0.85, ncol=3)
            ax_macd.grid(True, linestyle=':', alpha=0.5)

            # ---------------------------------------------------------
            # 3. 일봉 RSI 차트
            # ---------------------------------------------------------
            ax_rsi.plot(x_range, df['RSI'], label='RSI(14)', color='#8e44ad', linewidth=1.2)
            ax_rsi.axhline(70, color='#e31a1c', linestyle='--', linewidth=0.8, label='과매수(70)')
            ax_rsi.axhline(50, color='gray', linestyle=':', linewidth=0.7)
            ax_rsi.axhline(30, color='#1f78b4', linestyle='--', linewidth=0.8, label='과매도(30)')
            
            ax_rsi.set_ylim(0, 100)
            ax_rsi.set_ylabel("RSI", fontsize=8.5)
            ax_rsi.set_xlabel("일자 (최신 일봉 시계열)", fontsize=8.5)
            ax_rsi.legend(loc='upper left', fontsize=7.5, framealpha=0.85, ncol=3)
            ax_rsi.grid(True, linestyle=':', alpha=0.5)

            plt.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

    full_pdf_path = os.path.abspath(pdf_path)
    print(f"\n[3/3] 거래량 포함 골든크로스 후 평행유지 코인 PDF 리포트 생성 완료!\n -> 저장 위치: '{full_pdf_path}'")

    if upload_gdrive:
        try:
            from upload_to_gdrive import upload_pdf_to_gdrive
            upload_pdf_to_gdrive(full_pdf_path, folder_name="report_daily", user_email="hhokyung@gmail.com")
        except Exception as e:
            print(f"구글 드라이브 업로드 안내: {e}")

    return full_pdf_path

if __name__ == "__main__":
    generate_parallel_cross_pdf_report(max_workers=6)
