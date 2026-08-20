"""
========================================================================================
 [모듈 명]: export_daycross_ichimoku_pdf.py
 [구현 목적]:
   - 빗썸(Bithumb) 원화(KRW) 마켓 전 코인의 일봉(Daily) 시계열 200개 데이터를 수집하여,
     최근 3일 범위 이내에서 일목균형표 전환선(9)이 기준선(26)을 골든크로스(상향돌파)하고
     기준선(26)의 각도가 2도 이상(양의 각도 >= 2.0°)인 코인을 포착하여,
     분석 결과 및 일목균형표 + MACD 결합 차트 PDF 리포트(report_daily/report_daycross_YYYYMMDDHHMMSS.pdf)를 자동 발행합니다.

 [핵심 분석 조건]:
   - 최근 3개 일봉 시계열(t-2, t-1, t) 내에서 prev_tenkan <= prev_kijun AND curr_tenkan > curr_kijun 교차 감지
   - 기준선(26) 양의 각도 조건: 기준선 각도 >= 2.0°

 [PDF 구성 사양]:
   - Page 1: 골든크로스 전체 통계 요약 표 (마켓코드, 한글명, 현재가, 전환선, 기준선, 갭%, 기준선각도, 크로스 시점, RSI, MACD, 구름위치)
   - Page 2~N (1코인 1페이지):
     1) 상단: 일봉 일목균형표 차트 (종가, 전환선, 기준선, 구름대 + 골든크로스 발생 지점 황금색 마커 강조)
     2) 하단: 일봉 MACD 차트 (MACD Line, Signal Line, Oscillator Histogram)

 [사용 및 실행 방법]:
   - 터미널 실행: python export_daycross_ichimoku_pdf.py
   - 모듈 임포트: from export_daycross_ichimoku_pdf import generate_daycross_pdf_report
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

def get_kijun_dynamic_angle(series):
    """
    기준선 각도 계산:
    현재 기준선 값이 이전 값들 중 '같지 않은 가장 최근 이전 값'보다 큰 경우,
    그 이전 값의 시작 위치부터 현재값까지의 구간으로 각도(도, Degree)를 계산.
    상승하지 않았거나 이전 값이 없으면 (0.0, 0.0) 반환.
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
    """일봉 JSON 데이터를 DataFrame으로 변환 및 일목/MACD/RSI 계산"""
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
        
    df['Close'] = df['trade_price']
    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 9)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 26)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(26)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 52).shift(26)
    df['RSI'] = calc_rsi(df['Close'], 14)
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calc_macd(df['Close'])
    return df

def fetch_and_analyze_single_coin_daycross(m, count=200, lookback_bars=3):
    """
    단일 코인의 일봉 시계열을 수집하여 최근 lookback_bars(기본 최근 3일) 이내에
    일목균형표 전환선(9)이 기준선(26)을 골든크로스(상향돌파)하고,
    기준선 각도가 2도 이상(양의 각도 >= 2.0°)인지 검사
    """
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
                
                # 최근 lookback_bars(예: 최근 3봉) 범위 내 골든크로스 검사
                # 골든크로스 조건: 이전 봉 tenkan <= kijun AND 현재/다음 봉 tenkan > kijun
                cross_detected = False
                cross_bar_index = -1
                cross_date = ""
                
                # 일봉 뒤에서부터 lookback_bars 개 봉 검사
                for b_idx in range(1, lookback_bars + 1):
                    idx = len(df) - b_idx
                    if idx >= 1:
                        prev_tenkan = df['ConversionLine'].iloc[idx - 1]
                        prev_kijun = df['BaseLine'].iloc[idx - 1]
                        curr_tenkan = df['ConversionLine'].iloc[idx]
                        curr_kijun = df['BaseLine'].iloc[idx]
                        
                        if not pd.isna(prev_tenkan) and not pd.isna(prev_kijun) and not pd.isna(curr_tenkan) and not pd.isna(curr_kijun):
                            if (prev_tenkan <= prev_kijun) and (curr_tenkan > curr_kijun):
                                cross_detected = True
                                cross_bar_index = b_idx - 1  # 0: 현재봉, 1: 1봉전, 2: 2봉전
                                if 'candle_date_time_kst' in df.columns:
                                    cross_date = str(df['candle_date_time_kst'].iloc[idx])[:10]
                                break
                                
                if cross_detected:
                    last_row = df.iloc[-1]
                    price = last_row['Close']
                    tenkan = last_row['ConversionLine']
                    kijun = last_row['BaseLine']
                    
                    # 기준선 동적 상승 각도 계산 (이전 다른 값 지점부터 현재봉까지)
                    _, kijun_angle = get_kijun_dynamic_angle(df['BaseLine'])
                    
                    past_tenkan = df['ConversionLine'].iloc[-10:]
                    _, tenkan_angle = get_slope_and_angle(past_tenkan.dropna())
                    
                    # 기준선 양의 각도 조건 (각도 >= 2.0도)
                    if kijun_angle < 2.0:
                        return None
                    
                    # 구름대 위치 파악
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
                        
                    timing_str = "오늘(현재봉)" if cross_bar_index == 0 else f"{cross_bar_index}일 전"
                    
                    return {
                        'market': market_code,
                        'korean_name': korean_name,
                        'english_name': english_name,
                        'close_price': price,
                        'conversion_line': round(tenkan, 2),
                        'base_line': round(kijun, 2),
                        'tenkan_kijun_gap_pct': round(((tenkan - kijun) / kijun) * 100, 2) if kijun > 0 else 0.0,
                        'kijun_angle': round(kijun_angle, 2),
                        'tenkan_angle': round(tenkan_angle, 2),
                        'rsi': round(last_row['RSI'], 1) if not pd.isna(last_row['RSI']) else 0.0,
                        'macd': round(last_row['MACD'], 2) if not pd.isna(last_row['MACD']) else 0.0,
                        'macd_signal': round(last_row['MACD_Signal'], 2) if not pd.isna(last_row['MACD_Signal']) else 0.0,
                        'cross_timing': timing_str,
                        'cross_date': cross_date,
                        'cross_bar_index': cross_bar_index,
                        'cloud_pos': cloud_pos,
                        'df': df
                    }
    except Exception:
        pass
    return None

