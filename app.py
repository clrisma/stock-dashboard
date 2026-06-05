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

API_KEY = st.secrets["DART_API_KEY"]

def get_end_date():
    today = datetime.now()
    if today.weekday() == 0:
        return (today - timedelta(days=3)).strftime('%Y-%m-%d')
    elif today.weekday() >= 5:
        return (today - timedelta(days=today.weekday()-4)).strftime('%Y-%m-%d')
    else:
        return (today - timedelta(days=1)).strftime('%Y-%m-%d')

@st.cache_data(ttl=86400)
def get_corp_list():
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    res = requests.get(url, params={"crtfc_key": API_KEY})
    z = zipfile.ZipFile(io.BytesIO(res.content))
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

def analyze_stock(code, name):
    try:
        end_date = get_end_date()
        df = fdr.DataReader(code, '2025-01-01', end_date)
        if len(df) < 60:
            return None
        score = 0
        signals = []
        curr_close = df['Close'].iloc[-1]

        vol_ratio = df['Volume'].iloc[-5:].mean() / df['Volume'].rolling(20).mean().iloc[-1]
        if vol_ratio >= 1.5:
            score += 1
            signals.append(f"✅ 거래량 ({vol_ratio:.1f}배)")
        else:
            signals.append(f"❌ 거래량 ({vol_ratio:.1f}배)")

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

        ratio_52w = curr_close / df['High'].iloc[-252:].max() * 100
        if ratio_52w >= 70:
            score += 1
            signals.append(f"✅ 52주 고점 {ratio_52w:.0f}%")
        else:
            signals.append(f"❌ 52주 고점 {ratio_52w:.0f}%")

        ma5 = df['Close'].rolling(5).mean().iloc[-1]
        if ma5 > ma20.iloc[-1] > ma60.iloc[-1]:
            score += 1
            signals.append("✅ 정배열(5>20>60)")
        else:
            signals.append("❌ 정배열 미완성")

        change_20d = (curr_close - df['Close'].iloc[-21]) / df['Close'].iloc[-21] * 100
        if change_20d >= 3:
            score += 1
            signals.append(f"✅ 20일 수익률 (+{change_20d:.1f}%)")
        else:
            signals.append(f"❌ 20일 수익률 ({change_20d:.1f}%)")

        return {
            '종목명': name,
            '종목코드': code,
            '현재가': int(curr_close),
            '스코어': score,
            '신호': ' | '.join(signals)
        }
    except:
        return None

st.title("📊 주식 스코어링 대시보드")
st.caption(f"기준일: {get_end_date()} | 코스피+코스닥 각 300개 분석")

with st.sidebar:
    st.header("설정")
    min_score = st.slider("최소 스코어", 1, 5, 3)
    market_filter = st.selectbox("시장 선택", ["전체", "코스피", "코스닥"])
    run_btn = st.button("분석 실행 (15~20분)", type="primary")

if run_btn:
   
    results = []
    for market_name, listing_code in [("코스피", "KOSPI"), ("코스닥", "KOSDAQ")]:
        if market_filter != "전체" and market_filter != market_name:
            continue
        market_df = fdr.StockListing(listing_code).sort_values(
            'Marcap', ascending=False).head(300).reset_index(drop=True)
        merged = market_df.merge(
            corp_df, left_on='Code', right_on='stock_code', how='left'
        )[['Code', 'Name']].reset_index(drop=True)
        progress = st.progress(0, text=f"{market_name} 분석 중...")
        for i, row in merged.iterrows():
            result = analyze_stock(row['Code'], row['Name'])
            if result:
                result['시장'] = market_name
                results.append(result)
            progress.progress((i+1)/len(merged), text=f"{market_name} [{i+1}/{len(merged)}] {row['Name']}")
            time.sleep(0.3)
    result_df = pd.DataFrame(results).sort_values('스코어', ascending=False).reset_index(drop=True)
    st.session_state['result_df'] = result_df
    st.success(f"분석 완료! 총 {len(result_df)}개 종목")

if 'result_df' in st.session_state:
    df = st.session_state['result_df']
    filtered = df[df['스코어'] >= min_score]
    if market_filter != "전체":
        filtered = filtered[filtered['시장'] == market_filter]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("분석 종목", f"{len(df)}개")
    col2.metric("관심 종목(3점+)", f"{len(df[df['스코어']>=3])}개")
    col3.metric("최고 스코어", f"{df['스코어'].max()}점")
    col4.metric("현재 필터", f"{len(filtered)}개")

    fig = px.bar(
        filtered.head(30),
        x='종목명', y='스코어',
        color='시장',
        title='스코어링 TOP 30',
        color_discrete_map={'코스피': '#3498db', '코스닥': '#e67e22'}
    )
    fig.update_layout(xaxis_tickangle=-45)
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        filtered[['종목명', '시장', '현재가', '스코어', '신호']],
        use_container_width=True,
        hide_index=True
    )
