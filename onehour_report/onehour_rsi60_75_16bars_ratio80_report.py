"""
========================================================================================
 [모듈 명]: onehour_report/onehour_rsi60_75_16bars_ratio80_report.py
 [구현 목적]:
   - 빗썸 거래 전체 원화(KRW) 마켓 코인을 대상으로 200개 60분봉(1시간봉) 및 200개 일봉 데이터 수집
   - [매수 조건]:
     ① 1시간봉 기준 최근 16개봉(N-15 ~ N) 중 RSI(14) 값이 60 이상 75 이하(60 <= RSI <= 75) 조건 만족 봉 수가 13개 이상(80% 이상)
     ② [직전 3개봉 저RSI 필터]: 16개봉 바로 이전 3개봉(N-18, N-17, N-16 / 17~19번째 봉)의 RSI(14) 값이 모두 60 이하(<= 60.0)일 것!
   - 체결가(Close) vs 일목균형표 전환선(9) 이격도 및 이탈 위치 정보를 포함한 코인별 듀얼 3단 시각화 PDF 리포트 생성
   - [구글 드라이브 연동]: 생성된 PDF를 credentials.json 인증 정보를 통해 hhokyung@gmail.com 계정의 report_hour 폴더로 자동 업로드
   - **저장 위치**: onehour_report/report/onehour_rsi60_75_16bars_ratio80_report_YYYYMMDDHHMMSS.pdf
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

def process_candle_df(data):
    """캔들 JSON 데이터를 DataFrame으로 변환 및 일목(전환9, 기준26)/MACD/RSI 계산"""
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
        
    df['Close'] = df['trade_price']
    df['Volume'] = df['candle_acc_trade_volume'].astype(float) if 'candle_acc_trade_volume' in df.columns else 0.0
    
    # 일목균형표 계산 (전환선 9, 기준선 26, 선행스팬1 26, 선행스팬2 52)
    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 9)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 26)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(26)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 52).shift(26)
    
    # RSI 및 MACD
    df['RSI'] = calc_rsi(df['Close'], 14)
    df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = calc_macd(df['Close'])
    return df

def fetch_and_analyze_single_coin(m, count=200):
    """
    단일 코인의 60분봉 및 일봉 시계열 데이터 수집 및 분석 (16봉 기준 + 이전 3개봉 RSI <= 60 필터)
    포착 조건:
    1. 1시간봉 기준 최근 16개봉(N-15 ~ N) 중 60.0 <= RSI(14) <= 75.0 범위 조건 충족 봉 수 >= 13개 (>= 81.25%)
    2. [직전 3개봉 필터]: 16개봉 이전 3개봉(N-18, N-17, N-16 / 뒤에서 17, 18, 19번째 봉) RSI(14) <= 60.0 모두 만족!
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
            if isinstance(data_1h, list) and len(data_1h) >= 40:
                df_1h = process_candle_df(data_1h)
                
                # 1) 최근 16개봉 RSI 검증 (60 <= RSI <= 75)
                recent_16_rsi = df_1h['RSI'].iloc[-16:]
                valid_rsi_mask = (recent_16_rsi >= 60.0) & (recent_16_rsi <= 75.0)
                rsi_60_75_count = int(valid_rsi_mask.sum())
                rsi_60_75_ratio = (rsi_60_75_count / 16.0) * 100.0
                
                # 2) 직전 3개봉 RSI <= 60.0 검증 (N-18, N-17, N-16 봉)
                prev_3_rsi = df_1h['RSI'].iloc[-19:-16]
                prev_3_low_rsi_valid = (prev_3_rsi <= 60.0).all()
                
                # 최종 조건: 최근 16개봉 중 60 <= RSI <= 75 만족 봉 >= 13개 AND 직전 3개봉 RSI <= 60
                if rsi_60_75_count >= 13 and prev_3_low_rsi_valid:
                    res_daily = requests.get(url_daily, headers=headers, timeout=5)
                    if res_daily.status_code == 200:
                        data_daily = res_daily.json()
                        if isinstance(data_daily, list) and len(data_daily) >= 30:
                            df_daily = process_candle_df(data_daily)
                            
                            last_1h = df_1h.iloc[-1]
                            last_daily = df_daily.iloc[-1]
                            c_now = last_1h['Close']
                            t_now = last_1h['ConversionLine']
                            
                            # 체결가 vs 전환선 위치 상태 (Close >= ConversionLine: 전환선 상위, Close < ConversionLine: 전환선 아래 이탈)
                            is_above_tenkan = not pd.isna(c_now) and not pd.isna(t_now) and (c_now >= t_now)
                            tenkan_diff_pct = ((c_now - t_now) / t_now * 100.0) if (not pd.isna(t_now) and t_now > 0) else 0.0
                            
                            return {
                                'market': market_code,
                                'korean_name': korean_name,
                                'english_name': english_name,
                                'close_price': c_now,
                                'rsi_60_75_count': rsi_60_75_count,
                                'rsi_60_75_ratio': round(rsi_60_75_ratio, 1),
                                'prev_3_max_rsi': round(prev_3_rsi.max(), 1),
                                'is_above_tenkan': is_above_tenkan,
                                'tenkan_diff_pct': round(tenkan_diff_pct, 2),
                                'rsi_1h': round(last_1h['RSI'], 1) if not pd.isna(last_1h['RSI']) else 0.0,
                                'macd_1h': round(last_1h['MACD'], 2) if not pd.isna(last_1h['MACD']) else 0.0,
                                'tenkan_1h': round(last_1h['ConversionLine'], 2) if not pd.isna(last_1h['ConversionLine']) else 0.0,
                                'kijun_1h': round(last_1h['BaseLine'], 2) if not pd.isna(last_1h['BaseLine']) else 0.0,
                                'rsi_daily': round(last_daily['RSI'], 1) if not pd.isna(last_daily['RSI']) else 0.0,
                                'macd_daily': round(last_daily['MACD'], 2) if not pd.isna(last_daily['MACD']) else 0.0,
                                'tenkan_daily': round(last_daily['ConversionLine'], 2) if not pd.isna(last_daily['ConversionLine']) else 0.0,
                                'kijun_daily': round(last_daily['BaseLine'], 2) if not pd.isna(last_daily['BaseLine']) else 0.0,
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
    1단: 가격 + 일목균형표 + 거래량 (TwinX)
    2단: MACD
    3단: RSI (14) (60~75 목표 구간 하이라이트)
    """
    ax_p, ax_m, ax_r = axes_col
    x = range(len(df))
    
    # ---------------------------------------------------------
    # 1단: 가격 + 일목균형표(9, 26, 52) + 진한 거래량 (TwinX)
    # ---------------------------------------------------------
    ax_v = ax_p.twinx()
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
    ax_p.plot(x, df['BaseLine'], label='기준선(26)', color='#1f78b4', linewidth=1.3)
    ax_p.plot(x, df['Span1'], label='선행1(26)', color='#33a02c', linewidth=0.8, linestyle='--')
    ax_p.plot(x, df['Span2'], label='선행2(52)', color='#ff7f00', linewidth=0.8, linestyle='--')
    
    ax_p.fill_between(x, df['Span1'], df['Span2'], where=(df['Span1'] >= df['Span2']), color='#b2df8a', alpha=0.35, label='양운')
    ax_p.fill_between(x, df['Span1'], df['Span2'], where=(df['Span1'] < df['Span2']), color='#fb9a99', alpha=0.35, label='음운')
    
    ax_p.set_title(f"{title_prefix} - [{time_frame_label} 일목균형표(9,26) & 거래량]", fontsize=9.5, fontweight='bold', color='#1b4f72', pad=3)
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
    # 3단: RSI (14) (60~75 영역 음영 하이라이트)
    # ---------------------------------------------------------
    ax_r.plot(x, df['RSI'], label='RSI(14)', color='#8e44ad', linewidth=1.2)
    ax_r.axhspan(60, 75, color='#f39c12', alpha=0.25, label='60~75 목표구간')
    ax_r.axhline(75, color='#e31a1c', linestyle='--', linewidth=0.8, label='상한선(75)')
    ax_r.axhline(60, color='#d35400', linestyle=':', linewidth=0.8, label='하한선(60)')
    ax_r.axhline(30, color='#1f78b4', linestyle='--', linewidth=0.8, label='과매도(30)')
    ax_r.set_ylim(0, 100)
    ax_r.set_ylabel("RSI", fontsize=8)
    ax_r.tick_params(axis='x', labelsize=7.5)
    ax_r.tick_params(axis='y', labelsize=7.5)
    ax_r.legend(loc='upper left', fontsize=6.5, framealpha=0.85, ncol=4)
    ax_r.grid(True, linestyle=':', alpha=0.5)

def generate_onehour_rsi60_75_16bars_ratio80_pdf_report(pdf_path=None, max_workers=8):
    """
    1시간봉 최근 16개봉 RSI(14) 60~75 충족 봉 수 13개 이상(>=81.25%) AND 직전 3개봉(N-18~N-16) RSI <= 60 포착 코인 대상 PDF 리포트 생성
    - 구글 드라이브 자동 업로드 연동 (credentials.json / hhokyung@gmail.com 계정 / report_hour 폴더)
    - PDF 저장 위치: onehour_report/report/onehour_rsi60_75_16bars_ratio80_report_YYYYMMDDHHMMSS.pdf
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    if pdf_path is None:
        save_dir = os.path.join(base_dir, "report")
        os.makedirs(save_dir, exist_ok=True)
        filename = f"onehour_rsi60_75_16bars_ratio80_report_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_path = os.path.join(save_dir, filename)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(pdf_path)), exist_ok=True)

    markets = get_krw_markets()
    if not markets:
        print("조회된 KRW 마켓이 없습니다.")
        return None

    print(f"[1/3] 빗썸 {len(markets)}개 원화 코인 스캔 중 (조건: 16봉 60<=RSI<=75 >= 13봉 AND 직전 3개봉 RSI<=60, 스레드: {max_workers})...")
    
    captured_list = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_and_analyze_single_coin, m): m for m in markets}
        for future in as_completed(futures):
            res = future.result()
            if res:
                captured_list.append(res)
                state_str = "전환선 상위" if res['is_above_tenkan'] else "전환선 아래"
                print(f" ★ 포착 코인: {res['korean_name']}({res['market']}) | 현재가: {res['close_price']:,}원 | 16h RSI(60~75): {res['rsi_60_75_ratio']}%({res['rsi_60_75_count']}/16봉) | 이전3봉MaxRSI: {res['prev_3_max_rsi']} | 상태: {state_str}({res['tenkan_diff_pct']}%) | 60m RSI: {res['rsi_1h']}")

    # 정렬: RSI 60~75 충족 봉 수(rsi_60_75_count) 내림차순, 현재 1시간봉 RSI 내림차순 정렬
    captured_list.sort(key=lambda x: (x['rsi_60_75_count'], x['rsi_1h']), reverse=True)
    
    print(f"\n[2/3] 총 {len(captured_list)}개 포착 코인 PDF 생성 중... (저장경로: {pdf_path})")
    
    if not captured_list:
        print("조정된 조건(최근 16개 1시간봉 중 60 <= RSI <= 75 충족 봉 >= 13개 AND 직전 3개봉 RSI <= 60)을 만족하는 코인이 없습니다.")
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
                f"{c['rsi_60_75_ratio']}% ({c['rsi_60_75_count']}/16봉)",
                f"{c['prev_3_max_rsi']:.1f}",
                "상위" if c['is_above_tenkan'] else "이탈(하회)",
                f"{c['tenkan_diff_pct']:+.2f}%",
                f"{c['rsi_1h']:.1f}",
                f"{c['tenkan_1h']:,}",
                f"{c['rsi_daily']:.1f}",
                f"{c['tenkan_daily']:,}"
            ] for c in captured_list
        ]
        
        col_labels = ['마켓코드', '한글명', '영문명', '현재가(원)', '16h RSI(60~75)', '직전3봉MaxRSI', '전환선위치', '전환선이격률', '60m RSI', '60m전환선', '일봉 RSI', '일봉전환선']

        for page_idx in range(0, len(summary_rows_all), chunk_size):
            chunk = summary_rows_all[page_idx : page_idx + chunk_size]
            fig_table, ax_table = plt.subplots(figsize=(14, 8.5))
            ax_table.axis('off')

            title_text = "빗썸 1시간봉 최근 16봉 RSI (60~75) 13봉+ & 직전3봉 RSI<=60 포착 리포트"
            subtitle_text = f"분석 일시: {now_str} | 조건: 최근 16봉 중 60<=RSI<=75 >= 13봉 (80%+) AND 직전 3개봉(N-18~N-16) RSI <= 60 | 총 {len(captured_list)}개 코인 포착 (p.{page_idx//chunk_size + 1})"
            
            ax_table.text(0.5, 0.96, title_text, fontsize=14, fontweight='bold', ha='center', va='top', color='#1a5276')
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
        # 2. 개별 코인 차트 페이지 (한 페이지에 60분봉 3단 + 일봉 3단 나란히 배치) (상위 25개 코인)
        # -------------------------------------------------------------
        for idx, item in enumerate(captured_list[:25], 1):
            fig, axes = plt.subplots(
                3, 2, figsize=(16, 9.5),
                gridspec_kw={'height_ratios': [3.0, 1.2, 1.2], 'wspace': 0.18, 'hspace': 0.25}
            )
            
            k_name = item['korean_name']
            e_name = item['english_name']
            m_code = item['market']
            price = item['close_price']
            state_text = "전환선 상위" if item['is_above_tenkan'] else "전환선 하회이탈"
            
            title_page = f"[{idx}/{len(captured_list[:25])}] {k_name} ({e_name} / {m_code})  |  현재가: {price:,}원  |  [포착] 16h RSI(60~75): {item['rsi_60_75_ratio']}% ({item['rsi_60_75_count']}/16봉) | 직전3봉MaxRSI: {item['prev_3_max_rsi']} | 상태: {state_text} ({item['tenkan_diff_pct']:+.2f}%)"
            fig.suptitle(title_page, fontsize=11.5, fontweight='bold', color='#0e6251', y=0.98)
            
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
    print(f"\n[3/3] 성공! 1시간봉 최근 16개봉 RSI(60~75) 13봉+ AND 직전3봉 RSI<=60 포착 코인 PDF 리포트 생성 완료!", flush=True)
    print(f" -> PDF 저장 위치: '{full_pdf_path}'", flush=True)

    # 구글 드라이브 자동 업로드 (credentials.json / hhokyung@gmail.com 계정 / report_hour 폴더)
    try:
        root_dir = os.path.dirname(base_dir)
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)
        from upload_to_gdrive import upload_pdf_to_gdrive
        gdrive_url = upload_pdf_to_gdrive(full_pdf_path, folder_name="report_hour", user_email="hhokyung@gmail.com")
        if gdrive_url:
            print(f" -> 구글 드라이브 업로드 완료 링크: {gdrive_url}", flush=True)
    except Exception as e:
        print(f"구글 드라이브 업로드 수행 중 오류 발생: {e}", flush=True)

    return full_pdf_path

if __name__ == "__main__":
    generate_onehour_rsi60_75_16bars_ratio80_pdf_report()