def generate_daycross_pdf_report(pdf_path=None, max_coins=None, max_workers=6, upload_gdrive=True):
    """
    일봉 기준 일목균형표 전환선 > 기준선 골든크로스 & 기준선 각도 >= 2.0° 포착 코인 대상 PDF 리포트 생성 및 저장
    """
    if pdf_path is None:
        save_dir = "d:/pyprj/coinsts/report_daily"
        os.makedirs(save_dir, exist_ok=True)
        filename = f"report_daycross_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_path = os.path.join(save_dir, filename)
    else:
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    markets = get_krw_markets()
    if max_coins:
        markets = markets[:max_coins]

    print(f"[1/3] 총 {len(markets)}개 원화 코인 [일봉 일목균형표 골든크로스 & 기준선각도>=2.0°] 분석 중 (스레드수: {max_workers})...")
    
    captured_list = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_and_analyze_single_coin_daycross, m): m for m in markets}
        for future in as_completed(futures):
            res = future.result()
            if res:
                captured_list.append(res)
                print(f" ★ 일봉 골든크로스 포착: {res['korean_name']}({res['english_name']} / {res['market']}) | 시점: {res['cross_timing']} | 기준선각도: {res['kijun_angle']:+.2f}° | 현재가: {res['close_price']:,}원")
                
    # 발생 시점(최신 순) 및 기준선 각도 내림차순 정렬
    captured_list.sort(key=lambda x: (x['cross_bar_index'], -x['kijun_angle'], -x['tenkan_kijun_gap_pct']))
    
    print(f"\n[2/3] 총 {len(captured_list)}개 포착 코인 [일봉 일목균형표 + MACD 차트] PDF 리포트 생성 중...")
    
    if not captured_list:
        print("최근 일봉 기준 골든크로스 및 기준선각도>=2.0° 조건에 맞는 코인이 없어 PDF 생성을 중단합니다.")
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
                f"{c['tenkan_kijun_gap_pct']:+.2f}%",
                f"{c['kijun_angle']:+.2f}°",
                c['cross_timing'],
                f"{c['rsi']:.1f}",
                f"{c['macd']:,}",
                c['cloud_pos']
            ] for c in captured_list
        ]
        
        col_labels = ['마켓코드', '한글명', '영문명', '현재가(원)', '전환선(9)', '기준선(26)', '전환-기준 갭', '기준선 각도', '크로스 시점', 'RSI', 'MACD', '구름대 위치']

        for page_idx in range(0, len(summary_rows_all), chunk_size):
            chunk = summary_rows_all[page_idx : page_idx + chunk_size]
            fig_table, ax_table = plt.subplots(figsize=(11.69, 8.27))
            ax_table.axis('off')

            title_text = "빗썸 일목균형표 일봉 전환선-기준선 골든크로스 포착 리포트"
            subtitle_text = f"분석 일시: {now_str} | 조건: 일봉(Daily) 전환선(9) > 기준선(26) 골든크로스 & 기준선 각도 >= 2.0° | 총 {len(captured_list)}개 (p.{page_idx//chunk_size + 1})"
            
            ax_table.text(0.5, 0.96, title_text, fontsize=15, fontweight='bold', ha='center', va='top')
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
                cell.set_facecolor('#8e44ad')  # 보라색 헤더
                cell.set_text_props(color='white', fontweight='bold')
                
            plt.tight_layout()
            pdf.savefig(fig_table)
            plt.close(fig_table)

        # -------------------------------------------------------------
        # 개별 코인 차트 페이지 (상단: 일봉 일목균형표 / 하단: 일봉 MACD)
        # -------------------------------------------------------------
        for idx, coin_data in enumerate(captured_list, 1):
            fig, (ax_price, ax_macd) = plt.subplots(
                2, 1, figsize=(11.69, 8.27),
                gridspec_kw={'height_ratios': [3.2, 1.2]},
                sharex=False
            )
            
            k_name = coin_data['korean_name']
            e_name = coin_data['english_name']
            m_code = coin_data['market']
            price = coin_data['close_price']
            df = coin_data['df']
            x_range = range(len(df))
            
            # ---------------------------------------------------------
            # 상단 차트: 일봉 기준 일목균형표 차트
            # ---------------------------------------------------------
            ax_price.plot(x_range, df['Close'], label='일봉 종가', color='black', linewidth=1.4)
            ax_price.plot(x_range, df['ConversionLine'], label='전환선(9)', color='#e31a1c', linewidth=1.3)
            ax_price.plot(x_range, df['BaseLine'], label='기준선(26)', color='#1f78b4', linewidth=1.3)
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

            # 골든크로스 포착 강조 마커 표시
            cross_idx = len(df) - 1 - coin_data['cross_bar_index']
            cross_price = df['ConversionLine'].iloc[cross_idx]
            ax_price.scatter(
                cross_idx, cross_price, color='gold', s=120, zorder=5, edgecolors='red', linewidth=1.5,
                label=f"골든크로스({coin_data['cross_timing']})"
            )

            title_str = f"[{idx}/{len(captured_list)}] {k_name} ({e_name} / {m_code})  -  [일봉 일목 골든크로스]  |  현재가: {price:,}원  |  기준선각도: {coin_data['kijun_angle']:+.2f}°  |  크로스: {coin_data['cross_timing']}"
            ax_price.set_title(title_str, fontsize=11, fontweight='bold', color='#4a235a', pad=6)
            ax_price.set_ylabel("가격 (KRW)", fontsize=9)
            ax_price.legend(loc='upper left', fontsize=8, framealpha=0.85, ncol=3)
            ax_price.grid(True, linestyle=':', alpha=0.5)

            # ---------------------------------------------------------
            # 하단 차트: 일봉 MACD 차트
            # ---------------------------------------------------------
            ax_macd.plot(x_range, df['MACD'], label='MACD(12,26)', color='#1f78b4', linewidth=1.1)
            ax_macd.plot(x_range, df['MACD_Signal'], label='Signal(9)', color='#e31a1c', linewidth=1.1, linestyle='--')
            
            colors_hist = ['#e31a1c' if val >= 0 else '#1f78b4' for val in df['MACD_Hist']]
            ax_macd.bar(x_range, df['MACD_Hist'], color=colors_hist, alpha=0.4, width=0.8, label='Oscillator')
            ax_macd.axhline(0, color='gray', linestyle=':', linewidth=0.7)
            
            ax_macd.set_ylabel("일봉 MACD", fontsize=8.5)
            ax_macd.set_xlabel("일자 (최신 일봉 시계열)", fontsize=8.5)
            ax_macd.legend(loc='upper left', fontsize=7.5, framealpha=0.85, ncol=3)
            ax_macd.grid(True, linestyle=':', alpha=0.5)

            plt.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

    full_pdf_path = os.path.abspath(pdf_path)
    print(f"\n[3/3] 일봉 일목 골든크로스 PDF 리포트 생성 완료!\n -> 저장 위치: '{full_pdf_path}'")

    if upload_gdrive:
        try:
            from upload_to_gdrive import upload_pdf_to_gdrive
            upload_pdf_to_gdrive(full_pdf_path, folder_name="report_daily", user_email="hhokyung@gmail.com")
        except Exception as e:
            print(f"구글 드라이브 업로드 안내: {e}")

    return full_pdf_path

if __name__ == "__main__":
    generate_daycross_pdf_report(max_workers=6)

