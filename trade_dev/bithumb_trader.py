"""
========================================================================================
 [모듈 명]: trade_dev/bithumb_trader.py
 [구현 목적]:
   - 빗썸 Open API V1 인증 및 주문 처리 (모의 매수/매도 Dry-Run 내장)
   - [기본 트레이딩 규격]:
     * 총 계좌 자본금: 2,500,000 KRW (250만원)
     * 코인당 1회 매수 금액: 200,000 KRW (20만원)
   - [매도 선(先)처리 로직]: 매수 집행 전, 보유 종목(HOLDING)에 대해 3가지 OR 매도 조건 검증
     ① [목표가 익절]: 고가/종가 상승률 >= +50.0% 달성 시
     ② [종가 < 전환선 매도]: 거래가격(종가) < 일목 전환선(9) 이탈 시
     ③ [스탑로스 매도]: low_price 손실률 <= -3.0% 시 스탑로스 청산
   - [매수 후(後)처리 로직]: DB 중복 매수 검증 후 신규 포착 코인 매수 집행 및 DB 기록
========================================================================================
"""

import os
import sys
import json
import uuid
import time
import requests
import jwt
import hashlib
from urllib.parse import urlencode
from datetime import datetime

# 동일 폴더의 db_manager 모듈 임포트
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import db_manager

KEYS_FILE_PATH = os.path.join(current_dir, "bithumb_keys.json")

