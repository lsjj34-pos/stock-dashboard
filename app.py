import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup

# Streamlit 페이지 설정
st.set_page_config(page_title="AI 증권 대시보드", page_icon="📈", layout="wide")

@st.cache_data(ttl=3600) # 1시간마다 갱신
def get_exchange_rate():
    """
    네이버 금융에서 실시간 원/달러 환율을 스크래핑합니다.
    """
    try:
        url = "https://finance.naver.com/marketindex/"
        res = requests.get(url)
        soup = BeautifulSoup(res.text, 'html.parser')
        # 미국 USD 환율 추출
        rate_str = soup.select_one('#exchangeList > li.on > a.head.usd > div > span.value').text
        # 쉼표 제거 후 float 변환
        rate = float(rate_str.replace(',', ''))
        return rate
    except Exception as e:
        # 스크래핑 실패 시 대략적인 기본값 반환
        return 1300.0

def load_data(ticker_symbol, period, interval):
    """
    yfinance를 통해 주가 데이터와 재무제표 데이터를 수집합니다.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period=period, interval=interval)
        info = ticker.info
        financials = ticker.financials
        balance_sheet = ticker.balance_sheet
        return ticker, hist, info, financials, balance_sheet
    except Exception as e:
        st.error(f"데이터를 불러오는 중 오류가 발생했습니다: {e}")
        return None, None, None, None, None

def plot_candlestick(hist):
    """
    Plotly를 이용해 일봉 차트와 이동평균선을 시각화합니다.
    """
    if hist is None or hist.empty:
        st.warning("차트를 그릴 주가 데이터가 없습니다.")
        return
        
    # 이동평균선 계산
    hist['MA20'] = hist['Close'].rolling(window=20).mean()
    hist['MA60'] = hist['Close'].rolling(window=60).mean()

    fig = go.Figure()
    
    # 캔들스틱 차트 추가
    fig.add_trace(go.Candlestick(x=hist.index,
                                 open=hist['Open'],
                                 high=hist['High'],
                                 low=hist['Low'],
                                 close=hist['Close'],
                                 name='캔들스틱'))
    
    # MA20 추가
    fig.add_trace(go.Scatter(x=hist.index, y=hist['MA20'], 
                             line=dict(color='orange', width=1.5), 
                             name='MA20'))
    
    # MA60 추가
    fig.add_trace(go.Scatter(x=hist.index, y=hist['MA60'], 
                             line=dict(color='blue', width=1.5), 
                             name='MA60'))

    fig.update_layout(title="인터랙티브 주가 차트",
                      yaxis_title="가격",
                      xaxis_rangeslider_visible=False,
                      template="plotly_white",
                      height=600,
                      margin=dict(l=0, r=0, t=40, b=0))
    
    st.plotly_chart(fig, use_container_width=True)

def generate_ai_report(api_key, ticker_symbol, info, hist, financials):
    """
    Gemini API를 활용해 종합 리포트를 생성합니다.
    """
    if not api_key:
        return
        
    try:
        genai.configure(api_key=api_key)
        # 최신 모델 사용
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # 데이터 요약
        hist_summary = hist.tail(5).to_string() if (hist is not None and not hist.empty) else "주가 데이터 없음"
        fin_summary = financials.iloc[:, :2].to_string() if (financials is not None and not financials.empty) else "재무 데이터 없음"
        
        prompt = f"""
        당신은 전문 금융 데이터 분석가입니다. 다음은 {ticker_symbol} 주식에 대한 데이터입니다.
        
        [회사 개요]
        이름: {info.get('longName', '해당 없음')}
        섹터: {info.get('sector', '해당 없음')}
        산업: {info.get('industry', '해당 없음')}
        
        [최근 주가 흐름 (최근 5주기)]
        {hist_summary}
        
        [주요 재무 데이터 (최근 2기)]
        {fin_summary}
        
        위 데이터를 바탕으로 다음 두 가지 항목을 포함하는 종합 분석 리포트를 작성해 주세요:
        1. 정량적 분석 (주가 추세, 이동평균선 흐름, 재무 건전성 등 수치 기반 성능 평가)
        2. 정성적 분석 (해당 산업 내 주요 위치, 시장 환경, 향후 전망, 기회 및 리스크 요인)
        
        마크다운 형식을 사용하여 전문적이고 가독성 좋게 작성해 주세요.
        """
        
        with st.spinner("Gemini AI가 리포트를 생성 중입니다. 잠시만 기다려주세요..."):
            response = model.generate_content(prompt)
            st.markdown(response.text)
            
    except Exception as e:
        st.error(f"AI 리포트 생성 중 오류가 발생했습니다: {e}")

def main():
    st.title("📈 실시간 금융 데이터 & AI 분석 대시보드")
    st.markdown("티커를 검색하여 주가 차트, 재무제표를 확인하고 Gemini AI의 분석 리포트를 받아보세요.")
    st.divider()

    # Sidebar 구성
    st.sidebar.header("🔍 검색 및 설정")
    with st.sidebar.form(key="search_form"):
        ticker_symbol = st.text_input("종목 티커 (Ticker)", value="AAPL").upper()
        period = st.selectbox("기간 설정", ("1mo", "6mo", "1y", "5y"), index=2)
        interval = st.selectbox("간격 설정", ("1d", "1wk", "1mo"), index=0)
        submit_button = st.form_submit_button(label="검색 🔍")
    
    st.sidebar.divider()
    
    st.sidebar.header("🤖 AI 분석 설정")
    api_key = st.sidebar.text_input("Gemini API Key", type="password", help="AI 분석 기능을 사용하기 위해 필요합니다.")
    
    if submit_button and ticker_symbol:
        ticker, hist, info, financials, balance_sheet = load_data(ticker_symbol, period, interval)
        
        if info is not None:
            # Section 1: 회사 개요
            name = info.get('shortName') or info.get('longName', ticker_symbol)
            st.header(f"🏢 {name} ({ticker_symbol})")
            
            # 환율 정보 가져오기
            exchange_rate = get_exchange_rate()
            if ticker_symbol.endswith(".KS") or ticker_symbol.endswith(".KQ"):
                # 한국 주식일 경우 환율 적용 안함 (yfinance에서 KRW로 반환될 가능성 높음)
                exchange_rate = 1.0
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric(label="산업 (Industry)", value=info.get("industry", "N/A"))
            
            with col2:
                current_price = info.get("currentPrice", info.get("regularMarketPrice", 0))
                previous_close = info.get("previousClose", 0)
                change = current_price - previous_close
                change_pct = (change / previous_close * 100) if previous_close else 0
                
                # 원화 환산 가격 계산
                krw_price = current_price * exchange_rate
                
                # 표시 형식 (달러 또는 원화 기호)
                currency_symbol = "₩" if exchange_rate == 1.0 else "$"
                krw_str = "" if exchange_rate == 1.0 else f" (약 ₩{int(krw_price):,})"

                st.metric(
                    label="현재 주가", 
                    value=f"{currency_symbol}{current_price:,.2f}{krw_str}", 
                    delta=f"{change:,.2f} ({change_pct:.2f}%)"
                )
                
            with col3:
                market_cap = info.get("marketCap", 0)
                if market_cap:
                    # 원화 환산 시가총액
                    krw_cap = market_cap * exchange_rate
                    # 1조 단위로 표시
                    krw_cap_trillion = krw_cap / 1e12
                    
                    cap_str = f"₩{market_cap / 1e12:,.2f}T" if exchange_rate == 1.0 else f"${market_cap / 1e9:,.2f}B (약 ₩{krw_cap_trillion:,.1f}조)"
                else:
                    cap_str = "N/A"
                    
                st.metric(label="시가총액", value=cap_str)
                
            with col4:
                pe_ratio = info.get("trailingPE", "N/A")
                if isinstance(pe_ratio, float):
                     pe_ratio = f"{pe_ratio:.2f}"
                st.metric(label="P/E Ratio", value=pe_ratio)
            
            st.divider()
            
            # Section 2: 인터랙티브 차트
            st.subheader("📊 주가 차트")
            plot_candlestick(hist)
            
            st.divider()
            
            # Section 3: 재무정보
            st.subheader("📑 재무정보")
            tab1, tab2 = st.tabs(["손익계산서 (Income Statement)", "대차대조표 (Balance Sheet)"])
            
            with tab1:
                if financials is not None and not financials.empty:
                    # 손익계산서 한글 번역 매핑
                    fin_translation = {
                        "Total Revenue": "총 매출",
                        "Operating Revenue": "영업 수익",
                        "Cost Of Revenue": "매출 원가",
                        "Gross Profit": "매출 총이익",
                        "Operating Expense": "영업 비용",
                        "Operating Income": "영업 이익",
                        "Net Income": "순이익",
                        "Net Income Common Stockholders": "보통주 순이익",
                        "Basic EPS": "기본 주당순이익(EPS)",
                        "Diluted EPS": "희석 주당순이익",
                        "EBITDA": "상각전 영업이익(EBITDA)",
                        "Research And Development": "연구개발비",
                        "Selling General And Administration": "판매비와 관리비",
                        "Tax Provision": "법인세 비용",
                        "Pretax Income": "세전 이익",
                        "Interest Expense": "이자 비용",
                        "Interest Income": "이자 수익",
                        "Net Non Operating Interest Income Expense": "영업외 순이자 손익",
                        "Other Income Expense": "기타 손익",
                        "EBIT": "영업이익(EBIT)",
                        "Reconciled Cost Of Revenue": "조정 매출 원가",
                        "Reconciled Depreciation": "조정 감가상각비",
                        "Net Income From Continuing Operation Net Minority Interest": "소수주주지분 제외 계속영업순이익",
                        "Normalized Income": "정상 순이익"
                    }
                    fin_translated = financials.rename(index=fin_translation)
                    st.dataframe(fin_translated, use_container_width=True)
                else:
                    st.info("해당 종목의 손익계산서 데이터가 없습니다.")
                    
            with tab2:
                if balance_sheet is not None and not balance_sheet.empty:
                    # 대차대조표 한글 번역 매핑
                    bs_translation = {
                        "Total Assets": "자산 총계",
                        "Current Assets": "유동 자산",
                        "Cash And Cash Equivalents": "현금 및 현금성 자산",
                        "Inventory": "재고자산",
                        "Total Liabilities Net Minority Interest": "부채 총계",
                        "Current Liabilities": "유동 부채",
                        "Total Equity Gross Minority Interest": "자본 총계",
                        "Stockholders Equity": "주주 자본",
                        "Retained Earnings": "이익잉여금",
                        "Working Capital": "운전자본",
                        "Total Debt": "총 부채",
                        "Net Debt": "순 부채"
                    }
                    bs_translated = balance_sheet.rename(index=bs_translation)
                    st.dataframe(bs_translated, use_container_width=True)
                else:
                    st.info("해당 종목의 대차대조표 데이터가 없습니다.")
                    
            st.divider()
            
            # Section 4: Gemini AI 분석 (API 키 입력 시 활성화)
            st.subheader("🤖 Gemini 종합 분석 리포트")
            if api_key:
                if st.button("AI 리포트 생성하기", type="primary"):
                    generate_ai_report(api_key, ticker_symbol, info, hist, financials)
            else:
                st.info("👈 사이드바에 Gemini API Key를 입력하시면, AI가 작성한 심층 분석 리포트를 받아보실 수 있습니다.")

if __name__ == "__main__":
    main()
