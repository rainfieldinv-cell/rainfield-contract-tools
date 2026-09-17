"""
계약서 한 개에서 '내가 고른 키워드'에 해당하는 내용을 찾아내는 부품.

- 구글 시트에 계약서 종류별로 적어둔 키워드를 그대로 씁니다.
- 키워드 제목 글자만 찾는 게 아니라 '의미상' 해당하는 문장을 찾습니다.
- 각 내용이 원본 몇 페이지에 있는지, 그리고 형광펜을 칠할 '원문'도 함께 받아옵니다.
- 키워드가 많으면 몇 개씩 나눠서 여러 번 물어봅니다(길어져서 답이 잘리는 것 방지).
  이때 계약서 본문은 매번 같으므로 '프롬프트 캐시'를 걸어 비용을 아낍니다.
"""

import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import List, Optional

import anthropic
from pydantic import BaseModel

# 사용할 모델(품질 우선). 비용을 아끼려면 "claude-sonnet-5" 로 바꾸면 됩니다.
MODEL = "claude-opus-5"

# 한 번에 물어볼 키워드 개수 (많으면 답이 잘릴 수 있어 나눠서 물어봄)
KEYWORDS_PER_CALL = 4

# 한 번에 받을 수 있는 답의 최대 길이. 스트리밍으로 받으므로 넉넉히 둡니다.
MAX_TOKENS = 32000

# 요청은 '한 번에 하나씩' 보냅니다(순차).
#   · 동시에 보내면 30% 정도 빨라지지만, API가 '너무 빠르다'며 거절(429)할 위험이 생기고
#     계약서 본문 캐시 할인도 놓칩니다. 안전이 우선이라 순차로 둡니다.
#   · 기다리는 동안 진행 표시는 1초마다 갱신되므로 멈춘 것처럼 보이지는 않습니다.
MAX_PARALLEL = 1

# 거절(429)당했을 때 잠깐 쉬고 다시 시도하는 횟수·간격(초)
RETRY_ON_LIMIT = 3
RETRY_WAIT = 8


class ScanFinding(BaseModel):
    keyword: str  # 어떤 키워드에 해당하는 내용인지 (시트에 적힌 그 단어)
    topic: str = ""  # 이 항목이 묻는 '쟁점'을 한 줄로 다시 쓴 것 (단어 찾기 방지용)
    item: str  # 짧은 항목 이름 (예: 선행조건 - 담보설정)
    content: str  # 이해하기 쉽게 정리한 내용
    quote: str = ""  # 근거가 된 계약서 원문 그대로 (형광펜용)
    page: Optional[int] = None  # 원본 페이지 번호
    judgment: str = ""  # "해당" / "해당 아님" / "조항 없음" / "확인 필요"


class KeywordNote(BaseModel):
    """항목 하나에 대한 '대주 입장' 코멘트 (찾은 조항들을 종합한 총평)."""
    keyword: str  # 어떤 항목에 대한 코멘트인지 (시트 문장 그대로)
    why: str = ""  # 이 항목을 왜 봐야 하는지
    risk: str = ""  # 대주에게 불리하게 적혀 있으면 무엇이 문제인지
    check: str = ""  # 계약서에서 무엇을 확인·요구해야 하는지
    verdict: str = ""  # 이 계약서의 상태 한 줄 요약


class ScanResult(BaseModel):
    findings: List[ScanFinding]
    notes: List[KeywordNote] = []


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

[말이 달라도 같은 것 — 반드시 함께 보세요]
계약서마다 부르는 이름이 다릅니다. 항목에 쓰인 말이 계약서에 없어도 아래처럼 대응되는 말을 찾으세요.
 · 차주 = 위탁자 = 발행회사 = 시행사 = 채무자        · 대주 = 인수인 = 사채권자 = 채권자 = 대출기관
 · 대리금융기관 = 대리은행 = 에이전트(Agent)          · 기한이익상실 = EOD = 기한의 이익 상실 = 즉시 변제
 · 인출선행조건 = 선행조건 = 자금인출의 조건 = 대출실행 요건
 · 우선수익자 = 1순위 수익권자 = 수익권자            · 공매 = 공개매각 = 처분 = 환가
 · 근질권 = 질권 = 담보권 설정                        · 중도상환 = 기한전 상환 = 조기상환
 · 중대한 부정적 영향 = MAC = 중대한 악영향           · 자금집행 = 인출 = 지급 = 출금
 (여기 없는 말도 같은 뜻이면 같은 것으로 보세요. 조문 제목이 아니라 **내용**으로 판단하세요.)