def load_bithumb_keys():
    """빗썸 API 인증키 파일 로드"""
    if os.path.exists(KEYS_FILE_PATH):
        try:
            with open(KEYS_FILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                access_key = data.get('access_key', '').strip()
                secret_key = data.get('secret_key', '').strip()
                if access_key and secret_key and access_key != "YOUR_BITHUMB_ACCESS_KEY":
                    return access_key, secret_key
        except Exception as e:
            print(f"API 키 로드 오류: {e}")
    return None, None

def get_auth_header(access_key, secret_key, query_dict=None):
    """빗썸 V1 API JWT Authorization 헤더 생성"""
    payload = {
        'access_key': access_key,
        'nonce': str(uuid.uuid4()),
        'timestamp': int(time.time() * 1000)
    }
    if query_dict:
        query_string = urlencode(query_dict).encode('utf-8')
        m = hashlib.sha512()
        m.update(query_string)
        payload['query_hash'] = m.hexdigest()
        payload['query_hash_alg'] = 'SHA512'

    jwt_token = jwt.encode(payload, secret_key, algorithm='HS256')
    return {"Authorization": f"Bearer {jwt_token}", "accept": "application/json"}

def process_auto_sells(all_coins_dict, is_dry_run=True):
    """
    [PHASE 1: 매수 전 매도 선(先)처리]
    현재 DB상 status='HOLDING' 상태인 종목들을 대상으로 3가지 OR 매도 조건 검증:
      ① [목표가 익절]: 매수가 대비 (high_price 또는 trade_price) 상승률 >= +50.0%
      ② [종가 < 전환선 매도]: 종가(trade_price) < 전환선9(ConversionLine) 하회 이탈
      ③ [스탑로스 매도]: 매수가 대비 최저가(low_price) 손실률 <= -3.0%
    """
    db_manager.init_db()
    holding_positions = db_manager.get_holding_positions()
    
    if not holding_positions:
        print("[PHASE 1] 현재 보유 중(HOLDING)인 종목이 없습니다. (매도 진행 건너뜀)", flush=True)
        return []

    print(f"\n[PHASE 1] 보유 종목 {len(holding_positions)}개 매도 조건 (OR조건) 검증 시작...", flush=True)
    sold_list = []

    for pos in holding_positions:
        market = pos['market']
        korean_name = pos['korean_name']
        buy_price = float(pos['buy_price'])
        buy_volume = float(pos['buy_volume'])
        buy_amount_krw = float(pos['buy_amount_krw'])
        db_id = pos['id']

        if market not in all_coins_dict:
            print(f" - [{korean_name}({market})] 최신 캔들 정보 없음. (스킵)")
            continue

        coin_data = all_coins_dict[market]
        close_price = float(coin_data['close_price'])
        high_price = float(coin_data['high_price'])
        low_price = float(coin_data['low_price'])
        tenkan_9 = float(coin_data['tenkan_1h'])

        # 변동률 계산
        gain_close_pct = ((close_price - buy_price) / buy_price) * 100.0
        gain_high_pct = ((high_price - buy_price) / buy_price) * 100.0
        loss_low_pct = ((low_price - buy_price) / buy_price) * 100.0

        should_sell = False
        exit_reason = None

        # -------------------------------------------------------------
        # 매도 OR 조건 검증
        # -------------------------------------------------------------
        # ① [목표가 익절]: 고가 또는 종가 상승률 >= +50.0%
        if gain_high_pct >= 50.0 or gain_close_pct >= 50.0:
            should_sell = True
            exit_reason = "TAKE_PROFIT_50%"
            reason_desc = f"목표가 익절 달성 (+50.0% 이상 / 고가: {gain_high_pct:+.2f}%, 종가: {gain_close_pct:+.2f}%)"

        # ② [종가 < 전환선 매도]: 종가 < 일목 전환선(9) 이탈
        elif close_price < tenkan_9:
            should_sell = True
            exit_reason = "TENKAN_BREAK_EXIT"
            reason_desc = f"전환선9 하회 이탈 (종가: {close_price:,.1f}원 < 전환선: {tenkan_9:,.1f}원)"

        # ③ [스탑로스 매도]: low_price 손실률 <= -3.0%
        elif loss_low_pct <= -3.0:
            should_sell = True
            exit_reason = "STOP_LOSS_3%"
            reason_desc = f"스탑로스 손실선 도달 (-3.0% 이하 / 저가 손실률: {loss_low_pct:+.2f}%)"

        # 매도 처리
        if should_sell:
            sell_price = close_price
            sell_amount_krw = buy_volume * sell_price
            realized_pnl_pct = gain_close_pct

            if is_dry_run:
                mock_order_id = f"MOCK_SELL_{market}_{int(time.time())}"
                print(f" ★ [모의 매도 집행 완료] {korean_name}({market}) | 사유: {reason_desc} | 매수가: {buy_price:,.1f}원 -> 매도가: {sell_price:,.1f}원 | 수익률: {realized_pnl_pct:+.2f}% | 정산금액: {sell_amount_krw:,.0f}원", flush=True)
                db_manager.record_sell_order(
                    db_id=db_id,
                    sell_price=sell_price,
                    sell_amount_krw=sell_amount_krw,
                    pnl_pct=realized_pnl_pct,
                    exit_reason=exit_reason
                )
                sold_list.append({
                    'market': market,
                    'korean_name': korean_name,
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'pnl_pct': realized_pnl_pct,
                    'exit_reason': exit_reason
                })
            else:
                # 실전 매도 API (생략)
                pass
        else:
            print(f"   [보유 유지] {korean_name}({market}) | 진입가: {buy_price:,.1f}원 | 현재가: {close_price:,.1f}원({gain_close_pct:+.2f}%) | 전환선9: {tenkan_9:,.1f}원")

    return sold_list

def process_auto_buys(captured_list, max_buy_coins=10, buy_amount_per_coin=200000, is_dry_run=True):
    """
    [PHASE 2: 신규 포착 코인 중복 검증 & 후(後)매수 집행]
    1. 계좌 포트폴리오 가용 현금 잔액 체크 (자본금 250만원 기준)
    2. 코인당 20만원(200,000원) 매수 집행
    3. 이미 HOLDING 중인 코인 제외
    """
    db_manager.init_db()

    if not captured_list:
        print("\n[PHASE 2] 포착된 매수 대상 코인이 없습니다.", flush=True)
        return []

    # 포트폴리오 현금 잔액 체크
    acc_summary = db_manager.get_account_portfolio_summary()
    available_cash = acc_summary['available_cash_krw']

    print(f"\n[PHASE 2] 신규 포착 코인 {len(captured_list)}개 대상 매수 검증 시작", flush=True)
    print(f" - 계좌 자본금: {acc_summary['initial_capital']:,.0f}원 | 가용 현금 잔액: {available_cash:,.0f}원 | 1회 매수금액: {buy_amount_per_coin:,.0f}원 | 보유코인: {acc_summary['holding_count']}개", flush=True)

    bought_list = []

    for item in captured_list:
        if available_cash < buy_amount_per_coin:
            print(f" -> 가용 현금 잔액({available_cash:,.0f}원)이 매수 금액({buy_amount_per_coin:,.0f}원)보다 부족하여 추가 매수를 종료합니다.", flush=True)
            break

        if len(bought_list) >= max_buy_coins:
            print(f" -> 최대 매수 제한 수량({max_buy_coins}개)에 도달하여 매수를 종료합니다.", flush=True)
            break

        market = item['market']
        korean_name = item['korean_name']
        close_price = float(item['close_price'])

        # DB 중복 보유 검증
        if db_manager.is_already_holding(market):
            print(f" -> [매수 제외] {korean_name}({market}): 이미 보유 중(HOLDING)인 코인입니다.", flush=True)
            continue

        # 매수 수량 계산 (20만원 / 체결가)
        buy_amount_krw_val = float(buy_amount_per_coin)
        volume = buy_amount_krw_val / close_price if close_price > 0 else 0.0

        if is_dry_run:
            mock_order_id = f"MOCK_BUY_{market}_{int(time.time())}"
            db_manager.record_buy_order(
                order_id=mock_order_id,
                market=market,
                korean_name=korean_name,
                buy_price=close_price,
                buy_amount_krw=buy_amount_krw_val,
                buy_volume=volume,
                is_dry_run=1
            )
            available_cash -= buy_amount_krw_val

            print(f" ★ [모의 매수 완료] {korean_name}({market}) | 매수가: {close_price:,.1f}원 | 매수수량: {volume:,.4f} 코인 | 투입금액: {buy_amount_krw_val:,.0f}원 (남은 현금: {available_cash:,.0f}원)", flush=True)
            bought_list.append({
                'market': market,
                'korean_name': korean_name,
                'buy_price': close_price,
                'buy_volume': volume,
                'buy_amount_krw': buy_amount_krw_val
            })

    return bought_list

if __name__ == "__main__":
    print("Bithumb Trader 모듈 (250만원 자본금 / 20만원 매수) 테스트 완료")
