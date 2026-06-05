import streamlit as st
import pandas as pd
import numpy as np
import requests
import zipfile
import io
import xml.etree.ElementTree as ET
import FinanceDataReader as fdr
import plotly.express as px
import time
from datetime import datetime, timedelta

st.set_page_config(page_title="주식 스코어링 대시보드", layout="wide")

# API 키 설정
API_KEY = st.secrets["DART_API_KEY"]

# 기준일 자동 설정
def get_end_date():
    today = datetime.now()
    if today.weekday() == 0:
        return (today - timedelta(days=3)).strftime('%Y-%m-%d')
    elif today.weekday() >= 5:
        return (today - timedelta(days=today.weekday()-4)).strftime('%Y-%m-%d')
    else:
        return (today - timedelta(days=1)).strftime('%Y-%m-%d')

# DART 기업목록
@st.cache_data(ttl=86400)
def get_corp_list():
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    z = zipfile.ZipFile(io.BytesIO(requests.get(url, params={"crtfc_key": API_KEY}).content))
    root = ET.fromstring(z.read("CORPCODE.xml"))
    corps = []
    for item in root.findall("list"):
        stock_code = item.findtext("stock_code", "").strip()
        if stock_code:
            corps.append({
                "corp_code": item.findtext("corp_code", "").strip(),
                "corp_name": item.findtext("corp_name", "").strip(),
                "stock_code": stock_code
            })
    return pd.DataFrame(corps)

# 스코어링 함수
def analyze_stock(code, name):
    try:
        end_date = get_end_date()
        df = fdr.DataReader(code, '2025-01-01', end_date)
        if len(df) < 60:
            return None
        score = 0
        signals = []
        curr_close = df['Close'].iloc[-1]

        # 1. 거래량
        vol_ratio = df['Volume'].iloc[-5:].mean() / df['Volume'].rolling(20).mean().iloc[-1]
        if vol_ratio >= 1.5:
            score += 1
            signals.append(f"✅ 거래량 ({vol_ratio:.1f}배)")
        else:
            signals.append(f"❌ 거래량 ({vol_ratio:.1f}배)")

        # 2. 눌림목 (ATR 동적)
        ma20 = df['Close'].rolling(20).mean()
        ma60 = df['Close'].rolling(60).mean()
        atr = (df['High'] - df['Low']).rolling(14).mean().iloc[-1]
        atr_ratio = atr / ma20.iloc[-1]
        dynamic_range = round(atr_ratio * 1.5 * 100, 1)
        is_uptrend = ma20.iloc[-1] > ma60.iloc[-1]
        near_ma20 = abs(curr_close - ma20.iloc[-1]) / ma20.iloc[-1] < atr_ratio * 1.5
        if is_uptrend and near_ma20:
            score += 1
            signals.append(f"✅ 눌림목 (±{dynamic_range}%)")
        else:
            signals.append(f"❌ 눌림목 (±{dynamic_range}%)")

        # 3. 52주 고점
        ratio_52w = curr_close / df['High'].iloc[-252:].max() * 100
        if ratio_52w >= 70:
            score += 1
            signals.append(f"✅ 52주 고점 {ratio_52w:.0f}%")
        else:
            signals.append(f"❌ 52주 고점 {ratio_52w:.0f}%")

        # 4. 정배열
        ma5 = df['Close'].rolling(5).mean().iloc[-1]
        if ma5 > ma20.iloc[-1] > ma60.iloc[-1]:
            score += 1
            signals.append("✅ 정배열(5>20>60)")
        else:
            signals.append("❌ 정배열 미완성")

        # 5. 20일 수익률
        change_20d = (curr_close - df['Close'].iloc[-21]) / df['Close'].iloc[-21] * 100
        if change_20d >= 3:
            score += 1
            signals.append(f"✅ 20일 수익률 (+{change_20d:.1f}%)")
        else:
            signals.append(f"❌ 20일 수익률 ({change_20d:.1f}%)")

        return {
            '종목명': name, '종목코드': code,
            '현재가': int(curr_close), '스코어': score,
            '신호': ' | '.join(signals)
        }
    except:
        return None

# 메인 UI
st.title("📊 주식 스코어링 대시보드")
st.caption(f"기준일: {get_end_date()} | 코스피+코스닥 각 300개 분석")

# 사이드바
with st.sidebar:
    st.header("⚙️ 설정")
    min_score = st.slider("최소 스코어", 1, 5, 3)
    market_filter = st.selectbox("시장 선택", ["전체", "코스피", "코스닥"])
    run_btn = st.button("🔄 분석 실행 (15~20분)", type="primary")

if run_btn:
    corp_df = get_corp_list()
    results = []

    for market_name, listing_code in [("코스피", "KOSPI"), ("코스닥", "KOSDAQ")]:
        if market_filter != "전체" and market_filter != market_name:
            continue
        
        market_df = fdr.StockListing(listing_code).sort_values('Marcap', ascending=False).head(300).reset_index(drop=True)
        merged = market_df.merge(corp_df, left_on='Code'
