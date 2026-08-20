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

def process_candle_df(data):
    """캔들 JSON 데이터를 DataFrame으로 변환 및 일목/MACD 지표 계산"""
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

def fetch_and_analyze_single_coin_240m(m, count=200, kijun_window=10):
    """
    단일 코인의 240분봉 및 일봉 시계열 수집
    - 240분봉 조건: 전환선 > 기준선 AND 기준선 각도 >= 0도
    - 일봉 필터 조건: 일봉 전환선 > 일봉 기준선 AND 일봉 현재가 > 일봉 전환선
    """
    market_code = m['market']
    korean_name = m['korean_name']
    english_name = m['english_name']
    
    headers = {"accept": "application/json"}
    url_240m = f"https://api.bithumb.com/v1/candles/minutes/240?market={market_code}&count={count}"
    url_daily = f"https://api.bithumb.com/v1/candles/days?market={market_code}&count={count}"
    
    try:
        res_240m = requests.get(url_240m, headers=headers, timeout=5)
        if res_240m.status_code == 200:
            data_240m = res_240m.json()
            if isinstance(data_240m, list) and len(data_240m) >= 60:
                df_240m = process_candle_df(data_240m)
                last_240m = df_240m.iloc[-1]
                
                tenkan = last_240m['ConversionLine']
                kijun = last_240m['BaseLine']
                price = last_240m['Close']
                
                if pd.isna(tenkan) or pd.isna(kijun):
                    return None
                    
                cond1_tenkan_above_kijun = (tenkan > kijun)
                
                # 기준선 및 전환선 각도 계산 (최근 kijun_window 봉)
                past_kijun_240m = df_240m['BaseLine'].iloc[-kijun_window:]
                _, kijun_angle_240m = get_slope_and_angle(past_kijun_240m.dropna())
                
                past_tenkan_240m = df_240m['ConversionLine'].iloc[-kijun_window:]
                _, tenkan_angle_240m = get_slope_and_angle(past_tenkan_240m.dropna())
                
                cond2_kijun_angle_ge_zero = (kijun_angle_240m >= 0.0)
                
                # 240분봉 1차 조건 만족 시 일봉 데이터 검사
                if cond1_tenkan_above_kijun and cond2_kijun_angle_ge_zero:
                    res_daily = requests.get(url_daily, headers=headers, timeout=5)
                    if res_daily.status_code == 200:
                        data_daily = res_daily.json()
                        if isinstance(data_daily, list) and len(data_daily) >= 30:
                            df_daily = process_candle_df(data_daily)
                            last_daily = df_daily.iloc[-1]
                            
                            daily_tenkan = last_daily['ConversionLine']
                            daily_kijun = last_daily['BaseLine']
                            daily_price = last_daily['Close']
                            
                            if pd.isna(daily_tenkan) or pd.isna(daily_kijun):
                                return None
                                
                            # 일봉 추가 필터 조건:
                            # 1) 일봉 전환선 > 일봉 기준선
                            # 2) 일봉 현재가 > 일봉 전환선
                            cond3_daily_tenkan_above_kijun = (daily_tenkan > daily_kijun)
                            cond4_daily_price_above_tenkan = (daily_price > daily_tenkan)
                            
                            if cond3_daily_tenkan_above_kijun and cond4_daily_price_above_tenkan:
                                # 구름대 위치 파악
                                span1, span2 = last_240m['Span1'], last_240m['Span2']
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
                                    'conversion_line_240m': round(tenkan, 2),
                                    'base_line_240m': round(kijun, 2),
                                    'kijun_angle_240m': round(kijun_angle_240m, 2),
                                    'tenkan_angle_240m': round(tenkan_angle_240m, 2),
                                    'rsi_240m': round(last_240m['RSI'], 1) if not pd.isna(last_240m['RSI']) else 0.0,
                                    'macd_240m': round(last_240m['MACD'], 2) if not pd.isna(last_240m['MACD']) else 0.0,
                                    'macd_signal_240m': round(last_240m['MACD_Signal'], 2) if not pd.isna(last_240m['MACD_Signal']) else 0.0,
                                    'daily_tenkan': round(daily_tenkan, 2),
                                    'daily_kijun': round(daily_kijun, 2),
                                    'daily_price': round(daily_price, 2),
                                    'cloud_pos_240m': cloud_pos,
                                    'df_240m': df_240m,
                                    'df_daily': df_daily
                                }
    except Exception:
        pass
    return None

