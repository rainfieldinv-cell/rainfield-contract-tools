"""
레인필드 계약서 도구 (contract-tools)
------------------------------------
처음 화면에서 버튼 두 개 중 하나를 골라 들어갑니다. (왼쪽 메뉴 없음)

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

import runpy

import streamlit as st

from utils.auth import require_password

st.set_page_config(
    page_title="레인필드 계약서 도구",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 🔒 비밀번호 확인 (지금은 통합 대시보드에서만 접근을 통제하므로 그냥 통과)
require_password()

# 왼쪽 사이드바는 쓰지 않으므로 아예 감춤
st.markdown(
    """
    <style>
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display: none !important; }
    .home-hero { text-align:center; padding: 6px 0 2px; }
    .home-hero h1 { margin-bottom: 6px; }
    .home-hero p { color:#666; font-size:15px; margin-top:0; }
    .tool-card { text-align:center; padding: 6px 4px 2px; }
    .tool-card .emoji { font-size: 46px; line-height: 1.1; }
    .tool-card .name { font-size: 20px; font-weight: 700; color:#1A2B5E; margin-top: 6px; }
    .tool-card .desc { color:#555; font-size: 14px; margin: 10px 0 4px; min-height: 66px; }
    .tool-card .need { color:#888; font-size: 13px; margin-bottom: 10px; }
    </style>
    """,
    unsafe_allow_html=True,
)

TOOLS = {
    "compare": {
        "emoji": "📄",
        "name": "계약서 · IM 비교",
        "desc": "계약서와 제안서(IM)를 나란히 대조해 <b>다른 부분</b>을 찾고, "
                "계약서 기준으로 제안서를 어떻게 고쳐야 하는지 정리합니다.",
        "need": "필요한 파일 : 계약서 1개 + 제안서(IM) 1개",
        "file": "views/compare.py",
    },
    "scan": {
        "emoji": "🔎",
        "name": "계약서 항목 찾기",
        "desc": "구글 시트에 적어둔 검토 항목을 계약서에서 찾아, "
                "<b>원본 페이지에 형광펜</b>으로 어디에 있는지 보여줍니다.",
        "need": "필요한 파일 : 계약서 1개",
        "file": "views/scan.py",
    },
}


def open_tool(key: str):
    st.session_state["tool"] = key


def go_home():
    st.session_state["tool"] = None


def render_home():
    """처음 화면 — 버튼 두 개 중 하나를 고릅니다."""
    st.markdown(
        '<div class="home-hero"><h1>레인필드 계약서 도구</h1>'
        "<p>무엇을 할지 아래에서 골라주세요.</p></div>",
        unsafe_allow_html=True,
    )
    st.write("")

    _l, mid, _r = st.columns([0.5, 3, 0.5])
    with mid:
        cols = st.columns(2, gap="large")
        for col, (key, t) in zip(cols, TOOLS.items()):
            with col:
                with st.container(border=True):
                    st.markdown(
                        f'<div class="tool-card">'
                        f'<div class="emoji">{t["emoji"]}</div>'
                        f'<div class="name">{t["name"]}</div>'
                        f'<div class="desc">{t["desc"]}</div>'
                        f'<div class="need">{t["need"]}</div>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    st.button(
                        f'{t["emoji"]}  {t["name"]} 시작하기',
                        key=f"open_{key}", type="primary",
                        use_container_width=True,
                        on_click=open_tool, args=(key,),
                    )

        st.write("")
        st.caption(
            "⚠️ 두 기능의 결과는 **법적 판단이 아니라 검토 보조용**입니다. "
            "중요한 결정은 반드시 담당자가 원본 문서를 직접 확인하세요."
        )


def render_tool(key: str):
    """고른 도구 화면을 그립니다. 맨 위에 처음으로 돌아가는 버튼."""
    back, title = st.columns([0.16, 0.84], vertical_alignment="center")
    back.button("◀ 처음 화면", key="go_home", on_click=go_home,
                use_container_width=True)
    other = "scan" if key == "compare" else "compare"
    title.button(
        f'{TOOLS[other]["emoji"]}  {TOOLS[other]["name"]} 로 바로 가기',
        key=f"switch_{other}", on_click=open_tool, args=(other,),
    )
    st.divider()
    runpy.run_path(TOOLS[key]["file"], run_name="__main__")


tool = st.session_state.get("tool")
if tool in TOOLS:
    render_tool(tool)
else:
    render_home()
