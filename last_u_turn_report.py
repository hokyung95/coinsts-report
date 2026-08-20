"""
========================================================================================
 [모듈 명]: last_u_turn_report.py (Root Launcher)
 [구현 목적]:
   - U_Style_Code/last_u_turn_report.py 모듈을 루트 위치에서도 간편하게 호출 및 실행
========================================================================================
"""

import sys
import os

# U_Style_Code 디렉터리를 sys.path에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
u_style_dir = os.path.join(current_dir, "U_Style_Code")
if u_style_dir not in sys.path:
    sys.path.insert(0, u_style_dir)

from last_u_turn_report import scan_u_turn_recent, generate_last_u_turn_pdf

if __name__ == "__main__":
    matched_events = scan_u_turn_recent(max_lookback_days=3, max_workers=6)
    generate_last_u_turn_pdf(matched_events)
