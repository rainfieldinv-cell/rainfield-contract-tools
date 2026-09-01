"""
계약서 항목 찾기 (contract-scan)
--------------------------------
구글 시트에 계약서 종류별로 정리해 둔 '검토 키워드' 를 그대로 가져와서,
올린 계약서 한 개에서 내가 고른 키워드에 해당하는 내용을 찾아
원본 페이지 이미지에 형광펜으로 표시해 주는 도구입니다.

화면은 두 단계입니다.
  1단계 : 계약서 종류 고르고 계약서 올리기
  2단계 : 찾을 키워드 고르고 → 찾기 실행 → 결과 보기

실행 방법 (터미널):
    streamlit run app.py
"""

import os

import streamlit as st

from utils.keywords import load_keywords
from utils.loader import process_uploaded_documents
from utils.ocr import ocr_pdf_pages
from utils.render import render_page_image
from utils.scan import scan_contract

# 구글 시트(검토 키워드) 기본 주소 — secrets 의 keyword_sheet_url 로 덮어쓸 수 있음
DEFAULT_KEYWORD_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1CY--x7Z6mPUdCYfSN6Oh0qQuLLhGTm8ybz5hj_kyZUI/edit?usp=sharing"
)

STEPS = ["① 계약서 올리기", "② 키워드 고르고 찾기"]

# 시트에서 이 이름의 열은 '모든 계약서에 공통으로 보는 항목'으로 취급합니다.
COMMON_COLUMN = "공통"

# 결과 화면의 원본 이미지 크기(가로 픽셀). None 이면 화면 폭에 꽉 채움.
IMAGE_WIDTHS = {"작게": 420, "보통": 650, "크게": 900, "꽉 채우기": None}


# ─────────────────────────────────────────────
# 공통 도우미
# ─────────────────────────────────────────────
def get_api_key():
    """Anthropic(클로드) API 키 가져오기 (secrets.toml 또는 환경변수)."""
    try:
        key = st.secrets.get("anthropic_api_key", None)
    except Exception:
        key = None
    return key or os.environ.get("ANTHROPIC_API_KEY")


def _get_sheet_url() -> str:
    try:
        return st.secrets.get("keyword_sheet_url", DEFAULT_KEYWORD_SHEET_URL)
    except Exception:
        return DEFAULT_KEYWORD_SHEET_URL


@st.cache_data(ttl=120, show_spinner=False)
def load_keywords_cached(url: str) -> dict:
    """시트 내용을 2분간 기억해 둡니다(매번 다시 받지 않게)."""
    return load_keywords(url)


@st.cache_data(show_spinner=False)
def cached_page_image(pdf_path: str, page: int, highlight: str) -> bytes:
    """같은 페이지·같은 형광펜이면 이미지를 다시 만들지 않습니다."""
    return render_page_image(pdf_path, page, highlight_text=highlight)


def reset_all():
    """초기화: 올린 계약서와 찾은 결과를 모두 지웁니다."""
    for k in ["sc_contract", "scan_results", "scan_meta", "uploader_sc_contract"]:
        st.session_state.pop(k, None)
    st.session_state["step"] = STEPS[0]


def goto_step(index: int):
    """이전/다음 버튼 콜백."""
    st.session_state["step"] = STEPS[max(0, min(len(STEPS) - 1, index))]


def kw_key(contract_type: str, keyword: str) -> str:
    """키워드 체크박스의 이름표(계약서 종류마다 따로 기억)."""
    return f"kw::{contract_type}::{keyword}"


def set_all_keywords(contract_type: str, keywords: list, value: bool):
    """전체 선택 / 전체 해제 버튼."""
    for k in keywords:
        st.session_state[kw_key(contract_type, k)] = value


