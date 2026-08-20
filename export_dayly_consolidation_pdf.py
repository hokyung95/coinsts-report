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

def check_ichimoku_consolidation(df, threshold_pct=0.02):
    """
    일목균형표 기준선, 전환선, 구름대 위에 있으면서
    지표선 근처(밀착)에 머무르는 종목/시점을 필터링하는 조건식
    """
    cloud_top = np.maximum(df["Span1"], df["Span2"])

    above_conversion = df["Close"] >= df["ConversionLine"]
    above_base = df["Close"] >= df["BaseLine"]
    above_cloud = df["Close"] >= cloud_top

    is_above_all = above_conversion & above_base & above_cloud

    dist_from_base = np.abs(df["Close"] - df["BaseLine"]) / df["BaseLine"]
    dist_from_conversion = (
        np.abs(df["Close"] - df["ConversionLine"]) / df["ConversionLine"]
    )

    is_near_lines = (dist_from_base <= threshold_pct) | (
        dist_from_conversion <= threshold_pct
    )

    pct_change = df["Close"].pct_change()
    is_not_spiking = pct_change <= 0.05

    df["Condition"] = is_above_all & is_near_lines & is_not_spiking
    df["DistBase_Pct"] = dist_from_base * 100
    df["DistConversion_Pct"] = dist_from_conversion * 100

    return df

def fetch_and_analyze_single_coin_daily(m, threshold_pct=0.02, count=200):
    """단일 코인 일봉(Daily) 데이터 수집 및 일목 지표선 밀착 분석 함수"""
    market_code = m['market']
    korean_name = m['korean_name']
    english_name = m['english_name']
    
    url = f"https://api.bithumb.com/v1/candles/days?market={market_code}&count={count}"
    headers = {"accept": "application/json"}
    
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) >= 60:
                df = pd.DataFrame(data).iloc[::-1].reset_index(drop=True)
                for col in ['high_price', 'low_price', 'trade_price']:
                    df[col] = df[col].astype(float)
                    
                df['Close'] = df['trade_price']
                df['ConversionLine'] = calc_mid_point(df['high_price'], df['low_price'], 9)
                df['BaseLine'] = calc_mid_point(df['high_price'], df['low_price'], 26)
                df['Span1'] = ((df['ConversionLine'] + df['BaseLine']) / 2).shift(26)
                df['Span2'] = calc_mid_point(df['high_price'], df['low_price'], 52).shift(26)
                
                df_analyzed = check_ichimoku_consolidation(df, threshold_pct=threshold_pct)
                last_row = df_analyzed.iloc[-1]
                
                if last_row['Condition']:
                    return {
                        'market': market_code,
                        'korean_name': korean_name,
                        'english_name': english_name,
                        'close_price': last_row['Close'],
                        'conversion_line': round(last_row['ConversionLine'], 2),
                        'base_line': round(last_row['BaseLine'], 2),
                        'dist_base_pct': round(last_row['DistBase_Pct'], 2),
                        'dist_conversion_pct': round(last_row['DistConversion_Pct'], 2),
                        'df': df_analyzed
                    }
    except Exception:
        pass
    return None

