"""
========================================================================================
 [모듈 명]: onehour_rsi60_75_16bars_ratio80_report.py (루트 래퍼)
 [구현 목적]: onehour_report/onehour_rsi60_75_16bars_ratio80_report.py 모듈 실행
========================================================================================
"""

import os
import sys

base_dir = os.path.dirname(os.path.abspath(__file__))
module_file = os.path.join(base_dir, "onehour_report", "onehour_rsi60_75_16bars_ratio80_report.py")

import importlib.util
spec = importlib.util.spec_from_file_location("onehour_rsi60_75_16bars_ratio80_report_mod", module_file)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

if __name__ == "__main__":
    mod.generate_onehour_rsi60_75_16bars_ratio80_pdf_report()