[같은 말인데 뜻이 다른 것 — 헷갈리지 마세요]
 · '담보' : 담보신탁 / 근질권 / 연대보증 / 책임준공 — 어느 것을 말하는지 쟁점에 맞춰 고르세요.
 · '계좌' : 대출금계좌 / 분양수입금계좌 / 예비비계좌 — 쟁점과 무관한 계좌 조항은 버리세요.
 · '해지' : 계약 해지 / 신탁 해지 / 분양계약 해제 — 서로 다릅니다.
 · '변경' : 계약조건 변경 / 지분 변경 / 인허가 변경 — 다릅니다.
 · '동의' : 누가 누구에게 하는 동의인지(대주→차주 / 위탁자→수탁자)를 반드시 구분하세요.

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
  (조항이 없다는 사실 자체가 중요한 검토 결과입니다.)

━━━ notes (항목별 코멘트) — 항목마다 반드시 하나씩 ━━━
검토하는 사람은 **대주(대출·투자한 쪽)** 입니다. 항목마다 아래 네 가지를 짧고 실무적으로 적으세요.
 · why     : 대주가 이 항목을 왜 봐야 하는지 (1~2문장)
 · risk    : 이 부분이 불리하게 적혀 있으면 대주에게 무슨 손해·위험이 생기는지
 · check   : 계약서에서 구체적으로 무엇을 확인하고, 없으면 무엇을 요구해야 하는지
 · verdict : **이 계약서의 실제 상태**를 한 줄로 (예: "인출 순서는 있으나 원리금이 3순위로 밀려 있음")
일반론만 쓰지 말고, 위에서 찾은 조항 내용을 반영해 이 계약서에 맞게 쓰세요.
항목 수와 notes 개수는 같아야 합니다.

━━━ 길이 제한 (꼭 지키세요) ━━━
답이 너무 길면 중간에 잘려서 아무것도 못 받습니다. 아래를 지키세요.
 · 한 항목에 조항은 **핵심 3건까지만** (덜 중요한 것은 버리세요)
 · content 는 3문장 이내, quote 는 **한 문장만** (긴 조문은 핵심 한 문장을 그대로)
 · why / risk / verdict 는 각각 2문장 이내, check 는 ①~④ 정도까지
 · 같은 말을 되풀이하지 마세요."""


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
    progress_callback(done, total, seconds, waiting) : 진행 상황 알림(선택)
        done/total = 끝낸 묶음 / 전체 묶음, seconds = 시작 후 경과 초,
        waiting=True 는 아직 기다리는 중(1초마다 호출)

    반환값 : (찾은 내용, 항목별 코멘트)
        찾은 내용   = {키워드: [{"항목","내용","원문","페이지","판단","쟁점"}, ...]}
                      찾은 내용이 없는 키워드도 빈 리스트로 반드시 들어갑니다(누락 확인용).
        코멘트      = {키워드: {"왜","불리한 점","체크할 점","이 계약서 상태"}}
    """
    keywords = [k.strip() for k in keywords if k and k.strip()]
    result = {k: [] for k in keywords}  # 시트 순서 유지 + 못 찾은 키워드도 남김
    notes = {}
    if not keywords:
        return result, notes

    client = anthropic.Anthropic(api_key=api_key)
    document_text = _build_page_marked_text(pages)
    label = contract_type or "계약서"

    queue = list(_chunks(keywords, KEYWORDS_PER_CALL))
    done, total = 0, len(queue)
    last_error = None
    started = time.time()

    def take(batch, parsed):
        _collect(parsed.findings, batch, result)
        _collect_notes(getattr(parsed, "notes", None) or [], batch, result, notes)

    def report(waiting: bool = False):
        """진행 상황 알림. waiting=True 면 '지금 기다리는 중' 이라는 뜻."""
        if progress_callback:
            progress_callback(done, max(total, done), int(time.time() - started),
                              waiting)

    # 한 번에 하나씩(순차) 보냅니다. 기다리는 동안 1초마다 진행 표시만 갱신합니다.
    # (작업 자체는 일꾼 한 명에게 맡겨두고, 본 화면은 시간을 세면서 기다립니다)
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        while queue:
            batch = queue.pop(0)
            job = pool.submit(_ask_claude, client, document_text, label, batch)

            while True:
                finished, _ = wait([job], timeout=1.0, return_when=FIRST_COMPLETED)
                if finished:
                    break
                report(waiting=True)  # 아직 기다리는 중 — 경과 시간만 갱신

            try:
                take(batch, job.result())
            except Exception as e:
                last_error = e
                if len(batch) > 1:
                    # 답이 잘렸을 수 있으니 반으로 쪼개 다시 시도
                    half = len(batch) // 2
                    queue.insert(0, batch[half:])
                    queue.insert(0, batch[:half])
                    total += 1
                    continue
                # 항목 한 개인데도 실패하면 그 항목만 비워 두고 계속 진행

            done += 1
            report()

    # 한 항목도 못 받았으면 원인을 알려줍니다(전부 실패한 경우만)
    if last_error is not None and not any(result.values()) and not notes:
        raise last_error

    return result, notes