def generate_daily_pdf_report(pdf_path=None, threshold_pct=0.02, max_coins=None, max_workers=4, upload_gdrive=True):
    """
    일봉 포착 코인 대상: report_daily/report_daily_YYYYMMDD.pdf 형식으로 저장 후 구글 드라이브 업로드
    """
    if pdf_path is None:
        save_dir = "d:/pyprj/coinsts/report_daily"
        os.makedirs(save_dir, exist_ok=True)
        filename = f"report_daily_{datetime.now().strftime('%Y%m%d')}.pdf"
        pdf_path = os.path.join(save_dir, filename)

    markets = get_krw_markets()
    if max_coins:
        markets = markets[:max_coins]

    print(f"[1/3] 총 {len(markets)}개 원화 코인 [일봉(Daily) 기준] 데이터 수집 및 분석 중 (스레드수: {max_workers})...")
    
    captured_list = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_and_analyze_single_coin_daily, m, threshold_pct): m for m in markets}
        for future in as_completed(futures):
            res = future.result()
            if res:
                captured_list.append(res)
                print(f" ★ 일봉 포착: {res['korean_name']}({res['english_name']} / {res['market']})")
                
    captured_list.sort(key=lambda x: x['market'])
    
    print(f"\n[2/3] 총 {len(captured_list)}개 일봉 포착 코인 차트 시각화 및 PDF 파일 생성 중...")
    
    if not captured_list:
        print("일봉 기준 포착된 코인이 없어 PDF 생성을 중단합니다.")
        return None

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with PdfPages(pdf_path) as pdf:
        # -------------------------------------------------------------
        # 표지 및 요약 표 페이지 (Page 1 ~ )
        # -------------------------------------------------------------
        chunk_size = 22
        summary_rows_all = [
            [
                c['market'],
                c['korean_name'],
                c['english_name'],
                f"{c['close_price']:,}",
                f"{c['conversion_line']:,}",
                f"{c['base_line']:,}",
                f"{c['dist_conversion_pct']:.2f}%",
                f"{c['dist_base_pct']:.2f}%"
            ] for c in captured_list
        ]
        
        col_labels = ['마켓코드', '한글명', '영문명', '현재종가(원)', '전환선(9)', '기준선(26)', '전환선 괴리율', '기준선 괴리율']

        for page_idx in range(0, len(summary_rows_all), chunk_size):
            chunk = summary_rows_all[page_idx : page_idx + chunk_size]
            fig_table, ax_table = plt.subplots(figsize=(11.69, 8.27))
            ax_table.axis('off')

            title_text = "빗썸 일목균형표 지표선 밀착/상승 횡보 포착 코인 리포트 (일봉 기준)"
            subtitle_text = f"분석 일시: {now_str} | 대상 마켓: 빗썸 KRW 전체 (일봉) | 총 포착 코인 수: {len(captured_list)}개 (페이지 {page_idx//chunk_size + 1})"
            
            ax_table.text(0.5, 0.96, title_text, fontsize=16, fontweight='bold', ha='center', va='top')
            ax_table.text(0.5, 0.92, subtitle_text, fontsize=10, color='gray', ha='center', va='top')

            table = ax_table.table(
                cellText=chunk,
                colLabels=col_labels,
                cellLoc='center',
                loc='center',
                bbox=[0.03, 0.05, 0.94, 0.82]
            )
            table.auto_set_font_size(False)
            table.set_fontsize(8)
            
            for col_i in range(len(col_labels)):
                cell = table[(0, col_i)]
                cell.set_facecolor('#1c5235')
                cell.set_text_props(color='white', fontweight='bold')
                
            plt.tight_layout()
            pdf.savefig(fig_table)
            plt.close(fig_table)

        # -------------------------------------------------------------
        # 개별 코인 일목균형표 차트 페이지 (Page N ~ )
        # -------------------------------------------------------------
        num_coins = len(captured_list)
        for i in range(0, num_coins, 2):
            fig_charts, axes = plt.subplots(2, 1, figsize=(11.69, 8.27), sharex=False)
            
            for j in range(2):
                coin_idx = i + j
                if coin_idx < num_coins:
                    coin_data = captured_list[coin_idx]
                    ax = axes[j]
                    df_c = coin_data['df']

                    x = range(len(df_c))
                    
                    ax.plot(x, df_c['Close'], label='종가', color='black', linewidth=1.3)
                    ax.plot(x, df_c['ConversionLine'], label='전환선(9)', color='#e31a1c', linewidth=1.1)
                    ax.plot(x, df_c['BaseLine'], label='기준선(26)', color='#1f78b4', linewidth=1.1)
                    
                    ax.plot(x, df_c['Span1'], label='선행스팬1', color='#33a02c', linewidth=0.8, linestyle='--')
                    ax.plot(x, df_c['Span2'], label='선행스팬2', color='#ff7f00', linewidth=0.8, linestyle='--')
                    
                    ax.fill_between(
                        x, df_c['Span1'], df_c['Span2'],
                        where=(df_c['Span1'] >= df_c['Span2']),
                        color='#b2df8a', alpha=0.35, label='양운(상승 구름)'
                    )
                    ax.fill_between(
                        x, df_c['Span1'], df_c['Span2'],
                        where=(df_c['Span1'] < df_c['Span2']),
                        color='#fb9a99', alpha=0.35, label='음운(하락 구름)'
                    )

                    k_name = coin_data['korean_name']
                    e_name = coin_data['english_name']
                    m_code = coin_data['market']
                    price = coin_data['close_price']
                    d_conv = coin_data['dist_conversion_pct']
                    d_base = coin_data['dist_base_pct']
                    
                    title_str = f"[{coin_idx+1}/{num_coins}] {k_name} ({e_name} / {m_code})  |  현재가: {price:,}원  |  일봉 전환선 괴리율: {d_conv:.2f}%  |  일봉 기준선 괴리율: {d_base:.2f}%"
                    ax.set_title(title_str, fontsize=10.5, fontweight='bold', pad=8)
                    ax.set_ylabel("가격 (KRW)", fontsize=8.5)
                    ax.set_xlabel("일자 (최신 일봉 시계열)", fontsize=8)
                    ax.legend(loc='upper left', fontsize=7.5, framealpha=0.85, ncol=3)
                    ax.grid(True, linestyle=':', alpha=0.5)
                else:
                    axes[j].axis('off')

            plt.tight_layout()
            pdf.savefig(fig_charts)
            plt.close(fig_charts)

    full_pdf_path = os.path.abspath(pdf_path)
    print(f"\n[3/3] 일봉 PDF 리포트 생성 완료!\n -> 저장 위치: '{full_pdf_path}'")

    if upload_gdrive:
        try:
            from upload_to_gdrive import upload_pdf_to_gdrive
            upload_pdf_to_gdrive(full_pdf_path, folder_name="report_daily", user_email="hhokyung@gmail.com")
        except Exception as e:
            print(f"구글 드라이브 업로드 알림: {e}")

    return full_pdf_path

if __name__ == "__main__":
    generate_daily_pdf_report(threshold_pct=0.02, max_workers=4)
