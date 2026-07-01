#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
매일 자동 실행 오케스트레이터 — 내일 SMP 예측 대시보드 갱신.
① S3 최신 시간별 SMP+수요 다운로드 → smp_hourly_s3.json
② 내일 날짜 계산(today+1) 또는 인자로 지정
③ weather_demand.emit_dashboard → tomorrow_data.json + forecast.html 임베드

사용법:
  python daily_forecast.py               # 내일(today+1) 자동
  python daily_forecast.py 20260702      # 특정일 지정(테스트)
스케줄: run_daily.bat 를 Windows 작업 스케줄러가 매일 07:30 실행.
"""
import os, sys, datetime, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))

def _load(name):
    sp = importlib.util.spec_from_file_location(name, os.path.join(HERE, f"{name}.py"))
    m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m

def main():
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = args[0] if args else (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y%m%d")
    print(f"\n===== [{stamp}] 내일 SMP 예측 갱신 시작 (target={target}) =====")
    try:
        B = _load("s3_backfill")
        B.download()                    # smp_cache+demand_cache 최신 다운로드
        B.save(B.build_hourly())        # → smp_hourly_s3.json
        W = _load("weather_demand")
        W.emit_dashboard(target)        # → tomorrow_data.json + forecast.html 임베드
        print(f"===== [{stamp}] 완료 =====")
    except Exception as e:
        import traceback
        print(f"!!!!! [{stamp}] 실패: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
