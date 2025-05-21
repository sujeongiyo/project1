# -*- coding: utf-8 -*-
import streamlit as st
import urllib.request
import urllib.parse
import json
import pandas as pd
from datetime import datetime
import sqlite3
import os

# 페이지 설정
st.set_page_config(
    page_title="네이버 블로그 리뷰 분석 시스템",
    page_icon="📊",
    layout="wide"
)

# NaverApiClient 클래스 정의
class NaverApiClient:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = "https://openapi.naver.com/v1/search/"
   
    def get_data(self, media, count, query, start=1, sort="date"):
        """
        네이버 API에서 데이터를 가져오는 메소드
        """
        encText = urllib.parse.quote(query)
        url = f"{self.base_url}{media}?sort={sort}&display={count}&start={start}&query={encText}"
       
        request = urllib.request.Request(url)
        request.add_header("X-Naver-Client-Id", self.client_id)
        request.add_header("X-Naver-Client-Secret", self.client_secret)
       
        try:
            response = urllib.request.urlopen(request)
            rescode = response.getcode()
           
            if(rescode==200):
                response_body = response.read()
                result = response_body.decode('utf-8')
                return result
            else:
                st.error(f"Error Code: {rescode}")
                return None
        except Exception as e:
            st.error(f"Exception occurred: {e}")
            return None
   
    def get_blog(self, query, count=10, start=1, sort="date"):
        """블로그 검색 결과를 가져오는 편의 메소드"""
        return self.get_data("blog", count, query, start, sort)
   
    def parse_json(self, data):
        """API 응답을 JSON으로 파싱하는 메소드"""
        if data:
            return json.loads(data)
        return None

