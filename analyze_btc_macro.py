import requests
import pandas as pd
import numpy as np
import os
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from datetime import datetime

# Matplotlib 한글 폰트 설정 (Windows 맑은 고딕)
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

def calc_mid_point(high, low, window):
    """지정된 기간 동안의 (최고가 + 최저가) / 2 계산"""
    return (high.rolling(window=window).max() + low.rolling(window=window).min()) / 2

def get_bithumb_btc_candles(timeframe='days', count=200):
    """빗썸 비트코인(KRW-BTC) 캔들 데이터 수집"""
    if timeframe == 'days':
        url = f"https://api.bithumb.com/v1/candles/days?market=KRW-BTC&count={count}"
    else:
        url = f"https://api.bithumb.com/v1/candles/minutes/60?market=KRW-BTC&count={count}"
        
    headers = {"accept": "application/json"}
    res = requests.get(url, headers=headers)
    if res.status_code != 200:
        return None
        
    data = res.json()
    df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
    
    for col in ['high_price', 'low_price', 'trade_price']:
        df[col] = df[col].astype(float)
    if 'candle_acc_trade_volume' in df.columns:
        df['volume'] = df['candle_acc_trade_volume'].astype(float)
    else:
        df['volume'] = 0.0
        
    df['Close'] = df['trade_price']
    df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 9)
    df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 26)
    df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(26)
    df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 52).shift(26)
    df['CloudTop'] = np.maximum(df['Span1'], df['Span2'])
    df['Vol_20_MA'] = df['volume'].rolling(20).mean()
    
    return df

