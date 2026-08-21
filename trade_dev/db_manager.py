"""
========================================================================================
 [모듈 명]: trade_dev/db_manager.py
 [구현 목적]:
   - SQLite3 데이터베이스(coinsts.db) 연동 및 스키마 관리
   - 1시간봉 스캔 포착 신호 기록 (captured_signals)
   - 매수/매도 주문 이력 관리 (orders)
   - 자본금(250만원) 및 계좌 잔고/평가액 모니터링 (get_account_portfolio_summary)
   - 현재 보유 중(HOLDING) 코인 조회 및 중복 매수 검증
   - 매도 완료 처리 (SOLD) 및 실현 수익률(PnL) 기록
   - 일일 매매 성과 집계 (00:30 리포트용)
========================================================================================
"""

import sqlite3
import os
import pandas as pd
from datetime import datetime

# DB 파일 저장 경로 설정 (trade_dev 폴더 내 coinsts.db)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "coinsts.db")

# 계좌 초기 자본금 및 1회 매수 금액 설정
INITIAL_CAPITAL = 2500000.0  # 250만원
DEFAULT_BUY_AMOUNT = 200000.0  # 20만원

def get_db_connection(db_path=None):
    """SQLite 데이터베이스 연결 객체 생성"""
    if db_path is None:
        db_path = DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # 딕셔너리 형태로 컬럼 접근 가능
    return conn

def init_db(db_path=None):
    """테이블 스키마 생성 및 초기화"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # 1. 포착 신호 테이블 (captured_signals)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS captured_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scanned_at DATETIME NOT NULL,
            market TEXT NOT NULL,
            korean_name TEXT NOT NULL,
            close_price REAL NOT NULL,
            rsi_60_75_count INTEGER NOT NULL,
            rsi_60_75_ratio REAL NOT NULL,
            prev_3_max_rsi REAL NOT NULL,
            tenkan_diff_pct REAL NOT NULL,
            rsi_1h REAL NOT NULL,
            rsi_daily REAL NOT NULL
        );
    """)

    # 2. 주문 및 매매 이력 테이블 (orders)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            market TEXT NOT NULL,
            korean_name TEXT NOT NULL,
            side TEXT NOT NULL,                  -- 'BUY' / 'SELL'
            order_type TEXT NOT NULL,            -- 'MARKET' / 'LIMIT'
            buy_price REAL NOT NULL,             -- 매수가 (진입가)
            buy_amount_krw REAL NOT NULL,        -- 매수 원화 금액 (예: 200,000원)
            buy_volume REAL NOT NULL,            -- 매수 체결 코인 수량
            sell_price REAL,                     -- 매도가 (매도 시 기록)
            sell_amount_krw REAL,                -- 매도 원화 금액 (매도 시 기록)
            pnl_pct REAL,                        -- 수익률 % (매도 시 기록)
            exit_reason TEXT,                    -- 매도 사유 ('TAKE_PROFIT_50%', 'TENKAN_BREAK_EXIT', 'STOP_LOSS_3%')
            status TEXT NOT NULL,                -- 'HOLDING' / 'SOLD' / 'CANCELLED'
            is_dry_run INTEGER NOT NULL DEFAULT 1,-- 1: 모의매수, 0: 실전매수
            created_at DATETIME NOT NULL,        -- 매수 일시
            updated_at DATETIME                  -- 매도/상태변경 일시
        );
    """)

    # 3. 자본금 및 계좌 설정 정보 테이블 (account_settings)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS account_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            initial_capital REAL NOT NULL DEFAULT 2500000.0,
            buy_amount_per_coin REAL NOT NULL DEFAULT 200000.0,
            updated_at DATETIME NOT NULL
        );
    """)

    # 초기 계좌 설정 값이 없으면 250만원/20만원 기본값 등록
    cursor.execute("SELECT COUNT(*) FROM account_settings")
    if cursor.fetchone()[0] == 0:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO account_settings (initial_capital, buy_amount_per_coin, updated_at) VALUES (?, ?, ?)",
            (INITIAL_CAPITAL, DEFAULT_BUY_AMOUNT, now_str)
        )

    conn.commit()
    conn.close()

