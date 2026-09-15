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
    topic: str = ""  # 이 항목이 묻는 '쟁점'을 한 줄로 다시 쓴 것 (단어 찾기 방지용)
    item: str  # 짧은 항목 이름 (예: 선행조건 - 담보설정)
    content: str  # 이해하기 쉽게 정리한 내용
    quote: str = ""  # 근거가 된 계약서 원문 그대로 (형광펜용)
    page: Optional[int] = None  # 원본 페이지 번호
    judgment: str = ""  # "해당" / "해당 아님" / "조항 없음" / "확인 필요"


class ScanResult(BaseModel):
    findings: List[ScanFinding]


SCAN_SYSTEM = """당신은 금융 계약서를 검토하는 꼼꼼한 한국어 금융 분석 보조원입니다.
사용자가 제시한 '검토 항목'은 **검색어가 아니라, 계약서에서 확인해야 할 쟁점(체크리스트)** 입니다.

━━━ 가장 중요한 규칙 ━━━
**항목에 들어간 단어가 포함된 문장을 찾는 것은 금지입니다.**
단어가 겹친다는 것은 근거가 되지 않습니다. 반대로 단어가 하나도 겹치지 않아도,
그 쟁점을 규율하는 조항이면 그것이 정답입니다.

반드시 이 순서로 생각하세요.
 1) 그 항목이 **무엇을 확인하려는 것인지(쟁점)** 를 한 줄로 다시 씁니다 → topic 에 적습니다.
 2) 그 쟁점을 **규율하는 조항**을 계약서 전체에서 찾습니다. (조문 제목이 달라도, 용어가 달라도 됩니다)
 3) 그 조항이 실제로 어떻게 적혀 있는지 보고, 항목이 말하는 상황에 해당하는지 판단합니다.

[잘못된 예 — 이렇게 하지 마세요]
 항목 "담보가치 하락 시 조치 없음"
   ✗ '담보가치' 라는 말이 들어간 문장을 찾아 옮겨 적음
   ✓ 담보 재평가 주기, LTV·담보비율 유지의무, 부족 시 추가담보 제공의무, 미이행 시 기한이익상실
      같은 조항을 찾아 "그런 장치가 있는지/없는지" 를 판단

 항목 "분양대금 등 수입금은 차주가 지정하는 계좌로 수납할 수 있다"
   ✗ '분양대금' 이 들어간 문장을 찾음
   ✓ 수입금이 들어가는 계좌를 누가 정하고 누가 통제하는지(계좌 지정·개설 제한·자동이체·인출 권한)
      를 규율하는 조항을 찾아 판단

 항목 "대주 동의 없이 지분, 대표 변경"
   ✗ '지분' 이라는 단어가 든 문장을 모두 나열
   ✓ 주식 양도·담보제공 제한, 경영진(대표이사·임원) 변경 통제, 지배구조 변경 시 동의·통지 조항을
      찾아 각각 있는지 판단

규칙:
- 계약서에 실제로 적힌 내용만 추출하세요. 추측하거나 지어내지 마세요.
- 단어가 겹쳐도 **쟁점이 다르면 버리세요.** (예: '비용' 항목인데 단순히 '비용'이 나오는 무관한 조항)
- 한 쟁점에 대해 **가장 핵심이 되는 조항 위주로** 정리하세요. 스치듯 언급된 문장을 늘어놓지 마세요.
- keyword 에는 사용자가 준 항목 문장을 '그대로' 적으세요(변형 금지).
- topic 에는 1)에서 정한 쟁점을 한 줄로 적으세요(예: "수입금 계좌를 누가 지정·통제하는가").
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
            f"각 항목마다 먼저 **쟁점(topic)** 을 한 줄로 정한 뒤, 그 쟁점을 규율하는 조항을 찾으세요. "
            f"항목에 들어간 단어가 포함된 문장을 찾는 방식은 금지입니다.\n"
            f"각 내용을 keyword/topic/item/content/quote/page/judgment 로 정리하세요. "
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
            "쟁점": (f.topic or "").strip(),
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