def generate_btc_pdf_report(pdf_path=None, upload_gdrive=True):
    """
    비트코인(KRW-BTC) 대세 조건 검증 및 차트를 포함한 PDF 리포트 생성 함수
    저장 경로: d:/pyprj/coinsts/report_bitcoin/report_bitcoin_YYYYMMDDHH.pdf
    """
    if pdf_path is None:
        save_dir = "d:/pyprj/coinsts/report_bitcoin"
        os.makedirs(save_dir, exist_ok=True)
        filename = f"report_bitcoin_{datetime.now().strftime('%Y%m%d%H')}.pdf"
        pdf_path = os.path.join(save_dir, filename)

    print(f"[1/3] 비트코인(KRW-BTC) 1시간봉 및 일봉 시계열 데이터 수집 중...")
    df_daily = get_bithumb_btc_candles(timeframe='days', count=200)
    df_1h = get_bithumb_btc_candles(timeframe='minutes', count=200)
    
    if df_daily is None or df_1h is None:
        print("비트코인 데이터를 불러오지 못했습니다.")
        return None
        
    last_d = df_daily.iloc[-1]
    last_1h = df_1h.iloc[-1]
    
    # 일봉 기준 조건 검증
    d_above_conv = last_d['Close'] >= last_d['ConversionLine']
    d_above_base = last_d['Close'] >= last_d['BaseLine']
    d_above_cloud = last_d['Close'] >= last_d['CloudTop'] if not np.isnan(last_d['CloudTop']) else True
    d_conv_ge_base = last_d['ConversionLine'] >= last_d['BaseLine']
    vol_ratio_d = (last_d['volume'] / last_d['Vol_20_MA']) if last_d['Vol_20_MA'] > 0 else 1.0
    vol_increase_d = vol_ratio_d >= 1.2
    
    btc_macro_bull = d_above_conv and d_above_base and d_above_cloud and d_conv_ge_base
    verdict_text = "★ 대세 상승장 / 강세 조건 만족 (알트코인 분석 유효)" if btc_macro_bull else "[!] 비트코인 약세/조정국면 (알트코인 접근 주의/관망 구간)"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("\n" + "="*85)
    print(" [비트코인(KRW-BTC) 대세 조건 진단] ")
    print("="*85)
    print(f"▶ 현재 비트코인 종가: {last_d['Close']:,.0f} 원")
    print(f"▶ 최종 비트코인 대세 판단: {verdict_text}")
    print("="*85 + "\n")

    print(f"[2/3] 비트코인 PDF 리포트 차트 시각화 중... ({pdf_path})")

    with PdfPages(pdf_path) as pdf:
        # -------------------------------------------------------------
        # Page 1: 요약표 및 체크리스트
        # -------------------------------------------------------------
        fig_table, ax_table = plt.subplots(figsize=(11.69, 8.27))
        ax_table.axis('off')

        ax_table.text(0.5, 0.95, "비트코인(KRW-BTC) 대세 상승장 분석 리포트", fontsize=18, fontweight='bold', ha='center', va='top')
        ax_table.text(0.5, 0.90, f"분석 일시: {now_str}  |  현재 종가: {last_d['Close']:,.0f} 원", fontsize=11, color='gray', ha='center', va='top')

        status_box_color = '#d4edda' if btc_macro_bull else '#f8d7da'
        status_text_color = '#155724' if btc_macro_bull else '#721c24'
        ax_table.text(0.5, 0.81, f"최종 대세 판정: {verdict_text}", fontsize=14, fontweight='bold', color=status_text_color, ha='center', va='top', bbox=dict(boxstyle='round,pad=0.5', facecolor=status_box_color, edgecolor='none'))

        checklist_rows = [
            ["1. 종가 >= 일봉 전환선(9일)", "만족 (O)" if d_above_conv else "미부합 (X)", f"{last_d['Close']:,.0f} 원", f"{last_d['ConversionLine']:,.0f} 원"],
            ["2. 종가 >= 일봉 기준선(26일)", "만족 (O)" if d_above_base else "미부합 (X)", f"{last_d['Close']:,.0f} 원", f"{last_d['BaseLine']:,.0f} 원"],
            ["3. 종가 >= 일봉 구름대 상단", "만족 (O)" if d_above_cloud else "미부합 (X)", f"{last_d['Close']:,.0f} 원", f"{last_d['CloudTop']:,.0f} 원"],
            ["4. 일봉 전환선 >= 기준선", "만족 (O)" if d_conv_ge_base else "미부합 (X)", f"{last_d['ConversionLine']:,.0f} 원", f"{last_d['BaseLine']:,.0f} 원"],
            ["5. 거래량 수급 상태 (20일 평균 대비)", "수급 유입" if vol_increase_d else "수급 평이", f"{vol_ratio_d*100:.1f}%", f"{last_d['Vol_20_MA']:,.1f}"]
        ]
        
        table = ax_table.table(
            cellText=checklist_rows,
            colLabels=['점검 항목', '판정 결과', '현재 수치', '기준 수치'],
            cellLoc='center',
            loc='center',
            bbox=[0.05, 0.20, 0.90, 0.50]
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9.5)
        for c_idx in range(4):
            cell = table[(0, c_idx)]
            cell.set_facecolor('#1f4e78')
            cell.set_text_props(color='white', fontweight='bold')

        plt.tight_layout()
        pdf.savefig(fig_table)
        plt.close(fig_table)

        # -------------------------------------------------------------
        # Page 2: 1시간봉 & 일봉 일목 차트 + 거래량
        # -------------------------------------------------------------
        fig = plt.figure(figsize=(11.69, 8.27))
        gs = fig.add_gridspec(4, 1, height_ratios=[3, 1, 3, 1], hspace=0.35)
        
        ax_1h_price = fig.add_subplot(gs[0])
        ax_1h_vol = fig.add_subplot(gs[1], sharex=ax_1h_price)
        ax_daily_price = fig.add_subplot(gs[2])
        ax_daily_vol = fig.add_subplot(gs[3], sharex=ax_daily_price)
        
        # 1. 1시간봉 차트
        x_1h = range(len(df_1h))
        ax_1h_price.plot(x_1h, df_1h['Close'], label='BTC 종가', color='black', linewidth=1.3)
        ax_1h_price.plot(x_1h, df_1h['ConversionLine'], label='전환선(9)', color='#e31a1c', linewidth=1.1)
        ax_1h_price.plot(x_1h, df_1h['BaseLine'], label='기준선(26)', color='#1f78b4', linewidth=1.1)
        ax_1h_price.plot(x_1h, df_1h['Span1'], label='선행스팬1', color='#33a02c', linewidth=0.8, linestyle='--')
        ax_1h_price.plot(x_1h, df_1h['Span2'], label='선행스팬2', color='#ff7f00', linewidth=0.8, linestyle='--')
        ax_1h_price.fill_between(x_1h, df_1h['Span1'], df_1h['Span2'], where=(df_1h['Span1'] >= df_1h['Span2']), color='#b2df8a', alpha=0.35, label='양운')
        ax_1h_price.fill_between(x_1h, df_1h['Span1'], df_1h['Span2'], where=(df_1h['Span1'] < df_1h['Span2']), color='#fb9a99', alpha=0.35, label='음운')
        ax_1h_price.set_title(f"비트코인(KRW-BTC) 1시간봉 일목균형표 차트 (현재가: {last_1h['Close']:,.0f}원)", fontsize=10.5, fontweight='bold', color='#1b4f72')
        ax_1h_price.set_ylabel("가격 (KRW)", fontsize=8)
        ax_1h_price.legend(loc='upper left', fontsize=7, ncol=3, framealpha=0.85)
        ax_1h_price.grid(True, linestyle=':', alpha=0.5)
        
        colors_1h = ['#e31a1c' if df_1h['Close'].iloc[i] >= df_1h['Close'].iloc[max(0, i-1)] else '#1f78b4' for i in range(len(df_1h))]
        ax_1h_vol.bar(x_1h, df_1h['volume'], color=colors_1h, alpha=0.75, width=0.8)
        ax_1h_vol.plot(x_1h, df_1h['Vol_20_MA'], color='darkorange', linewidth=1.0, label='20봉 평균 거래량')
        ax_1h_vol.set_ylabel("거래량", fontsize=7.5)
        ax_1h_vol.grid(True, linestyle=':', alpha=0.4)
        
        # 2. 일봉 차트
        x_daily = range(len(df_daily))
        ax_daily_price.plot(x_daily, df_daily['Close'], label='BTC 일봉 종가', color='black', linewidth=1.4)
        ax_daily_price.plot(x_daily, df_daily['ConversionLine'], label='일봉 전환선(9)', color='#e31a1c', linewidth=1.2)
        ax_daily_price.plot(x_daily, df_daily['BaseLine'], label='일봉 기준선(26)', color='#1f78b4', linewidth=1.2)
        ax_daily_price.plot(x_daily, df_daily['Span1'], label='선행스팬1', color='#33a02c', linewidth=0.9, linestyle='--')
        ax_daily_price.plot(x_daily, df_daily['Span2'], label='선행스팬2', color='#ff7f00', linewidth=0.9, linestyle='--')
        ax_daily_price.fill_between(x_daily, df_daily['Span1'], df_daily['Span2'], where=(df_daily['Span1'] >= df_daily['Span2']), color='#b2df8a', alpha=0.35, label='양운')
        ax_daily_price.fill_between(x_daily, df_daily['Span1'], df_daily['Span2'], where=(df_daily['Span1'] < df_daily['Span2']), color='#fb9a99', alpha=0.35, label='음운')
        ax_daily_price.set_title(f"비트코인(KRW-BTC) 일봉(Daily) 일목균형표 차트 - [{verdict_text}]", fontsize=10.5, fontweight='bold', color='#145a32')
        ax_daily_price.set_ylabel("가격 (KRW)", fontsize=8)
        ax_daily_price.legend(loc='upper left', fontsize=7, ncol=3, framealpha=0.85)
        ax_daily_price.grid(True, linestyle=':', alpha=0.5)
        
        colors_daily = ['#e31a1c' if df_daily['Close'].iloc[i] >= df_daily['Close'].iloc[max(0, i-1)] else '#1f78b4' for i in range(len(df_daily))]
        ax_daily_vol.bar(x_daily, df_daily['volume'], color=colors_daily, alpha=0.75, width=0.8)
        ax_daily_vol.plot(x_daily, df_daily['Vol_20_MA'], color='darkorange', linewidth=1.0, label='20일 평균 거래량')
        ax_daily_vol.set_ylabel("거래량", fontsize=7.5)
        ax_daily_vol.set_xlabel("시계열 봉 순서 (최신 200개)", fontsize=8)
        ax_daily_vol.grid(True, linestyle=':', alpha=0.4)
        
        plt.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)

    full_pdf_path = os.path.abspath(pdf_path)
    print(f"\n[3/3] 비트코인 PDF 리포트 생성 완료!\n -> 저장 위치: '{full_pdf_path}'")

    if upload_gdrive:
        try:
            from upload_to_gdrive import upload_pdf_to_gdrive
            upload_pdf_to_gdrive(full_pdf_path, folder_name="report_bitcoin", user_email="hhokyung@gmail.com")
        except Exception as e:
            print(f"구글 드라이브 업로드 알림: {e}")

    return full_pdf_path

if __name__ == "__main__":
    generate_btc_pdf_report()
