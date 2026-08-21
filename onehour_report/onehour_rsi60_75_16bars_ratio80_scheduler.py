"""
========================================================================================
 [모듈 명]: onehour_report/onehour_rsi60_75_16bars_ratio80_scheduler.py
 [구현 목적]:
   - 빗썸 원화(KRW) 코인 대상 1시간봉 최근 16봉 RSI 60~75 80%+ 포착 및 구글 드라이브 자동 업로드 모듈을 매시간 01분 00초(HH:01:00) 정각에 자동 실행
   - 다음 HH:01:00 시각까지의 대기 시간을 초 단위로 정밀 산출하여 time.sleep 수행
   - 실행 실패나 네트워크 예외가 발생하더라도 스케줄러 상주 프로세스가 중단되지 않고 지속 연속 동작
========================================================================================
"""

import time
import os
import sys
from datetime import datetime, timedelta

# 원화 모듈 경로 등록
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from onehour_rsi60_75_16bars_ratio80_report import generate_onehour_rsi60_75_16bars_ratio80_pdf_report

def get_seconds_until_next_target(target_minute=1, target_second=0):
    """
    현재 시각 기준으로 다음 목표 시각(HH:target_minute:target_second)까지 남은 대기 시간(초) 산출
    예: 16:31:22 일 때 목표 17:01:00 -> 1778초 (29분 38초) 남음
    """
    now = datetime.now()
    # 당일 당시간의 target_minute:target_second 시각
    target_time = now.replace(minute=target_minute, second=target_second, microsecond=0)
    
    # 이미 현재 시각이 목표 시각을 지나쳤다면 1시간 뒤 목표 시각으로 설정
    if now >= target_time:
        target_time += timedelta(hours=1)
        
    seconds_left = (target_time - now).total_seconds()
    return seconds_left, target_time

def run_hourly_scheduler(run_immediately=True):
    """
    매시간 01분 00초 정각 스케줄러 실행 함수
    run_immediately=True 일 경우 시작 시 1회 즉시 실행 후 정각 대기 루프 진입
    """
    print("=" * 80, flush=True)
    print(" [빗썸 1시간봉 16봉 RSI (60~75 80%+) 매시간 01분 00초 자동 스케줄러 시작] ", flush=True)
    print(f" - 스케줄러 실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f" - 실행 주기: 매시간 01분 00초 (HH:01:00)", flush=True)
    print("=" * 80 + "\n", flush=True)

    if run_immediately:
        print("▶ [초기 실행] 스케줄러 시작과 함께 1회 즉시 스리닝 및 구글 드라이브 업로드를 진행합니다...", flush=True)
        try:
            generate_onehour_rsi60_75_16bars_ratio80_pdf_report()
        except Exception as e:
            print(f"❌ 초기 실행 중 에러 발생: {e}", flush=True)
        print("-" * 80 + "\n", flush=True)

    while True:
        try:
            seconds_left, next_target_time = get_seconds_until_next_target(target_minute=1, target_second=0)
            mins = int(seconds_left // 60)
            secs = int(seconds_left % 60)
            
            print(f"⏳ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 다음 정각 실행 예정 시각: {next_target_time.strftime('%Y-%m-%d %H:%M:%S')} (남은 대기 시간: {mins}분 {secs}초 / {seconds_left:.1f}초)...", flush=True)
            
            # 다음 정각까지 대기
            time.sleep(seconds_left)
            
            # 정각 도달 시 작업 수행
            exec_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n🚀 [{exec_time_str}] 매시간 01분 00초 정각 포착 모듈 자동 실행 시작!", flush=True)
            
            # 리포트 포착 및 구글 드라이브 업로드 실행
            generate_onehour_rsi60_75_16bars_ratio80_pdf_report()
            
            print(f"✅ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 정각 실행 완료! 다음 타깃 시각 대기 모드로 전환합니다.\n", flush=True)
            print("-" * 80 + "\n", flush=True)
            
            # 연속 즉시 재실행 방지를 위해 5초 미세 대기
            time.sleep(5)
            
        except KeyboardInterrupt:
            print("\n👋 사용자에 의해 스케줄러가 종료되었습니다.", flush=True)
            break
        except Exception as e:
            print(f"❌ 스케줄러 루프 실행 중 에러 발생 (스케줄러는 계속 유지됨): {e}", flush=True)
            # 에러 발생 시 30초 후 다음 루프 재시도
            time.sleep(30)

if __name__ == "__main__":
    run_hourly_scheduler(run_immediately=True)
