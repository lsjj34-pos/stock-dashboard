import streamlit as st
from yahooquery import Ticker as YQTicker
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import google.generativeai as genai
import requests
import urllib.request
import json
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

# Streamlit 페이지 설정
st.set_page_config(page_title="증권 대시보드(개인용)", page_icon="📈", layout="wide")

# Yahoo Finance에 웹 브라우저처럼 보이게 하기 위한 User-Agent 설정
session = cffi_requests.Session(impersonate="chrome110")

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

@st.cache_data(ttl=3600)
def load_data(ticker_symbol, period, interval):
    """
    yfinance를 통해 주가 데이터와 재무제표 데이터를 수집합니다.
    """
    try:
        # yfinance로부터 역사 주가 먼저 가져오기 (yahooquery보다 안정적일 때가 많음)
        yf_ticker = yf.Ticker(ticker_symbol, session=session)
        
        # 주가 역사 데이터
        hist = yf_ticker.history(period=period, interval=interval)
        if isinstance(hist, pd.DataFrame):
            hist = hist.reset_index()
            if 'date' in hist.columns:
                hist.set_index('date', inplace=True)
            elif 'Date' in hist.columns:
                hist.set_index('Date', inplace=True)
            hist.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
        else:
            hist = None
            
        # 기본 정보 - 우선 yfinance (안정적) 시도, 없으면 yahooquery로 보완
        info = {}
        try:
            yf_info = yf_ticker.info
            info['shortName'] = yf_info.get('shortName')
            info['longName'] = yf_info.get('longName')
            info['industry'] = yf_info.get('industry')
            info['sector'] = yf_info.get('sector')
            info['currentPrice'] = yf_info.get('currentPrice', yf_info.get('regularMarketPrice'))
            info['previousClose'] = yf_info.get('previousClose')
            info['marketCap'] = yf_info.get('marketCap')
            info['trailingPE'] = yf_info.get('trailingPE')
            
            # yfinance에서 찾지 못한 필수 정보가 있다면 yahooquery 호출
            if not info['currentPrice']:
                raise ValueError("yfinance failed to fetch current price")
        except Exception as e_yf:
            # yfinance가 실패했을 때 yahooquery로 폴백 (Fallback)
            try:
                yq_ticker = YQTicker(ticker_symbol, asynchronous=False)
                target_sym = ticker_symbol
                detail_res = yq_ticker.summary_detail
                profile_res = yq_ticker.asset_profile
                price_res = yq_ticker.price
                
                # 만약 API 응답이 에러 문자열 형태라면
                if isinstance(price_res, dict) and isinstance(price_res.get(target_sym), str):
                    err_msg = price_res.get(target_sym)
                    if "Crumb" in err_msg or "Rate" in err_msg:
                        raise ValueError(f"Yahoo Server Blocked (Rate Limit or Crumb): {err_msg}")
                    raise ValueError(f"Yahoo Finance API 에러: {err_msg}")
                if isinstance(detail_res, dict) and isinstance(detail_res.get(target_sym), str):
                    raise ValueError(f"Yahoo Finance API 에러: {detail_res.get(target_sym)}")
                    
                detail = detail_res.get(target_sym, {}) if isinstance(detail_res, dict) and isinstance(detail_res.get(target_sym), dict) else {}
                profile = profile_res.get(target_sym, {}) if isinstance(profile_res, dict) and isinstance(profile_res.get(target_sym), dict) else {}
                price = price_res.get(target_sym, {}) if isinstance(price_res, dict) and isinstance(price_res.get(target_sym), dict) else {}
                
                # 완전 빈 데이터라면 잘못된 티커일 수 있음
                if not detail and not profile and not price:
                    raise ValueError("해당 티커에 대한 재무/주가 데이터를 찾을 수 없습니다.")
                
                info['shortName'] = price.get('shortName')
                info['longName'] = price.get('longName')
                info['industry'] = profile.get('industry')
                info['sector'] = profile.get('sector')
                info['currentPrice'] = price.get('regularMarketPrice')
                info['previousClose'] = detail.get('previousClose')
                info['marketCap'] = detail.get('marketCap')
                info['trailingPE'] = detail.get('trailingPE')
                
                # yahooquery에서도 현재가를 가져오지 못했다면 최후의 수단으로 직접 API 호츌
                if not info.get('currentPrice'):
                    raise ValueError("yahooquery failed to fetch current price")
            except Exception as e_yq:
                # 둘 다 완전히 실패했을 경우, 세 번째 최후의 수단 (직접 Request)
                try:
                    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{ticker_symbol}'
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req) as response:
                        chart_data = json.loads(response.read().decode())
                        result = chart_data.get('chart', {}).get('result', [])
                        if result:
                            meta = result[0].get('meta', {})
                            info['currentPrice'] = meta.get('regularMarketPrice')
                            info['previousClose'] = meta.get('chartPreviousClose')
                            info['shortName'] = ticker_symbol
                            
                            if not info.get('currentPrice'):
                                raise ValueError("직접 호출로도 가격을 가져오지 못했습니다.")
                        else:
                            raise ValueError("차트 API 결과가 비어있습니다.")
                except Exception as e_direct:
                    raise ValueError(f"데이터를 가져올 수 없습니다. IP Rate Limit 혹은 일시적 차단 상태입니다.\n(yfinance: {str(e_yf)} / yahooquery: {str(e_yq)} / direct: {str(e_direct)})")
        
        # 재무제표 (Transposed for display) - yfinance 사용
        try:
            financials = yf_ticker.income_stmt
            if isinstance(financials, pd.DataFrame):
                financials = financials.T
            else:
                financials = None
                
            balance_sheet = yf_ticker.balance_sheet
            if isinstance(balance_sheet, pd.DataFrame):
                balance_sheet = balance_sheet.T
            else:
                balance_sheet = None
        except Exception:
            # yfinance 실패 시 빈 데이터 반환
            financials = None
            balance_sheet = None
            
        return hist, info, financials, balance_sheet
    except Exception as e:
        st.error(f"데이터를 불러오는 중 오류가 발생했습니다: {e}")
        return None, None, None, None

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
            
            # 응답 유효성 검증
            try:
                report_content = response.text
                if not report_content:
                    st.error("생성된 리포트 내용이 비어있습니다.")
                    return None
            except ValueError:
                # 안전 검열(Safety filters) 등에 걸려 텍스트가 반환되지 않는 경우
                st.error("AI가 안전 기준에 의해 응답을 생성하지 못했습니다. (프롬프트나 데이터 확인 필요)")
                return None
            
            return report_content
            
    except Exception as e:
        # 오류가 발생했을 때 사용자에게 명확히 보일 수 있도록 구체적인 에러 메시지 출력
        st.error(f"❌ AI 리포트 생성 실패: {str(e)}")
        st.info("API Key가 정확한지, 혹은 할당량(Quota)을 초과하지 않았는지 확인해 주세요.")
        return None

