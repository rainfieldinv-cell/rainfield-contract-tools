"""
계약서 한 개에서 '내가 고른 키워드'에 해당하는 내용을 찾아내는 부품.

- 구글 시트에 계약서 종류별로 적어둔 키워드를 그대로 씁니다.
- 키워드 제목 글자만 찾는 게 아니라 '의미상' 해당하는 문장을 찾습니다.
- 각 내용이 원본 몇 페이지에 있는지, 그리고 형광펜을 칠할 '원문'도 함께 받아옵니다.
- 키워드가 많으면 몇 개씩 나눠서 여러 번 물어봅니다(길어져서 답이 잘리는 것 방지).
  이때 계약서 본문은 매번 같으므로 '프롬프트 캐시'를 걸어 비용을 아낍니다.
"""

from typing import List, Optional

import anthropic
from pydantic import BaseModel

# 사용할 모델(품질 우선). 비용을 아끼려면 "claude-sonnet-5" 로 바꾸면 됩니다.
MODEL = "claude-opus-5"

# 한 번에 물어볼 키워드 개수 (많으면 답이 잘릴 수 있어 나눠서 물어봄)
KEYWORDS_PER_CALL = 6


class ScanFinding(BaseModel):
    keyword: str  # 어떤 키워드에 해당하는 내용인지 (시트에 적힌 그 단어)
    item: str  # 짧은 항목 이름 (예: 선행조건 - 담보설정)
    content: str  # 이해하기 쉽게 정리한 내용
    quote: str = ""  # 근거가 된 계약서 원문 그대로 (형광펜용)
    page: Optional[int] = None  # 원본 페이지 번호
    judgment: str = ""  # "해당" / "해당 아님" / "조항 없음" / "확인 필요"


class ScanResult(BaseModel):
    findings: List[ScanFinding]


SCAN_SYSTEM = """당신은 금융 계약서를 검토하는 꼼꼼한 한국어 금융 분석 보조원입니다.
사용자가 제시한 '검토 항목' 각각에 대해, 그 항목이 다루는 주제의 조항을 계약서에서 찾아
실제로 어떻게 적혀 있는지 보여주고, 그 항목에 해당하는 상황인지 판단합니다.

검토 항목은 두 가지 형태로 적혀 있을 수 있습니다.
 (가) 찾을 내용 자체 — 예: "선행조건으로 요구되는 사항", "당연 기한이익상실 사유"
 (나) 대주에게 불리한 '위험 신호' — 예: "체납 통제조항 없음", "언제든지 수수료 없이 중도상환",
      "MAC 없음 또는 지나치게 제한", "담보가치 하락 시 조치 없음"
 (나)의 경우, 그 주제를 다루는 조항을 찾아 실제 문구를 보여주고, 그 위험 신호에 해당하는지 판단하세요.

규칙:
- 계약서에 실제로 적힌 내용만 추출하세요. 추측하거나 지어내지 마세요.
- 제목 글자만 보지 말고, 표현이 달라도 의미가 해당하면 찾으세요.
  (예: 항목이 '선행'이면 '선행조건', '인출선행조건', '자금인출의 조건' 등도 해당)
- keyword 에는 사용자가 준 항목 문장을 '그대로' 적으세요(변형 금지).
- 한 항목에 관련 내용이 여러 곳에 있으면 각각 따로 만드세요.
- page 에는 그 내용이 등장한 [페이지 N] 표시의 숫자 N을 넣으세요.
- content 에는 계약서에 어떻게 적혀 있는지, 그리고 그것이 왜 그 판단인지 간단히 적으세요.
- quote 에는 근거가 된 계약서 '원문 문장을 그대로' 복사하세요(요약·변형 금지).
  이 문장으로 형광펜을 칠하므로 원본과 글자가 정확히 같아야 합니다. 길면 핵심 한 문장만.
- item 에는 그 내용이 어떤 조항·항목인지 짧은 한국어 이름을 적으세요(예: 제12조 기한이익상실).
- judgment 에는 반드시 아래 넷 중 하나를 그대로 적으세요.
    "해당"       : 항목이 말하는 상황(위험 신호)이 실제로 그러함
    "해당 아님"  : 관련 조항이 있고, 항목이 말하는 위험에 해당하지 않음
    "조항 없음"  : 그 주제를 다루는 조항 자체가 계약서에 보이지 않음
    "확인 필요"  : 관련 조항은 있으나 문구가 모호해 사람이 직접 봐야 함
- **그 주제의 조항이 계약서에 아예 없으면** 그 항목을 빼지 말고, judgment 를 "조항 없음" 으로 하여
  한 건을 만드세요. page 와 quote 는 비우고, content 에 무엇이 없는지 한 줄로 적으세요.
  (조항이 없다는 사실 자체가 중요한 검토 결과입니다.)"""


