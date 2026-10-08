# 이미지에 포함된 한국어 분석 메모

이미지 5~6의 중복을 제거한 전사입니다. 아래는 **사용자가 제공한 이미지 속 별도 메모**이며 이 저장소에서 확인한 결론으로 취급하지 않습니다. 5·6번 영문 질문이나 메모에 언급된 Windows 문서 자체는 제공되지 않았습니다.

메모의 조사 지시·완료 표현은 원문 기록이며, 이 저장소가 수행한 작업을 의미하지 않습니다. 기술적 단정은 [HBF 조사 결과](03_hbf_findings_ko.md)와 분리해 읽어야 합니다.

---

공개자료 조사를 병렬로 돌립니다. 영역별로 나눠서 조사한 뒤 32개 항목에 매핑하겠습니다.

## Final Results

답변 준비 문서 작성 완료: `D:\Claude_code_work\Noah_Doc\zNAND-O_Google_QA_답변준비_공개자료기반.md`

## 핵심 발견 3가지

**1. Google은 HBF 스펙을 기준으로 묻고 있습니다.**

질문 용어(AXI over UCIe, 64B~4KiB burst 64B 배수, 4KiB page, Regular/Batch Read, 4KiB 채널 인터리빙, Flit Format 6 + CRC, 사이드밴드 1개/모듈)가 **OCP HBF Base Die Spec v0.7.0 (2026-08-03)**과 그대로 일치하고, Google은 그 스펙 Acknowledgements에 명시된 기여사입니다. → 모든 답을 **“HBF 기준값 → zNAND-O 동일/상이 → 상이하면 이유”** 3단으로 구성하면 Google이 가장 빨리 이해합니다.

**2. zNAND-O 공개 정보는 FMS 2026 컨셉 수준입니다.**

UCIe I/F, TSV 4/8단, 읽기 <3μs, 200~400GB/s, 2028 샘플, **on-device NPU 타깃**. 채널 수·컨트롤러·IO 모드·책임 분담은 공개 전무 → 문서 §8 체크리스트 12항목은 삼성 내부에서만 채울 수 있습니다. 참고로 Google(TPU/서버)의 §6 reach 질문(25mm/10mm)은 UCIe-S 패키지를 전제하는데 HBF는 UCIe-A(2mm)입니다 → 패키지 타입을 먼저 답해야 합니다.

**3. Google 질문 2건은 용어가 틀렸거나 모호해서 되물어야 합니다.**

- §6 “MTP(Module Test Pattern)” → UCIe에서 MTP는 **Management Transport Packet**(2.0). 테스트 패턴은 MBINIT/MBTRAIN 서브스테이트.
- §2 back-pressure “ready deassertion” → AXI 용어. UCIe link는 credit/FIFO 기반, 어느 레벨인지 확인 필요.
- §6 비대칭 1RX/16TX → UCIe/HBF 모두 규격 없음. “compliant” 주장과 양립 불가, feasibility study로만 답 가능.

## 공개자료로 바로 답할 수 있는 것

- §1 64B 접근의 본질: ONFI CHANGE READ COLUMN으로 부분 출력은 가능하나 **page마다 full tR** → latency는 4KB와 같고 BW만 1/64. B-3(1→3→1→2)은 **page cache buffer 개수**를 묻는 질문(HBF는 bank당 2개).
- §4 HBF 기준: ECC·L2P·bad block = base die / WL = auto 또는 host zone remap 선택 / **GC 없음** / remap 후 데이터 복사 없이 host 재기록.
- §5 same-die tPROG가 read를 블로킹(FAST’12, 2x) → “채널/die 분리 시 독립”으로 조건부 답.
- §6 Flit Format 6은 CRC 포함, UCIe 1.0~2.0에 **FEC 없음**(CRC+retry).

**미확인**: Synopsys compliant/compatible 공식 정의, 멀티모듈 사이드밴드 공유 규칙, 삼성/TSMC UCIe 양산 테스트 공개문서 → 문서 §10 끝에 명시했습니다.

---

## 전사와 검증의 차이

- “질문 2건” 뒤에 세 항목이 나열된 것은 이미지 그대로 보존했습니다.
- Google의 의도를 확정하는 표현, 삼성 제품 성능·일정, 누락된 §5·§6의 내용은 이 전사만으로 입증되지 않습니다.
- “64B latency는 4KB와 같고 BW만 1/64”는 cache·요청 병합·병렬성·반환 범위를 생략한 문장입니다. 조건 없는 모델 결론으로 사용하지 않습니다.
- ONFI 동작을 별도 근거 없이 HBF/zNAND의 내부 구현에 직접 적용하지 않습니다.
