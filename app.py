"""
레인필드 계약서 도구 (contract-tools)
------------------------------------
계약서 관련 자동화 두 가지를 한 앱에서 씁니다. 왼쪽 메뉴에서 골라 들어갑니다.

  📄 계약서·제안서(IM) 비교   → views/compare.py
      계약서와 증권사·은행이 보낸 제안서(IM)를 대조해,
      계약서 기준으로 제안서를 어떻게 고쳐야 하는지 정리합니다.

  🔎 계약서 항목 찾기         → views/scan.py
      구글 시트에 정리해 둔 검토 항목을 계약서에서 찾아
      원본 페이지에 형광펜으로 표시합니다.

두 화면은 서로 영향을 주지 않습니다(올린 파일·결과를 따로 보관).

실행 방법 (터미널):
    streamlit run app.py
"""

import streamlit as st

from utils.auth import require_password

st.set_page_config(page_title="레인필드 계약서 도구", layout="wide")

# 🔒 비밀번호 확인 (지금은 통합 대시보드에서만 접근을 통제하므로 그냥 통과)
require_password()

# 왼쪽 메뉴 꾸미기
st.markdown(
    """
    <style>
    [data-testid="stSidebarNav"] ul { padding-top: 4px; }
    [data-testid="stSidebarNav"] a { font-size: 15px; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)

pages = [
    st.Page("views/compare.py", title="계약서·IM 비교", icon="📄", default=True),
    st.Page("views/scan.py", title="계약서 항목 찾기", icon="🔎"),
]

with st.sidebar:
    st.markdown("### 레인필드 계약서 도구")
    st.caption("아래에서 할 일을 골라주세요.")

nav = st.navigation(pages)

with st.sidebar:
    st.divider()
    st.caption(
        "**📄 계약서·IM 비교** — 계약서와 제안서(IM)를 나란히 대조해 "
        "다른 부분과 고칠 방향을 정리합니다. (문서 2개 필요)\n\n"
        "**🔎 계약서 항목 찾기** — 구글 시트에 적어둔 검토 항목을 계약서에서 찾아 "
        "원본에 형광펜으로 보여줍니다. (계약서 1개면 됨)"
    )

nav.run()