def save_captured_signal(item, db_path=None):
    """1시간봉 포착된 코인 신호 DB 저장"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO captured_signals (
            scanned_at, market, korean_name, close_price,
            rsi_60_75_count, rsi_60_75_ratio, prev_3_max_rsi,
            tenkan_diff_pct, rsi_1h, rsi_daily
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now_str,
        item['market'],
        item['korean_name'],
        float(item['close_price']),
        int(item['rsi_60_75_count']),
        float(item['rsi_60_75_ratio']),
        float(item['prev_3_max_rsi']),
        float(item['tenkan_diff_pct']),
        float(item['rsi_1h']),
        float(item['rsi_daily'])
    ))

    conn.commit()
    conn.close()

def get_holding_positions(db_path=None):
    """현재 보유 중(status = 'HOLDING')인 모든 코인 목록 조회"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, order_id, market, korean_name, buy_price, buy_amount_krw, buy_volume, is_dry_run, created_at
        FROM orders
        WHERE status = 'HOLDING'
        ORDER BY created_at ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def is_already_holding(market, db_path=None):
    """특정 마켓 코인이 현재 HOLDING 보유 중인지 확인"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) FROM orders
        WHERE market = ? AND status = 'HOLDING'
    """, (market,))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

def record_buy_order(order_id, market, korean_name, buy_price, buy_amount_krw, buy_volume, is_dry_run=1, db_path=None):
    """매수(BUY) 주문 완료 후 DB 기록 (status = 'HOLDING')"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO orders (
            order_id, market, korean_name, side, order_type,
            buy_price, buy_amount_krw, buy_volume, status, is_dry_run, created_at, updated_at
        ) VALUES (?, ?, ?, 'BUY', 'MARKET', ?, ?, ?, 'HOLDING', ?, ?, ?)
    """, (
        order_id, market, korean_name, float(buy_price), float(buy_amount_krw),
        float(buy_volume), int(is_dry_run), now_str, now_str
    ))

    conn.commit()
    conn.close()

def record_sell_order(db_id, sell_price, sell_amount_krw, pnl_pct, exit_reason, db_path=None):
    """매도(SELL) 완료 후 DB 상태를 'SOLD'로 업데이트하고 실현 손익 기록"""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        UPDATE orders
        SET sell_price = ?,
            sell_amount_krw = ?,
            pnl_pct = ?,
            exit_reason = ?,
            status = 'SOLD',
            updated_at = ?
        WHERE id = ?
    """, (
        float(sell_price), float(sell_amount_krw), float(pnl_pct),
        exit_reason, now_str, db_id
    ))

    conn.commit()
    conn.close()

def get_account_portfolio_summary(current_prices_dict=None, db_path=None):
    """
    250만원 총 자본금 대비 현재 계좌 전체 포트폴리오 상태 종합 산출
    - 총 자본금 (2,500,000원)
    - 매수하여 보유 중인 코인 수 및 투자 원금 합계
    - 실현 손익 합계 (매도 완료 거래)
    - 현금 잔액 (가용 매수 가능금) = 총자본금 - 보유원금합계 + 실현손익
    - 보유 코인 평가금액 및 전체 계좌 평가금액 / 전체 수익률(%)
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # 1. 초기 자본금 설정 로드
    cursor.execute("SELECT initial_capital, buy_amount_per_coin FROM account_settings ORDER BY id DESC LIMIT 1")
    row_setting = cursor.fetchone()
    initial_capital = float(row_setting['initial_capital']) if row_setting else INITIAL_CAPITAL
    buy_amount_per_coin = float(row_setting['buy_amount_per_coin']) if row_setting else DEFAULT_BUY_AMOUNT

    # 2. 매도 완료(SOLD) 거래의 실현 손익 합계
    cursor.execute("""
        SELECT COALESCE(SUM(sell_amount_krw - buy_amount_krw), 0) as total_realized_pnl,
               COUNT(*) as total_sold_count
        FROM orders WHERE status = 'SOLD'
    """)
    row_sold = cursor.fetchone()
    realized_pnl_krw = float(row_sold['total_realized_pnl'])
    total_sold_count = int(row_sold['total_sold_count'])

    # 3. 현재 보유 중(HOLDING) 거래
    cursor.execute("""
        SELECT market, korean_name, buy_price, buy_amount_krw, buy_volume, is_dry_run, created_at
        FROM orders WHERE status = 'HOLDING'
    """)
    holding_rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    holding_count = len(holding_rows)
    holding_invested_krw = sum(float(h['buy_amount_krw']) for h in holding_rows)

    # 가용 현금 잔액 = 총자본금 - 보유투자원금 + 누적실현손익
    available_cash_krw = initial_capital - holding_invested_krw + realized_pnl_krw

    # 현재 평가금액 계산
    holding_eval_krw = 0.0
    for h in holding_rows:
        m = h['market']
        curr_price = float(h['buy_price'])
        if current_prices_dict and m in current_prices_dict:
            curr_price = float(current_prices_dict[m].get('close_price', h['buy_price']))
        h['current_price'] = curr_price
        h['eval_amount_krw'] = float(h['buy_volume']) * curr_price
        h['unrealized_pnl_pct'] = ((curr_price - float(h['buy_price'])) / float(h['buy_price'])) * 100.0
        holding_eval_krw += h['eval_amount_krw']

    total_account_eval_krw = available_cash_krw + holding_eval_krw
    total_account_pnl_krw = total_account_eval_krw - initial_capital
    total_account_return_pct = (total_account_pnl_krw / initial_capital) * 100.0

    return {
        'initial_capital': initial_capital,
        'buy_amount_per_coin': buy_amount_per_coin,
        'holding_count': holding_count,
        'holding_invested_krw': holding_invested_krw,
        'realized_pnl_krw': realized_pnl_krw,
        'available_cash_krw': available_cash_krw,
        'holding_eval_krw': holding_eval_krw,
        'total_account_eval_krw': total_account_eval_krw,
        'total_account_pnl_krw': total_account_pnl_krw,
        'total_account_return_pct': round(total_account_return_pct, 2),
        'holding_positions': holding_rows
    }