def generate_4hour_pdf_report(pdf_path=None, max_coins=None, max_workers=6, upload_gdrive=True):
    """
    240분봉 정배열&기준선 우상향 + 일봉 정배열 코인 대상 PDF 리포트 생성 (일목 + MACD 서브플롯 포함)
    """
    if pdf_path is None:
        save_dir = "d:/pyprj/coinsts/report_4hour"
        os.makedirs(save_dir, exist_ok=True)
        filename = f"report_4hour_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_path = os.path.join(save_dir, filename)
    else:
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

    markets = get_krw_markets()
    if max_coins:
        markets = markets[:max_coins]

    print(f"[1/3] 총 {len(markets)}개 원화 코인 [240분봉 & 일봉 듀얼 + MACD 지표] 분석 중 (스레드수: {max_workers})...")
    
    captured_list = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_and_analyze_single_coin_240m, m): m for m in markets}
        for future in as_completed(futures):
            res = future.result()
            if res:
                captured_list.append(res)
                print(f" ★ 멀티타임프레임 포착: {res['korean_name']}({res['english_name']} / {res['market']}) | 240m기준선각도: {res['kijun_angle_240m']:+.2f}° | MACD: {res['macd_240m']}")
                
    captured_list.sort(key=lambda x: (x['kijun_angle_240m'], x['tenkan_angle_240m']), reverse=True)
    
    print(f"\n[2/3] 총 {len(captured_list)}개 최종 포착 코인 [일목균형표 + MACD 포함] PDF 생성 중...")
    
    if not captured_list:
        print("조건을 모두 만족하는 코인이 없어 PDF 생성을 완료할 수 없습니다.")
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
                f"{c['conversion_line_240m']:,}",
                f"{c['base_line_240m']:,}",
                f"{c['kijun_angle_240m']:+.2f}°",
                f"{c['daily_tenkan']:,}",
                f"{c['daily_kijun']:,}",
                f"{c['macd_240m']:,}",
                f"{c['rsi_240m']:.1f}",
                c['cloud_pos_240m']
            ] for c in captured_list
        ]
        
        col_labels = ['마켓코드', '한글명', '영문명', '현재가(원)', '240m전환선', '240m기준선', '240m각도', '일봉전환선', '일봉기준선', '240m MACD', '240m RSI', '구름위치']

        for page_idx in range(0, len(summary_rows_all), chunk_size):
            chunk = summary_rows_all[page_idx : page_idx + chunk_size]
            fig_table, ax_table = plt.subplots(figsize=(11.69, 8.27))
            ax_table.axis('off')

            title_text = "빗썸 일목균형표 & MACD 240분봉/일봉 멀티 타임프레임 리포트"
            subtitle_text = f"분석 일시: {now_str} | 조건: (240m 전환>기준 & 기준선각도>=0°) AND (일봉 전환>기준 & 현재가>전환선) | 총 {len(captured_list)}개 (p.{page_idx//chunk_size + 1})"
            
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
            table.set_fontsize(7.5)
            
            for col_i in range(len(col_labels)):
                cell = table[(0, col_i)]
                cell.set_facecolor('#1a5276')
                cell.set_text_props(color='white', fontweight='bold')
                
            plt.tight_layout()
            pdf.savefig(fig_table)
            plt.close(fig_table)

        # -------------------------------------------------------------
        # 개별 코인 차트 페이지 (4개 Subplot: 240m 일목, 240m MACD, 일봉 일목, 일봉 MACD)
        # -------------------------------------------------------------
        for idx, coin_data in enumerate(captured_list, 1):
            fig, (ax_240m_price, ax_240m_macd, ax_daily_price, ax_daily_macd) = plt.subplots(
                4, 1, figsize=(11.69, 8.27),
                gridspec_kw={'height_ratios': [2.8, 1.2, 2.8, 1.2]},
                sharex=False
            )
            
            k_name = coin_data['korean_name']
            e_name = coin_data['english_name']
            m_code = coin_data['market']
            price = coin_data['close_price']
            
            # ---------------------------------------------------------
            # 1. 상단 가격 차트: 240분봉(4시간) 일목균형표
            # ---------------------------------------------------------
            df_240m = coin_data['df_240m']
            x_240m = range(len(df_240m))
            
            ax_240m_price.plot(x_240m, df_240m['Close'], label='종가', color='black', linewidth=1.3)
            ax_240m_price.plot(x_240m, df_240m['ConversionLine'], label='전환선(9)', color='#e31a1c', linewidth=1.1)
            ax_240m_price.plot(x_240m, df_240m['BaseLine'], label='기준선(26)', color='#1f78b4', linewidth=1.1)
            ax_240m_price.plot(x_240m, df_240m['Span1'], label='선행스팬1', color='#33a02c', linewidth=0.8, linestyle='--')
            ax_240m_price.plot(x_240m, df_240m['Span2'], label='선행스팬2', color='#ff7f00', linewidth=0.8, linestyle='--')
            
            ax_240m_price.fill_between(
                x_240m, df_240m['Span1'], df_240m['Span2'],
                where=(df_240m['Span1'] >= df_240m['Span2']),
                color='#b2df8a', alpha=0.35, label='양운'
            )
            ax_240m_price.fill_between(
                x_240m, df_240m['Span1'], df_240m['Span2'],
                where=(df_240m['Span1'] < df_240m['Span2']),
                color='#fb9a99', alpha=0.35, label='음운'
            )

            k_ang_240m = coin_data['kijun_angle_240m']
            t_ang_240m = coin_data['tenkan_angle_240m']
            rsi_240m = coin_data['rsi_240m']
            
            title_240m = f"[{idx}/{len(captured_list)}] {k_name} ({e_name} / {m_code})  -  [상단: 240분봉(4시간) 일목 차트]  |  현재가: {price:,}원  |  기준선 각도: {k_ang_240m:+.2f}°  |  RSI: {rsi_240m}"
            ax_240m_price.set_title(title_240m, fontsize=10, fontweight='bold', color='#1b4f72', pad=4)
            ax_240m_price.set_ylabel("가격 (KRW)", fontsize=8)
            ax_240m_price.legend(loc='upper left', fontsize=7, framealpha=0.85, ncol=3)
            ax_240m_price.grid(True, linestyle=':', alpha=0.5)

            # ---------------------------------------------------------
            # 2. 240분봉 MACD 차트
            # ---------------------------------------------------------
            ax_240m_macd.plot(x_240m, df_240m['MACD'], label='MACD(12,26)', color='#1f78b4', linewidth=1.0)
            ax_240m_macd.plot(x_240m, df_240m['MACD_Signal'], label='Signal(9)', color='#e31a1c', linewidth=1.0, linestyle='--')
            
            # Histogram 바 차트
            colors_240m_hist = ['#e31a1c' if val >= 0 else '#1f78b4' for val in df_240m['MACD_Hist']]
            ax_240m_macd.bar(x_240m, df_240m['MACD_Hist'], color=colors_240m_hist, alpha=0.4, width=0.8, label='Oscillator')
            ax_240m_macd.axhline(0, color='gray', linestyle=':', linewidth=0.7)
            
            ax_240m_macd.set_ylabel("240m MACD", fontsize=7.5)
            ax_240m_macd.legend(loc='upper left', fontsize=6.5, framealpha=0.85, ncol=3)
            ax_240m_macd.grid(True, linestyle=':', alpha=0.5)

            # ---------------------------------------------------------
            # 3. 하단 가격 차트: 일봉(Daily) 일목균형표
            # ---------------------------------------------------------
            df_daily = coin_data['df_daily']
            if df_daily is not None and not df_daily.empty:
                x_daily = range(len(df_daily))
                last_daily = df_daily.iloc[-1]
                
                ax_daily_price.plot(x_daily, df_daily['Close'], label='종가', color='black', linewidth=1.3)
                ax_daily_price.plot(x_daily, df_daily['ConversionLine'], label='전환선(9)', color='#e31a1c', linewidth=1.1)
                ax_daily_price.plot(x_daily, df_daily['BaseLine'], label='기준선(26)', color='#1f78b4', linewidth=1.1)
                ax_daily_price.plot(x_daily, df_daily['Span1'], label='선행스팬1', color='#33a02c', linewidth=0.8, linestyle='--')
                ax_daily_price.plot(x_daily, df_daily['Span2'], label='선행스팬2', color='#ff7f00', linewidth=0.8, linestyle='--')
                
                ax_daily_price.fill_between(
                    x_daily, df_daily['Span1'], df_daily['Span2'],
                    where=(df_daily['Span1'] >= df_daily['Span2']),
                    color='#b2df8a', alpha=0.35, label='양운'
                )
                ax_daily_price.fill_between(
                    x_daily, df_daily['Span1'], df_daily['Span2'],
                    where=(df_daily['Span1'] < df_daily['Span2']),
                    color='#fb9a99', alpha=0.35, label='음운'
                )

                daily_rsi = round(last_daily['RSI'], 1) if not pd.isna(last_daily['RSI']) else 0.0
                
                title_daily = f"[하단: 일봉(Daily) 일목 차트]  |  일봉 종가: {last_daily['Close']:,}원  |  일봉 전환선: {coin_data['daily_tenkan']:,}원  |  일봉 기준선: {coin_data['daily_kijun']:,}원  |  일봉 RSI: {daily_rsi}"
                ax_daily_price.set_title(title_daily, fontsize=10, fontweight='bold', color='#145a32', pad=4)
                ax_daily_price.set_ylabel("가격 (KRW)", fontsize=8)
                ax_daily_price.legend(loc='upper left', fontsize=7, framealpha=0.85, ncol=3)
                ax_daily_price.grid(True, linestyle=':', alpha=0.5)

                # ---------------------------------------------------------
                # 4. 일봉 MACD 차트
                # ---------------------------------------------------------
                ax_daily_macd.plot(x_daily, df_daily['MACD'], label='MACD(12,26)', color='#1f78b4', linewidth=1.0)
                ax_daily_macd.plot(x_daily, df_daily['MACD_Signal'], label='Signal(9)', color='#e31a1c', linewidth=1.0, linestyle='--')
                
                colors_daily_hist = ['#e31a1c' if val >= 0 else '#1f78b4' for val in df_daily['MACD_Hist']]
                ax_daily_macd.bar(x_daily, df_daily['MACD_Hist'], color=colors_daily_hist, alpha=0.4, width=0.8, label='Oscillator')
                ax_daily_macd.axhline(0, color='gray', linestyle=':', linewidth=0.7)
                
                ax_daily_macd.set_ylabel("일봉 MACD", fontsize=7.5)
                ax_daily_macd.set_xlabel("일자 (최신 일봉 시계열)", fontsize=7.5)
                ax_daily_macd.legend(loc='upper left', fontsize=6.5, framealpha=0.85, ncol=3)
                ax_daily_macd.grid(True, linestyle=':', alpha=0.5)
            else:
                ax_daily_price.text(0.5, 0.5, "일봉 데이터를 불러올 수 없습니다.", ha='center', va='center', fontsize=11)

            plt.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

    full_pdf_path = os.path.abspath(pdf_path)
    print(f"\n[3/3] MACD 포함 240분봉 & 일봉 PDF 리포트 생성 완료!\n -> 저장 위치: '{full_pdf_path}'")

    if upload_gdrive:
        try:
            from upload_to_gdrive import upload_pdf_to_gdrive
            upload_pdf_to_gdrive(full_pdf_path, folder_name="report_4hour", user_email="hhokyung@gmail.com")
        except Exception as e:
            print(f"구글 드라이브 업로드 안내: {e}")

    return full_pdf_path

if __name__ == "__main__":
    generate_4hour_pdf_report(max_workers=6)