def main():
    st.title("📈 정준's AI증권 대시보드")
    st.markdown("티커를 검색하여 주가 차트, 재무제표를 확인하고 Gemini AI의 분석 리포트를 받아보세요.")
    st.divider()

    # Sidebar 구성
    st.sidebar.header("🔍 검색 및 설정")
    with st.sidebar.form(key="search_form"):
        ticker_input = st.text_input("종목 티커 (Ticker)", value="AAPL").upper()
        period_input = st.selectbox("기간 설정", ("1mo", "6mo", "1y", "5y"), index=2)
        interval_input = st.selectbox("간격 설정", ("1d", "1wk", "1mo"), index=0)
        submit_button = st.form_submit_button(label="검색 🔍")

    st.sidebar.divider()
    
    st.sidebar.header("🤖 AI 분석 설정")
    api_key = st.sidebar.text_input(
        "Gemini API Key", 
        value="", # 보안을 위해 코드가 아닌 앱 화면에서 직접 입력하시는 것을 권장합니다.
        type="password", 
        help="AI 분석 기능을 사용하기 위해 필요합니다."
    )

    # 1. 검색 버튼을 누르면 세션 상태에 검색어와 설정값을 저장합니다.
    if submit_button and ticker_input:
        st.session_state['search_active'] = True
        st.session_state['ticker'] = ticker_input
        st.session_state['period'] = period_input
        st.session_state['interval'] = interval_input
        st.session_state['ai_report'] = None # 새 검색 시 기존 리포트 초기화

    # 2. 검색 기록이 세션에 남아있을 때만 화면에 데이터를 뿌려줍니다. (리포트 버튼을 눌러도 유지됨)
    if st.session_state.get('search_active'):
        ticker_symbol = st.session_state['ticker']
        period = st.session_state['period']
        interval = st.session_state['interval']

        hist, info, financials, balance_sheet = load_data(ticker_symbol, period, interval)
        
        if info is not None:
            # Section 1: 회사 개요
            name = info.get('shortName') or info.get('longName', ticker_symbol)
            st.header(f"🏢 {name} ({ticker_symbol})")
            
            exchange_rate = get_exchange_rate()
            if ticker_symbol.endswith(".KS") or ticker_symbol.endswith(".KQ"):
                exchange_rate = 1.0
            
            st.markdown("""
                <style>
                [data-testid="stMetricValue"] {
                    white-space: normal; word-break: keep-all; font-size: 1.6rem; line-height: 1.2;
                }
                </style>
                """, unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.metric(label="산업 (Industry)", value=info.get("industry", "N/A"))
            
            with col2:
                def to_float(val):
                    try: return float(val) if val is not None else 0.0
                    except: return 0.0

                current_price = to_float(info.get("currentPrice", info.get("regularMarketPrice", 0)))
                previous_close = to_float(info.get("previousClose", 0))
                
                change = current_price - previous_close
                change_pct = (change / previous_close * 100) if previous_close else 0
                krw_price = current_price * exchange_rate
                
                currency_symbol = "₩" if exchange_rate == 1.0 else "$"
                krw_str = "" if exchange_rate == 1.0 else f" (약 ₩{int(krw_price):,})"

                st.metric(label="현재 주가", value=f"{currency_symbol}{current_price:,.2f}{krw_str}", delta=f"{change:,.2f} ({change_pct:.2f}%)")
            
            st.write("")
            col3, col4 = st.columns(2)
                
            with col3:
                market_cap = info.get("marketCap", 0)
                if market_cap:
                    krw_cap = market_cap * exchange_rate
                    krw_cap_trillion = krw_cap / 1e12
                    cap_str = f"₩{market_cap / 1e12:,.2f}T" if exchange_rate == 1.0 else f"${market_cap / 1e9:,.2f}B (약 ₩{krw_cap_trillion:,.1f}조)"
                else:
                    cap_str = "N/A"
                st.metric(label="시가총액", value=cap_str)
                
            with col4:
                pe_ratio = info.get("trailingPE", "N/A")
                if isinstance(pe_ratio, float): pe_ratio = f"{pe_ratio:.2f}"
                st.metric(label="P/E Ratio", value=pe_ratio)
            
            st.divider()
            
            # Section 2: 인터랙티브 차트
            st.subheader("📊 주가 차트")
            plot_candlestick(hist)
            
            st.divider()
            
            # Section 3: 재무정보 (기존과 동일하므로 생략 없이 사용)
            st.subheader("📑 재무정보")
            tab1, tab2 = st.tabs(["손익계산서", "대차대조표"])
            
            with tab1:
                if financials is not None and not financials.empty:
                    st.dataframe(financials, use_container_width=True)
                else:
                    st.info("해당 종목의 손익계산서 데이터가 없습니다.")
                    
            with tab2:
                if balance_sheet is not None and not balance_sheet.empty:
                    st.dataframe(balance_sheet, use_container_width=True)
                else:
                    st.info("해당 종목의 대차대조표 데이터가 없습니다.")
                    
            st.divider()
            
            # Section 4: Gemini AI 분석
            st.subheader("🤖 Gemini 종합 분석 리포트")
            if api_key:
                # 버튼을 누르면 리포트를 생성하고 세션에 저장
                if st.button("AI 리포트 생성하기", type="primary"):
                    report = generate_ai_report(api_key, ticker_symbol, info, hist, financials)
                    if report is not None:
                        st.session_state['ai_report'] = report
                    else:
                        st.session_state['ai_report'] = "생성실패" 
                
                # 세션에 리포트가 있으면 출력 (화면이 새로고침 되어도 유지됨)
                current_report = st.session_state.get('ai_report')
                if current_report and current_report != "생성실패":
                    with st.expander("리포트 결과 보기", expanded=True):
                        st.markdown(current_report)
            else:
                st.info("👈 좌측 메뉴에 새로 발급받은 Gemini API Key를 입력해주세요.")

if __name__ == "__main__":
    main()