def get_daily_performance_summary(target_date_str=None, db_path=None):
    """
    지정된 날짜(YYYY-MM-DD)의 매매 성과 집계
    - target_date_str이 없으면 전일(Yesterday) 기준
    """
    if target_date_str is None:
        target_date_str = (datetime.now() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # 1. 매도 완료(SOLD)된 거래 성과 집계
    cursor.execute("""
        SELECT 
            COUNT(*) as total_sold_count,
            SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as win_count,
            SUM(CASE WHEN pnl_pct <= 0 THEN 1 ELSE 0 END) as loss_count,
            COALESCE(SUM(buy_amount_krw), 0) as total_buy_krw,
            COALESCE(SUM(sell_amount_krw), 0) as total_sell_krw,
            COALESCE(SUM(sell_amount_krw - buy_amount_krw), 0) as total_pnl_krw,
            COALESCE(AVG(pnl_pct), 0) as avg_pnl_pct,
            MAX(pnl_pct) as max_pnl_pct,
            MIN(pnl_pct) as min_pnl_pct
        FROM orders
        WHERE status = 'SOLD' AND DATE(updated_at) = ?
    """, (target_date_str,))
    sold_row = dict(cursor.fetchone())

    # 2. 신규 매수(BUY) 건수 및 금액
    cursor.execute("""
        SELECT COUNT(*) as new_buy_count, COALESCE(SUM(buy_amount_krw), 0) as new_buy_krw
        FROM orders
        WHERE DATE(created_at) = ?
    """, (target_date_str,))
    buy_row = dict(cursor.fetchone())

    # 3. 매도 건별 내역 목록
    cursor.execute("""
        SELECT market, korean_name, buy_price, sell_price, buy_amount_krw, sell_amount_krw, pnl_pct, exit_reason, created_at, updated_at
        FROM orders
        WHERE status = 'SOLD' AND DATE(updated_at) = ?
        ORDER BY updated_at DESC
    """, (target_date_str,))
    sold_trades = [dict(row) for row in cursor.fetchall()]

    # 4. 현재 보유 중(HOLDING) 잔고 목록
    cursor.execute("""
        SELECT id, order_id, market, korean_name, buy_price, buy_amount_krw, buy_volume, is_dry_run, created_at
        FROM orders
        WHERE status = 'HOLDING'
        ORDER BY created_at ASC
    """)
    holding_trades = [dict(row) for row in cursor.fetchall()]

    conn.close()

    win_rate = (sold_row['win_count'] / sold_row['total_sold_count'] * 100.0) if sold_row['total_sold_count'] > 0 else 0.0

    return {
        'target_date': target_date_str,
        'sold_summary': sold_row,
        'buy_summary': buy_row,
        'win_rate': round(win_rate, 1),
        'sold_trades': sold_trades,
        'holding_trades': holding_trades
    }

if __name__ == "__main__":
    init_db()
    print(f"★ DB 및 자본금(250만원/매수20만원) 설정 완료! 경로: {DB_PATH}")
    acc = get_account_portfolio_summary()
    print(f"총 자본금: {acc['initial_capital']:,.0f}원 | 매수원금: {acc['holding_invested_krw']:,.0f}원 | 가용현금: {acc['available_cash_krw']:,.0f}원 | 보유코인: {acc['holding_count']}개")
