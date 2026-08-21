"""
========================================================================================
 [모듈 명]: trade_dev/trade_dev_scheduler.py
 [구현 목적]:
   - 24시간 상주형 자동 트레이딩 & 성과 리포트 스케줄러
   - [스케줄 1]: 매시간 01분 00초 (HH:01:00) 
     -> 1시간봉 16봉 RSI (60~75) 포착, 매수 전 선(先)매도 처리, 후(後)매수(20만원) 집행, PDF/구글드라이브 업로드
   - [스케줄 2]: 매일 00시 30분 00초 (00:30:00)
     -> 250만원 자본금 기준 전일 매매 성과/승률/실현손익/평가액 종합 PDF 보고서 생성 & 구글드라이브 업로드
   - 프로세스 네트워크 오류/예외 발생 시 자동 복구 및 무한 연속 동작
========================================================================================
"""

import time
import os
import sys
from datetime import datetime, timedelta

# trade_dev 및 상위 경로 등록
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from onehour_rsi60_75_16bars_ratio80_report_trade import run_onehour_trade_pipeline
from daily_trade_performance_report import generate_daily_trade_performance_report

def get_seconds_until_next_hourly(target_minute=1, target_second=0):
    """다음 매시간 HH:target_minute:target_second 시각까지 남은 초 산출"""
    now = datetime.now()
    target_time = now.replace(minute=target_minute, second=target_second, microsecond=0)
    if now >= target_time:
        target_time += timedelta(hours=1)
    return (target_time - now).total_seconds(), target_time

def get_seconds_until_daily_0030():
    """다음 00시 30분 00초(00:30:00) 시각까지 남은 초 산출"""
    now = datetime.now()
    target_time = now.replace(hour=0, minute=30, second=0, microsecond=0)
    if now >= target_time:
        target_time += timedelta(days=1)
    return (target_time - now).total_seconds(), target_time

def run_trade_dev_scheduler(run_immediately=True):
    """
    24시간 365일 상주 트레이딩 및 일일 성과 보고서 통합 스케줄러 메인 루프
    """
    print("=" * 80, flush=True)
    print(" [CoinSTS trade_dev 24시간 365일 상주 트레이딩 & 성과 보고서 스케줄러 시작] ", flush=True)
    print(f" - 시작 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f" - 스케줄 1: 매시간 01분 (HH:01:00) 트레이딩 스캔 & 매수/매도 & 보고서 업로드", flush=True)
    print(f" - 스케줄 2: 매일 00시 30분 (00:30:00) 전일 매매 수익 종합 분석 보고서 업로드", flush=True)
    print("=" * 80 + "\n", flush=True)

    if run_immediately:
        print("▶ [초기 실행] 스케줄러 시작과 함께 매매 파이프라인 1회를 즉시 집행합니다...", flush=True)
        try:
            run_onehour_trade_pipeline(is_dry_run=True)
        except Exception as e:
            print(f"초기 실행 중 오류 발생: {e}", flush=True)
        print("-" * 80 + "\n", flush=True)

    last_hourly_run_hour = -1
    last_daily_run_date = ""

    while True:
        try:
            now = datetime.now()
            current_date_str = now.strftime("%Y-%m-%d")
            current_hour = now.hour
            current_minute = now.minute

            # [체크 1]: 매시간 01분 정각 체크
            if current_minute == 1 and current_hour != last_hourly_run_hour:
                exec_time_str = now.strftime('%Y-%m-%d %H:%M:%S')
                print(f"\n🚀 [{exec_time_str}] [매시간 정각 트레이딩 파이프라인] 자동 실행 시작!", flush=True)
                try:
                    run_onehour_trade_pipeline(is_dry_run=True)
                    last_hourly_run_hour = current_hour
                    print(f"✅ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 매시간 트레이딩 완료!", flush=True)
                except Exception as e:
                    print(f"❌ 매시간 트레이딩 실행 중 오류: {e}", flush=True)

            # [체크 2]: 매일 00시 30분 정각 체크
            if current_hour == 0 and current_minute == 30 and current_date_str != last_daily_run_date:
                exec_time_str = now.strftime('%Y-%m-%d %H:%M:%S')
                print(f"\n📊 [{exec_time_str}] [일일 00:30 전일 매매 수익 분석 리포트] 자동 발행 시작!", flush=True)
                try:
                    generate_daily_trade_performance_report()
                    last_daily_run_date = current_date_str
                    print(f"✅ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 일일 수익 분석 리포트 생성 및 업로드 완료!", flush=True)
                except Exception as e:
                    print(f"❌ 일일 수익 분석 실행 중 오류: {e}", flush=True)

            # 다음 1분 체크를 위한 10초 미세 대기
            time.sleep(10)

        except KeyboardInterrupt:
            print("\n👋 사용자에 의해 스케줄러가 정지되었습니다.", flush=True)
            break
        except Exception as e:
            print(f"❌ 스케줄러 메인 루프 예외 발생 (스케줄러 지속 유지됨): {e}", flush=True)
            time.sleep(15)

if __name__ == "__main__":
    run_trade_dev_scheduler(run_immediately=False)