def _ask_claude(client, document_text: str, label: str, batch: list):
    """
    묶음 하나를 클로드에게 물어봅니다. (스트리밍 — 긴 답도 잘리지 않게)
    동시에 여러 개 보내다 거절(429)당하면 잠깐 쉬고 다시 시도합니다.
    """
    for attempt in range(RETRY_ON_LIMIT):
        try:
            return _ask_once(client, document_text, label, batch)
        except anthropic.RateLimitError:
            if attempt == RETRY_ON_LIMIT - 1:
                raise
            time.sleep(RETRY_WAIT * (attempt + 1))
        except anthropic.APIStatusError as e:
            # 서버 쪽 일시적 오류(5xx)면 한 번 더 시도
            if getattr(e, "status_code", 0) < 500 or attempt == RETRY_ON_LIMIT - 1:
                raise
            time.sleep(RETRY_WAIT)


def _ask_once(client, document_text: str, label: str, batch: list):
    """실제 호출 한 번."""
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
        f"keyword 는 위 목록의 문장을 그대로 사용하세요.\n"
        f"그리고 notes 에 **항목마다 하나씩** 대주 입장 코멘트"
        f"(why/risk/check/verdict)를 넣으세요. 위 항목 {len(batch)}개 모두 필요합니다.\n"
        f"길이 제한(항목당 조항 3건·quote 한 문장)을 반드시 지키세요."
    )

    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
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
    ) as stream:
        message = stream.get_final_message()

    return message.parsed_output


def _match_keyword(name: str, batch_keywords: list, result: dict):
    """클로드가 돌려준 키워드 이름을 우리가 보낸 항목과 맞춰줍니다."""
    def norm(s):
        return "".join((s or "").split()).lower()

    lookup = {norm(k): k for k in result}
    key = lookup.get(norm(name))
    if key is None:
        for k in batch_keywords:
            if norm(k) and (norm(k) in norm(name) or norm(name) in norm(k)):
                return k
    return key


def _collect_notes(note_list: list, batch_keywords: list, result: dict, notes: dict):
    """항목별 코멘트를 키워드별로 담습니다."""
    for n in note_list:
        key = _match_keyword(n.keyword, batch_keywords, result)
        if key is None:
            continue
        notes[key] = {
            "왜": (n.why or "").strip(),
            "불리한 점": (n.risk or "").strip(),
            "체크할 점": (n.check or "").strip(),
            "이 계약서 상태": (n.verdict or "").strip(),
        }


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