# 데이터베이스 초기화 및 연결 함수
def init_db():
    # 데이터베이스 디렉토리 확인 및 생성
    db_dir = os.path.join(os.getcwd(), "data")
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
   
    db_path = os.path.join(db_dir, "reviews.db")
   
    # 데이터베이스 연결
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
   
    # 테이블 생성 (없는 경우)
    c.execute('''
    CREATE TABLE IF NOT EXISTS blog_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        link TEXT,
        blogger_name TEXT,
        post_date TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
   
    # 분석 결과 테이블 생성
    c.execute('''
    CREATE TABLE IF NOT EXISTS analysis_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        positive_opinions TEXT,
        negative_opinions TEXT,
        summary TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
   
    conn.commit()
    return conn, c

# 블로그 데이터를 DB에 저장하는 함수
def save_blog_data_to_db(conn, cursor, blog_data, product_name):
    if not blog_data or "items" not in blog_data or not blog_data["items"]:
        st.warning("처리할 블로그 데이터가 없습니다.")
        return 0
   
    # 기존 데이터 삭제 (같은 제품명으로 검색한 경우)
    cursor.execute("DELETE FROM blog_posts WHERE product_name = ?", (product_name,))
   
    # 새 데이터 삽입
    count = 0
    for item in blog_data["items"]:
        # HTML 태그 제거
        title = item["title"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"')
        description = item["description"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"')
       
        cursor.execute('''
        INSERT INTO blog_posts (product_name, title, description, link, blogger_name, post_date)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            product_name,
            title,
            description,
            item.get("link", ""),
            item.get("bloggername", ""),
            item.get("postdate", "")
        ))
        count += 1
   
    conn.commit()
    st.success(f"{count}개의 블로그 포스트가 데이터베이스에 저장되었습니다.")
    return count

# 데이터베이스에서 블로그 포스트 가져오기
def get_blog_posts(cursor, product_name, limit=50):
    cursor.execute("""
    SELECT title, description, blogger_name, post_date, link
    FROM blog_posts
    WHERE product_name = ?
    LIMIT ?
    """, (product_name, limit))
   
    return cursor.fetchall()

# 분석 결과를 데이터베이스에 저장
def save_analysis_result(conn, cursor, product_name, positive, negative, summary):
    # 기존 분석 삭제 (같은 제품명인 경우)
    cursor.execute("DELETE FROM analysis_results WHERE product_name = ?", (product_name,))
   
    # 새 분석 결과 저장
    cursor.execute('''
    INSERT INTO analysis_results (product_name, positive_opinions, negative_opinions, summary)
    VALUES (?, ?, ?, ?)
    ''', (product_name, positive, negative, summary))
   
    conn.commit()

# 데이터베이스에서 분석 결과 가져오기
def get_analysis_result(cursor, product_name):
    cursor.execute("""
    SELECT positive_opinions, negative_opinions, summary
    FROM analysis_results
    WHERE product_name = ?
    """, (product_name,))
   
    return cursor.fetchone()

# ChatGPT API를 사용한 리뷰 분석 함수
def analyze_reviews(api_key, reviews_text, product_name):
    if not api_key:
        st.error("OpenAI API 키가 필요합니다.")
        return None, None, None
   
    try:
        # OpenAI 모듈 가져오기
        import openai
       
        # API 키 설정
        openai.api_key = api_key
       
        # 리뷰 텍스트가 너무 긴 경우 줄이기
        max_chars = 15000
        if len(reviews_text) > max_chars:
            st.warning(f"리뷰 텍스트가 너무 깁니다. 처음 {max_chars} 문자만 분석합니다.")
            reviews_text = reviews_text[:max_chars] + "... (이하 생략)"
       
        # 리뷰 분석을 위한 프롬프트
        prompt = f"""
다음은 '{product_name}'에 대한 네이버 블로그 포스트입니다. 이 내용을 분석하여 아래 세 가지 결과를 제공해주세요:
1. 긍정적 의견 (5-7줄로 요약)
2. 부정적 의견 (5-7줄로 요약)
3. 전체 요약 및 총평 (5-7줄로 요약)

블로그 내용:
{reviews_text}

응답은 JSON 형식으로 제공하되  Markdown출력은 사용하지 말아주세요:
{{
  "ad_analysis": "광고성 콘텐츠 분석 결과 (광고성 콘텐츠 비율 추정치 포함)",
  "positive": "구체적인 긍정적 의견 요약 (실제 사용자 경험 중심)",
  "negative": "구체적인 부정적 의견 요약 (실제 사용자 경험 중심)",
  "summary": "객관적인 전체 요약 및 종합 평가"
}}

        # API 호출
        response = openai.ChatCompletion.create(
            model="gpt-40-mini",
            messages=[
                {"role": "system", "content": "당신은 제품 리뷰를 분석하는 전문가입니다. 제공된 네이버 블로그 포스트를 기반으로 긍정적 의견, 부정적 의견, 전체 요약을 명확하게 요약합니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=1000
        )
       
        # 결과 파싱
        result = json.loads(response.choices[0].message.content)
        return result["positive"], result["negative"], result["summary"]
   
    except Exception as e:
        st.error(f"ChatGPT API 호출 중 오류 발생: {str(e)}")
        return None, None, None

# 메인 애플리케이션 함수
def main():
    st.title("네이버 블로그 제품 리뷰 분석 시스템")
    st.markdown("---")
   
    # 사이드바 설정
    with st.sidebar:
        st.header("API 설정")
       
        # 네이버 API 설정
        st.subheader("네이버 검색 API")
        naver_client_id = st.text_input("Naver Client ID", value="9XhhxLV1IzDpTZagoBr1")
        naver_client_secret = st.text_input("Naver Client Secret", value="J14HFxv3B6", type="password")
       
        # OpenAI API 설정
        st.subheader("OpenAI API")
        openai_api_key = st.text_input("OpenAI API 키", type="password")
       
        st.markdown("---")
       
        # 데이터베이스 초기화 버튼
        st.subheader("데이터베이스 설정")
        reset_db_button = st.button("데이터베이스 초기화")
       
        if reset_db_button:
            # 데이터베이스 파일 삭제
            db_path = os.path.join(os.getcwd(), "data", "reviews.db")
            if os.path.exists(db_path):
                os.remove(db_path)
                st.success("데이터베이스가 초기화되었습니다.")
   
    # 데이터베이스 연결
    conn, cursor = init_db()
   
    # 네이버 API 클라이언트 생성
    naver_client = NaverApiClient(naver_client_id, naver_client_secret)
   
    # 제품명 입력 및 검색 설정
    st.subheader("제품 검색 및 분석")
   
    product_name = st.text_input("제품명 입력", "")
   
    col1, col2 = st.columns(2)
   
    with col1:
        count = st.slider("검색 결과 수", min_value=10, max_value=100, value=50)
   
    with col2:
        sort_options = st.selectbox(
            "정렬",
            options=[("최신순", "date"), ("정확도순", "sim")],
            format_func=lambda x: x[0]
        )
        sort_option = sort_options[1]
   
    # 검색 버튼
    search_button = st.button("검색", type="primary")
   
    if search_button and product_name:
        if not naver_client_id or not naver_client_secret:
            st.error("네이버 API 키가 필요합니다.")
        else:
            with st.spinner(f"'{product_name}'에 대한 네이버 블로그 검색 중..."):
                # 네이버 블로그 검색
                data = naver_client.get_blog(product_name, count, sort=sort_option)
                parsed_data = naver_client.parse_json(data)
               
                if parsed_data and "items" in parsed_data and parsed_data["items"]:
                    # 블로그 데이터를 DB에 저장
                    save_blog_data_to_db(conn, cursor, parsed_data, product_name)
                   
                    # 검색 결과 표시
                    st.subheader(f"검색 결과 (총 {parsed_data['total']}개 중 {len(parsed_data['items'])}개 표시)")
                   
                    # 결과를 데이터프레임으로 표시
                    df = pd.DataFrame(parsed_data["items"])
                   
                    # HTML 태그 제거
                    for col in ['title', 'description']:
                        if col in df.columns:
                            df[col] = df[col].str.replace('<b>', '').str.replace('</b>', '').str.replace('&quot;', '"')
                   
                    # 필요한 열만 선택하여 표시
                    display_cols = ['title', 'description', 'postdate', 'bloggername']
                    display_cols = [col for col in display_cols if col in df.columns]
                   
                    # 수정된 부분: use_column_width 대신 use_container_width 사용
                    st.dataframe(df[display_cols], use_container_width=True)
                else:
                    st.error("검색 결과가 없거나 오류가 발생했습니다.")
   
    # 분석 버튼
    if product_name:
        analyze_button = st.button("리뷰 분석")
       
        if analyze_button:
            if not openai_api_key:
                st.error("OpenAI API 키가 필요합니다.")
            else:
                # 먼저 기존 분석 결과가 있는지 확인
                existing_analysis = get_analysis_result(cursor, product_name)
               
                if existing_analysis:
                    # 기존 분석 결과 표시
                    positive, negative, summary = existing_analysis
                   
                    # 분석 결과 표시
                    st.subheader("기존 분석 결과")
                    col1, col2 = st.columns(2)
                   
                    with col1:
                        st.markdown("### 👍 긍정적 의견")
                        st.markdown(positive)
                   
                    with col2:
                        st.markdown("### 👎 부정적 의견")
                        st.markdown(negative)
                   
                    st.markdown("### 📋 전체 요약 및 총평")
                    st.markdown(summary)
                   
                    # 재분석 옵션
                    if st.button("재분석 실행"):
                        st.session_state.reanalyze = True
                   
                    if not st.session_state.get("reanalyze", False):
                        return
               
                with st.spinner("리뷰 데이터 분석 중..."):
                    # DB에서 블로그 포스트 가져오기
                    blog_posts = get_blog_posts(cursor, product_name)
                   
                    if blog_posts:
                        # 모든 블로그 포스트 내용 결합
                        all_posts_text = "\n\n".join([
                            f"제목: {post[0]}\n내용: {post[1]}\n작성자: {post[2]}\n날짜: {post[3]}"
                            for post in blog_posts
                        ])
                       
                        # ChatGPT로 리뷰 분석
                        positive, negative, summary = analyze_reviews(openai_api_key, all_posts_text, product_name)
                       
                        if positive and negative and summary:
                            # 분석 결과 DB에 저장
                            save_analysis_result(conn, cursor, product_name, positive, negative, summary)
                           
                            # 분석 결과 표시
                            st.subheader("리뷰 분석 결과")
                            col1, col2 = st.columns(2)
                           
                            with col1:
                                st.markdown("### 👍 긍정적 의견")
                                st.markdown(positive)
                           
                            with col2:
                                st.markdown("### 👎 부정적 의견")
                                st.markdown(negative)
                           
                            st.markdown("### 📋 전체 요약 및 총평")
                            st.markdown(summary)
                           
                            # 세션 상태 초기화
                            st.session_state.reanalyze = False
                        else:
                            st.error("리뷰 분석 중 오류가 발생했습니다.")
                    else:
                        st.warning(f"'{product_name}'에 대한 블로그 포스트가 없습니다. 먼저 검색을 실행해주세요.")
   
    # 데이터베이스 연결 종료
    conn.close()

# 애플리케이션 실행
if __name__ == "__main__":
    if "reanalyze" not in st.session_state:
        st.session_state.reanalyze = False
    main()