# ─────────────────────────────────────────────
# 화면 기본 설정
# ─────────────────────────────────────────────
st.title("계약서 항목 찾기")
st.caption(
    "구글 시트에 정리해 둔 검토 키워드로, 계약서에서 그 내용이 어디에 있는지 찾아 "
    "원본 페이지에 형광펜으로 보여줍니다."
)
st.warning(
    "⚠️ 이 도구의 결과는 **법적 판단이 아니라 검토 보조용**입니다. "
    "중요한 결정은 반드시 담당자가 원본 계약서를 직접 확인하세요."
)

# 라디오를 '탭 모양' 으로 보이게 (자금판·계약서 비교와 같은 남색 테마)
st.markdown(
    """
    <style>
    .st-key-bigtabs div[role="radiogroup"]{
        flex-direction:row; gap:4px; border-bottom:2px solid #e6e6e6;
    }
    .st-key-bigtabs div[role="radiogroup"] label{
        margin:0; padding:8px 18px; cursor:pointer; font-weight:600;
        color:#666; border-bottom:3px solid transparent;
    }
    .st-key-bigtabs div[role="radiogroup"] label>div:first-child{ display:none; }
    .st-key-bigtabs div[role="radiogroup"] label:has(input:checked){
        color:#1A2B5E; border-bottom:3px solid #1A2B5E;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# 검토 키워드 시트 읽기 (두 단계에서 모두 사용)
# ─────────────────────────────────────────────
sheet_url = _get_sheet_url()
sheet_data = {"all": [], "by_contract": {}}
sheet_error = None
try:
    sheet_data = load_keywords_cached(sheet_url)
except Exception as e:
    sheet_error = str(e)

if sheet_error:
    st.error(f"검토 키워드 시트를 읽지 못했습니다: {sheet_error}")
    st.caption(
        f"[시트 열기]({sheet_url}) → 공유를 '링크가 있는 모든 사용자 · 뷰어' 로 바꿔주세요."
    )
    st.stop()

contract_types = list(sheet_data["by_contract"].keys())
if not contract_types:
    st.info(
        f"시트에 아직 계약서가 없습니다. [시트 열기]({sheet_url}) 에서 "
        "맨 윗줄에 계약서 이름을, 그 아래 칸에 찾을 키워드를 한 줄에 하나씩 적어주세요."
    )
    st.stop()

# ── 처음 쓰는 사람을 위한 사용법 (접었다 폈다) ──
with st.expander("❓ 이 도구는 뭐 하는 건가요? (처음이면 열어보세요)"):
    st.markdown(
        """
**한 줄 요약** — 계약서를 올리면, 미리 정해둔 검토 항목이 그 계약서 **어디에 적혀 있는지** 찾아서
**원본 페이지에 형광펜을 칠해** 보여줍니다. 사람이 100페이지를 훑지 않아도 됩니다.

**쓰는 순서**

1. **① 계약서 올리기** — 어떤 종류의 계약서인지 고르고(대출약정서·담보신탁계약서 등),
   그 계약서 파일 **하나**를 올립니다. 보통은 **PDF 하나면 충분**합니다.
   단, 복사기로 스캔한(사진으로 된) PDF는 글자가 없어서 못 읽으니 그때는 워드를 올려주세요.
2. **② 키워드 고르고 찾기** — 그 계약서에서 찾을 항목(선행·후행·기한이익상실 …)을 체크로 고르고
   **찾기 실행** 을 누릅니다. 30초~1분쯤 걸립니다.
3. **결과** — 항목별로 계약서에 뭐라고 적혀 있는지, 몇 페이지인지, 그리고 원본 페이지 사진에
   그 문장이 노랗게 칠해져서 나옵니다. 확인한 항목은 오른쪽 네모에 체크해 두면 됩니다.

**찾을 항목(키워드)은 아래 구글 시트에서 관리합니다.** 새 계약서 종류를 추가하거나
찾을 항목을 늘리고 싶으면 시트만 고치면 됩니다 — 프로그램은 손댈 필요 없습니다.

**주의** — 결과는 사람이 확인하기 쉽게 정리해 주는 것일 뿐, 법적 판단이 아닙니다.
중요한 건 반드시 원본 계약서로 직접 확인하세요.
"""
    )

# ── 검토 키워드 시트 바로가기 (제목 바로 아래) ──
with st.container(border=True):
    link_col, refresh_col = st.columns([0.62, 0.38])
    link_col.link_button(
        "📋 검토 키워드 시트 열기 (새 창)", sheet_url, use_container_width=True,
    )
    if refresh_col.button("🔄 시트 새로고침", use_container_width=True, key="kw_refresh_top"):
        load_keywords_cached.clear()
        st.rerun()
    st.caption(
        "**찾을 항목은 저 시트에서 관리합니다.** 이 버튼을 누르면 시트가 새 창으로 열립니다. "
        "시트 맨 윗줄에 **계약서 이름**을, 그 아래 칸에 **찾을 키워드**를 한 줄에 하나씩 적으면 됩니다.\n\n"
        "① 시트 열기 → ② 키워드 고치거나 추가하고 저장 → ③ 이 화면으로 돌아와 "
        "**🔄 시트 새로고침** → ④ 찾기 실행. 앱은 손댈 필요 없습니다."
    )

# '공통' 열은 계약서 종류가 아니라 모든 계약서에 함께 보는 항목
common_items = sheet_data["by_contract"].get(COMMON_COLUMN, [])
selectable_types = [t for t in contract_types if t != COMMON_COLUMN] or contract_types

# 준비 상태 한 줄 안내
has_contract = "sc_contract" in st.session_state
st.caption(f"계약서 준비 상태 — {'✅ 올림' if has_contract else '⏳ 아직 안 올림'}")

# 단계 탭
st.session_state.setdefault("step", STEPS[0])
with st.container(key="bigtabs"):
    st.radio("단계 선택", STEPS, key="step", horizontal=True,
             label_visibility="collapsed")
step = st.session_state["step"]


# ─────────────────────────────────────────────
# 1단계: 계약서 종류 고르기 + 계약서 올리기
# ─────────────────────────────────────────────
def render_step1():
    st.header("계약서 종류 고르고 올리기")
    st.caption(
        "먼저 **어떤 종류의 계약서인지** 고르세요. 종류마다 찾을 항목이 다르기 때문입니다. "
        "그다음 그 계약서 파일을 올리면 됩니다."
    )

    st.selectbox(
        "어떤 계약서를 볼 건가요?",
        selectable_types,
        key="contract_type",
        help="구글 시트 맨 윗줄에 적어둔 계약서 이름들입니다. 시트에 추가하고 🔄 시트 새로고침을 누르면 여기에도 늘어납니다.",
    )

    contract_type = st.session_state["contract_type"]
    n_kw = len(sheet_data["by_contract"].get(contract_type, []))
    n_common = len(common_items)
    if n_kw or n_common:
        st.caption(
            f"**{contract_type}** 항목 **{n_kw}개**"
            + (f" + **{COMMON_COLUMN}** 항목 **{n_common}개**" if n_common else "")
            + " (다음 단계에서 고릅니다)"
        )
    else:
        st.caption(
            f"**{contract_type}** 는 시트에 아직 항목이 없습니다. "
            f"[시트 열기]({sheet_url}) 에서 그 칸 아래에 찾을 내용을 적고 🔄 새로고침을 눌러주세요."
        )

    st.divider()
    st.subheader("계약서 파일 올리기")
    st.error(
        "🚫 **스캔본(사진으로 된) PDF는 찾을 수 없습니다.**\n\n"
        "복사기로 스캔하거나 사진을 찍어 만든 PDF는 겉보기엔 글자 같아도 컴퓨터에는 "
        "**그림 한 장**일 뿐이라 내용을 읽지 못합니다.\n\n"
        "**내 PDF가 어느 쪽인지 1초에 확인하는 법** — PDF를 열어 본문 글자를 마우스로 **드래그**해 보세요. "
        "글자가 파랗게 선택되면 ✅ 그대로 올리면 됩니다. 아무것도 안 잡히고 사진처럼 끌리면 ❌ 스캔본입니다.\n\n"
        "스캔본밖에 없다면 **워드(.docx) 파일을 올려주세요.** 워드도 없다면 파일을 올린 뒤 화면에 나오는 "
        "**OCR로 글자 읽기** 버튼을 쓸 수 있지만, 이때는 형광펜이 칠해지지 않고 페이지 사진만 나옵니다."
    )
    st.caption(
        "계약서 파일 **하나**만 올려주세요. **글자가 살아있는 PDF가 가장 좋습니다** "
        "— 상대방이 보낸 원본 그대로의 페이지·모양으로 보여주기 때문입니다. "
        "워드를 올리면 PDF로 바꿔서 읽는데, 이때 페이지 번호가 원본 PDF와 다를 수 있고 "
        "글자가 겹쳐 보일 수 있습니다(찾는 정확도에는 영향이 없고, 보이는 모양만 그렇습니다)."
    )

    uploaded = st.file_uploader(
        "계약서 파일 (PDF 또는 워드)",
        type=["pdf", "docx", "doc", "pptx", "ppt"],
        accept_multiple_files=False,
        key="uploader_sc_contract",
        label_visibility="collapsed",
    )

    files = [uploaded] if uploaded else []
    if files:
        file_sig = "|".join(sorted(f"{f.name}-{f.size}" for f in files))
        saved = st.session_state.get("sc_contract")
        if not (saved and saved.get("_sig") == file_sig):
            st.session_state.pop("scan_results", None)  # 새 계약서면 이전 결과는 지움
            with st.spinner("계약서를 읽는 중..."):
                try:
                    result = process_uploaded_documents(files)
                    result["_sig"] = file_sig
                    st.session_state["sc_contract"] = result
                except Exception as e:
                    st.error(str(e))

    contract = st.session_state.get("sc_contract")
    if not contract:
        st.info("위에 계약서 파일을 올리면 다음 단계로 넘어갈 수 있습니다.")
        return

    pages = contract["pages"]
    total_pages = len(pages)
    total_chars = sum(len(p["text"]) for p in pages)
    st.success(f"읽기 완료: {contract['name']}")
    if contract.get("status"):
        st.caption(contract["status"])
    st.write(f"총 **{total_pages}페이지**, 글자 수 약 **{total_chars:,}자**")

    # 스캔(사진) PDF 대응 — 글자가 거의 없으면 OCR 버튼
    avg_chars = total_chars / total_pages if total_pages else 0
    if avg_chars < 20:
        st.warning(
            "글자가 거의 없습니다. **스캔(사진)으로 만든 PDF** 로 보입니다.\n\n"
            "**워드 파일이 있다면 그걸 올리는 게 가장 좋습니다.** 워드가 없다면 아래 버튼으로 "
            "클로드가 페이지 사진을 읽어 글자로 바꿀 수 있습니다(OCR). "
            f"단 OCR로 읽은 경우 페이지에 진짜 글자가 없어서 **형광펜은 칠해지지 않고** "
            f"페이지 사진만 나옵니다. ({total_pages}페이지 처리에 몇 분, 소액 과금이 있을 수 있어요.)"
        )
        if st.button("🔎 OCR로 글자 읽기"):
            api_key = get_api_key()
            if not api_key:
                st.error("Anthropic(클로드) API 키가 설정되지 않았습니다.")
            else:
                progress = st.progress(0.0, text="OCR 준비 중...")
                contract["pages"] = ocr_pdf_pages(
                    contract["pdf_path"], api_key,
                    progress_callback=lambda d, t: progress.progress(
                        d / t, text=f"OCR 진행 중... {d}/{t} 페이지"
                    ),
                )
                st.session_state["sc_contract"] = contract
                st.success("OCR 완료!")
                st.rerun()

    with st.expander("📄 계약서 페이지별 텍스트 보기"):
        for item in pages:
            st.markdown(f"**{item['page']} 페이지** (글자 수 {len(item['text'])})")
            st.text(item["text"] or "(이 페이지에서는 텍스트가 추출되지 않았습니다)")


# ─────────────────────────────────────────────
# 2단계: 키워드 고르기 + 찾기 실행 + 결과
# ─────────────────────────────────────────────
def render_step2():
    contract_type = st.session_state.get("contract_type", contract_types[0])
    contract = st.session_state.get("sc_contract")

    st.header(f"찾을 항목 고르기 — {contract_type}")
    st.caption(
        "아래는 구글 시트에 적어둔 **이 계약서에서 찾을 항목**들입니다. "
        "체크된 것만 찾습니다. 필요 없는 항목은 체크를 빼면 그만큼 빨라지고 비용도 덜 듭니다. "
        "항목 자체를 늘리거나 고치려면 위의 **📋 시트 열기** 로 시트를 고치고 **🔄 시트 새로고침**."
    )

    own = sheet_data["by_contract"].get(contract_type, [])
    common = common_items if contract_type != COMMON_COLUMN else []
    if not own and not common:
        st.info(
            f"**{contract_type}** 는 시트에 아직 항목이 없습니다. "
            f"[시트 열기]({sheet_url}) 에서 **{contract_type}** 칸 아래에 찾고 싶은 내용을 "
            "한 줄에 하나씩 적은 뒤, 1단계의 **🔄 시트 새로고침** 을 눌러주세요."
        )
        return

    all_keywords = own + [k for k in common if k not in own]

    btn1, btn2, _sp = st.columns([1, 1, 2])
    btn1.button(
        "전체 선택", use_container_width=True,
        on_click=set_all_keywords, args=(contract_type, all_keywords, True),
    )
    btn2.button(
        "전체 해제", use_container_width=True,
        on_click=set_all_keywords, args=(contract_type, all_keywords, False),
    )

    def _checkbox_block(title, items, caption=None):
        if not items:
            return
        st.markdown(f"**{title}**")
        if caption:
            st.caption(caption)
        with st.container(border=True):
            cols = st.columns(2)
            for i, kw in enumerate(items):
                with cols[i % 2]:
                    key = kw_key(contract_type, kw)
                    st.session_state.setdefault(key, True)
                    st.checkbox(kw, key=key)

    _checkbox_block(f"📌 {contract_type} 항목 ({len(own)}개)", own)
    _checkbox_block(
        f"🧩 {COMMON_COLUMN} 항목 ({len(common)}개)", common,
        caption="계약서 종류와 상관없이 항상 함께 보는 항목입니다.",
    )

    selected = [k for k in all_keywords if st.session_state.get(kw_key(contract_type, k))]
    st.caption(
        f"선택한 항목: **{len(selected)}개** / 전체 {len(all_keywords)}개 "
        f"({contract_type} {len(own)}개 + {COMMON_COLUMN} {len(common)}개)"
    )

    # ── 찾기 실행 (같은 단계에서 바로) ──
    st.divider()
    run_col, reset_col, _sp = st.columns([1.8, 1, 3])
    ready = bool(contract) and bool(selected)
    run_clicked = run_col.button(
        f"🔎 고른 항목 {len(selected)}개 찾기",
        type="primary", use_container_width=True, disabled=not ready,
    )
    reset_col.button("🔄 초기화", on_click=reset_all, use_container_width=True)

    if not contract:
        st.caption("**① 계약서 올리기** 에서 계약서를 먼저 올려주세요.")
    elif not selected:
        st.caption("찾을 항목을 하나 이상 골라주세요.")

    if run_clicked:
        api_key = get_api_key()
        if not api_key:
            st.error(
                "Anthropic(클로드) API 키가 설정되지 않았습니다. "
                "`.streamlit/secrets.toml` 의 `anthropic_api_key` 를 확인하세요."
            )
        else:
            progress = st.progress(0.0, text="계약서를 읽는 중...")
            try:
                st.session_state["scan_results"] = scan_contract(
                    contract["pages"], selected, api_key,
                    contract_type=contract_type,
                    progress_callback=lambda d, t: progress.progress(
                        d / t, text=f"찾는 중... {d}/{t} 묶음"
                    ),
                )
                st.session_state["scan_meta"] = {
                    "계약서종류": contract_type,
                    "파일": contract["name"],
                }
            except Exception as e:
                st.error(f"찾기에 실패했습니다: {e}")
            finally:
                progress.empty()

    render_results(contract)


def render_results(contract):
    """찾은 내용 — 키워드별 결과 + 원본 페이지 이미지(형광펜)."""
    results = st.session_state.get("scan_results")
    if not results:
        return

    meta = st.session_state.get("scan_meta", {})
    found_kw = [k for k, v in results.items() if v]
    total_items = sum(len(v) for v in results.values())

    st.divider()
    st.header("찾은 내용")
    st.caption(
        f"{meta.get('계약서종류','')} · {meta.get('파일','')} — "
        f"항목 **{len(found_kw)}/{len(results)}개** 에서 총 **{total_items}건** 찾음"
    )
    st.info(
        "**보는 방법** — 항목마다 계약서에 적힌 내용과 **몇 페이지**인지가 나오고, "
        "그 아래 원본 페이지 사진에 해당 문장이 **노랗게** 칠해져 있습니다. "
        "직접 눈으로 확인한 항목은 오른쪽 네모에 체크해 두면 어디까지 봤는지 알 수 있습니다. "
        "'찾지 못했습니다' 라고 나오면 그 항목은 이 계약서에 없거나 표현이 많이 달라 못 찾은 것이니, "
        "중요한 항목이면 원본을 한 번 더 확인하세요."
    )
    opt1, opt2, opt3 = st.columns([0.34, 0.45, 0.21])
    show_image = opt1.checkbox("원본 페이지 이미지(형광펜) 함께 보기", value=True)
    opt2.radio(
        "기본 이미지 크기", list(IMAGE_WIDTHS), key="img_size",
        horizontal=True, label_visibility="collapsed",
    )
    apply_all = opt3.button("모든 이미지에 적용", use_container_width=True,
                            help="아래 이미지들의 크기를 지금 고른 크기로 한 번에 맞춥니다.")
    default_size = st.session_state["img_size"]

    # ── 확인 진행바 (스크롤해도 위에 붙어 있음) ──
    all_keys = [
        f"chk_{kw}_{idx}"
        for kw, items in results.items() for idx in range(len(items))
    ]
    done = sum(1 for k in all_keys if st.session_state.get(k))
    total = len(all_keys)
    left = total - done
    pct = int(round((done / total) * 100)) if total else 0

    st.markdown(
        "<style>"
        # 확인 진행바: 화면 오른쪽 위에 완전히 고정 — 스크롤해도 항상 보임
        ".chkfixed{position:fixed; top:64px; right:24px; z-index:1000;"
        "width:290px; background:#ffffff; border:1px solid #1A2B5E;"
        "border-radius:10px; padding:10px 12px;"
        "box-shadow:0 4px 14px rgba(0,0,0,.12); font-size:13px; color:#1A2B5E;}"
        ".chkfixed b{font-size:15px;}"
        ".chkbar{height:9px; background:#e6e8ef; border-radius:5px;"
        "margin-top:7px; overflow:hidden;}"
        ".chkbar>span{display:block; height:100%; background:#1A2B5E;}"
        # 원본 페이지 이미지에 검정 테두리
        '[data-testid="stImage"] img{border:1px solid #111; border-radius:2px;}'
        "</style>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="chkfixed">✅ 확인 <b>{done}</b> / {total}건'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;남은 <b>{left}</b>건'
        f'<div class="chkbar"><span style="width:{pct}%"></span></div></div>',
        unsafe_allow_html=True,
    )

    checked_cards = []  # 체크된 카드는 초록색으로 칠하기 위해 모아둠

    for kw, items in results.items():
        st.subheader(f"🔎 {kw}  ({len(items)}건)")
        if not items:
            st.caption("이 계약서에서 관련 내용을 찾지 못했습니다.")
            continue

        for idx, item in enumerate(items):
            page = item.get("페이지")
            page_label = f"{page}페이지" if page else "페이지 미상"
            judgment = item.get("판단", "")
            # 판단은 '조항'이 아니라 '검토 항목(위험 신호)'에 대한 것이라 문장으로 적어줍니다.
            judge_line = {
                "해당": f"🔴 검토 항목 「{kw}」 → **이 위험에 해당합니다**",
                "해당 아님": f"🟢 검토 항목 「{kw}」 → 위험 없음 (해당하지 않음)",
                "조항 없음": f"🟠 검토 항목 「{kw}」 → **관련 조항이 계약서에 없습니다**",
                "확인 필요": f"🟡 검토 항목 「{kw}」 → 문구가 모호해 사람이 확인해야 합니다",
            }.get(judgment, f"「{kw}」 → {judgment}" if judgment else "")

            chk_key = f"chk_{kw}_{idx}"
            card_key = f"card_{abs(hash((kw, idx)))}"
            is_done = bool(st.session_state.get(chk_key))
            if is_done:
                checked_cards.append(card_key)

            with st.container(border=True, key=card_key):
                # 맨 앞에 체크 → 그 뒤에 제목·페이지 (세로 높이 맞춤)
                chk, head = st.columns([0.035, 0.965], vertical_alignment="center")
                chk.checkbox(
                    "확인함", key=chk_key, label_visibility="collapsed",
                    help="직접 눈으로 확인했으면 체크하세요.",
                )
                head.markdown(
                    f"**{item.get('항목') or '(항목 이름 없음)'}**"
                    f"  ·  📄 {page_label}"
                    + ("  ·  ✅ **확인함**" if is_done else "")
                )

                if judge_line:
                    st.markdown(judge_line)
                st.write(item.get("내용", ""))
                if item.get("원문"):
                    st.caption(f"원문: {item['원문']}")

                if show_image and page and contract:
                    size_key = f"imgsize_{kw}_{idx}"
                    if apply_all or size_key not in st.session_state:
                        st.session_state[size_key] = default_size
                    size_col, _sp = st.columns([0.45, 0.55])
                    size_col.radio(
                        "이미지 크기", list(IMAGE_WIDTHS), key=size_key,
                        horizontal=True, label_visibility="collapsed",
                    )
                    width = IMAGE_WIDTHS[st.session_state[size_key]]
                    try:
                        img = cached_page_image(
                            contract["pdf_path"], page,
                            item.get("원문") or item.get("내용", ""),
                        )
                        if width:
                            # 가운데 정렬: 양옆에 빈 칸을 두고 가운데 칸에 그림
                            left, mid, right = st.columns([1, 3, 1])
                            mid.image(img, width=width)
                        else:
                            st.image(img, use_container_width=True)
                    except Exception as e:
                        st.caption(f"이미지를 만들지 못했습니다: {e}")

    # 확인한 카드는 연한 초록 배경 + 초록 테두리로 표시
    if checked_cards:
        rules = ", ".join(f".st-key-{k}" for k in checked_cards)
        st.markdown(
            f"<style>{rules} {{ background:#f0fdf4; border-color:#16a34a !important; }}</style>",
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────
# 선택된 단계 그리기 + 아래쪽 이동 버튼
# ─────────────────────────────────────────────
if step == STEPS[0]:
    render_step1()
else:
    render_step2()

st.divider()
prev_col, _mid, next_col = st.columns([1.6, 3, 1.6])
if step == STEPS[1]:
    prev_col.button(
        "◀ 이전: 계약서 올리기", use_container_width=True,
        on_click=goto_step, args=(0,),
    )
else:
    next_col.button(
        "다음: 키워드 고르고 찾기 ▶", type="primary", use_container_width=True,
        on_click=goto_step, args=(1,),
    )