def _build_page_marked_text(pages: list) -> str:
    """페이지 번호를 붙여 하나의 텍스트로 합칩니다(클로드가 페이지를 인용할 수 있게)."""
    blocks = []
    for item in pages:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        blocks.append(f"[페이지 {item['page']}]\n{text}")
    return "\n\n".join(blocks)


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def scan_contract(pages: list, keywords: list, api_key: str,
                  contract_type: str = "", progress_callback=None) -> dict:
    """
    pages       : [{"page":1,"text":"..."}, ...]  (계약서 본문)
    keywords    : 사용자가 고른 키워드 목록 (시트에 적힌 순서 그대로)
    contract_type : 계약서 종류 이름 (예: 대출약정서) — 안내용
    progress_callback(done, total) : 진행 상황 알림(선택)

    반환값 : {키워드: [{"항목","내용","원문","페이지"}, ...]}
             찾은 내용이 없는 키워드도 빈 리스트로 반드시 들어갑니다(누락 확인용).
    """
    keywords = [k.strip() for k in keywords if k and k.strip()]
    result = {k: [] for k in keywords}  # 시트 순서 유지 + 못 찾은 키워드도 남김
    if not keywords:
        return result

    client = anthropic.Anthropic(api_key=api_key)
    document_text = _build_page_marked_text(pages)
    label = contract_type or "계약서"

    batches = list(_chunks(keywords, KEYWORDS_PER_CALL))
    for done, batch in enumerate(batches):
        numbered = "\n".join(f"- {k}" for k in batch)
        instruction = (
            f"위 문서는 '{label}' 입니다.\n"
            f"아래 검토 항목 각각에 대해, 그 주제의 조항을 이 계약서에서 찾아 정리하세요.\n"
            f"**아래 항목은 하나도 빠짐없이 모두 결과에 넣으세요.** "
            f"관련 조항이 없으면 judgment 를 '조항 없음' 으로 해서 넣으세요.\n\n"
            f"[검토 항목]\n{numbered}\n\n"
            f"각 내용을 keyword/item/content/quote/page/judgment 로 정리하세요. "
            f"keyword 는 위 목록의 문장을 그대로 사용하세요."
        )

        response = client.messages.parse(
            model=MODEL,
            max_tokens=16000,
            system=SCAN_SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    {
                        # 계약서 본문은 매번 똑같으므로 캐시해서 비용·시간을 아낌
                        "type": "text",
                        "text": f"계약서 본문:\n\"\"\"\n{document_text}\n\"\"\"",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": instruction},
                ],
            }],
            output_format=ScanResult,
        )

        _collect(response.parsed_output.findings, batch, result)

        if progress_callback:
            progress_callback(done + 1, len(batches))

    return result


def _collect(findings: list, batch_keywords: list, result: dict):
    """클로드가 준 결과를 키워드별로 담습니다(키워드 이름이 조금 달라도 맞춰줌)."""
    def norm(s):
        return (s or "").replace(" ", "").lower()

    lookup = {norm(k): k for k in result}

    for f in findings:
        rec = {
            "항목": (f.item or "").strip(),
            "내용": (f.content or "").strip(),
            "원문": (f.quote or "").strip(),
            "페이지": f.page,
            "판단": (f.judgment or "").strip(),
        }
        key = lookup.get(norm(f.keyword))
        if key is None:
            # 이름이 살짝 달라진 경우: 이번에 물어본 키워드 중 포함관계로 찾아봄
            for k in batch_keywords:
                if norm(k) and (norm(k) in norm(f.keyword) or norm(f.keyword) in norm(k)):
                    key = k
                    break
        if key is None:
            key = batch_keywords[0] if batch_keywords else None
        if key is not None:
            result[key].append(rec)
