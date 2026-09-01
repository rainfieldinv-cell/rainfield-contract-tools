# 레인필드 계약서 도구 (contract-tools)

계약서 관련 자동화 **두 가지를 한 앱**에 모은 것입니다. 왼쪽 메뉴에서 골라 씁니다.

| 메뉴 | 하는 일 | 필요한 파일 |
|---|---|---|
| 📄 **계약서·IM 비교** | 계약서와 제안서(IM)를 대조해 다른 부분을 찾고, **계약서 기준으로 제안서를 어떻게 고칠지** 정리 | 계약서 1 + 제안서 1 |
| 🔎 **계약서 항목 찾기** | 구글 시트에 적어둔 검토 항목을 계약서에서 찾아 **원본 페이지에 형광펜** 표시 | 계약서 1 |

두 화면은 서로 영향을 주지 않습니다(올린 파일과 결과를 따로 보관).

## 폴더 구조

```
app.py                  메뉴(왼쪽 사이드바) — 여기서 두 화면을 불러옵니다
views/compare.py        계약서·IM 비교 화면 (예전 doc-compare)
views/scan.py           계약서 항목 찾기 화면 (예전 contract-scan)
utils/                  공용 부품
  analyze.py            비교용 분석(금융조건·권리통제) — 클로드
  scan.py               항목 찾기 + 판단(해당/해당 아님/조항 없음/확인 필요)
  keywords.py           구글 시트에서 검토 항목 읽기
  convert.py            워드·PPT → PDF (로컬 MS Office / 클라우드 LibreOffice)
  pdf_utils.py          PDF 페이지별 텍스트 추출
  render.py             페이지 이미지 + 형광펜
  ocr.py                스캔본 OCR (클로드 비전)
  loader.py / auth.py / memo.py
```

## 검토 항목 관리 (구글 시트)

`계약서 항목 찾기` 화면의 검토 항목은 구글 시트에서 관리합니다.
시트 맨 윗줄에 **계약서 이름**, 그 아래 칸에 **찾을 내용**을 한 줄에 하나씩.
`공통` 열에 적은 항목은 **어떤 계약서를 골라도 함께** 검토합니다.
시트를 고친 뒤 앱에서 **🔄 시트 새로고침**만 누르면 반영됩니다(코드 수정 불필요).

## 로컬 실행

```
pip install -r requirements.txt
streamlit run app.py
```

`.streamlit/secrets.toml` (깃에 올라가지 않음)
```toml
anthropic_api_key = "sk-ant-..."
# keyword_sheet_url = "https://docs.google.com/spreadsheets/d/.../edit"   # 다른 시트를 쓸 때만
```

## 배포

GitHub `rainfieldinv-cell/rainfield-contract-tools` → Streamlit Community Cloud.
고친 뒤 `올리기(클라우드 반영).bat` 을 실행하면 GitHub에 올라가고 몇 분 뒤 앱에 반영됩니다.

## 참고

- 분석 모델: `claude-opus-5` (항목 찾기), `claude-opus-4-8` (비교), OCR은 클로드 비전
- 결과는 **법적 판단이 아니라 검토 보조용**입니다.
