"""
========================================================================================
 [모듈 명]: onehour_rsi60_75_ratio80_report_v2.py (루트 래퍼)
 [구현 목적]: onehour_report/onehour_rsi60_75_ratio80_report_v2.py 모듈 실행
========================================================================================
"""

import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
target_dir = os.path.join(script_dir, "onehour_report")
if target_dir not in sys.path:
    sys.path.insert(0, target_dir)

from onehour_rsi60_75_ratio80_report_v2 import generate_onehour_rsi60_75_ratio80_pdf_report_v2

if __name__ == "__main__":
    generate_onehour_rsi60_75_ratio80_pdf_report_v2()
