# HBF 기준 zNAND 질의 분석과 Prefetch 모델 검토

첨부 이미지의 영문 질의 1~4번, 질문별 의도, HBF 공개 사양 조사, `NAND_Prefetch_Model`과의 비교를 정리한 연구 기록입니다.

- 정리일: **2026-10-08, Asia/Seoul**
- 공개 사양 조사 기준: **OCP HBF Base Die Specification v0.7.0, 2026-08-03**
- 모델 검토 기준: [`NAND_Prefetch_Model` / `6456496`](https://github.com/JBRARAPARK/NAND_Prefetch_Model/tree/645649621a94c96de5a4d614267ab80387f06c0c)
- 저장소 성격: 질의 분석과 설계 검토 문서. 삼성 제품의 공식 답변이나 실측 성능 자료가 아닙니다.

## 먼저 읽을 내용

1. [영문 질문 원문](docs/01_questions_en.md): 중복 제거한 1~4번. 이미지에서 잘린 마지막 문장을 표시했습니다.
2. [질문별 의도](docs/02_question_intent_ko.md): 질문의 본질과 답변에 필요한 조건.
3. [HBF 조사 결과](docs/03_hbf_findings_ko.md): 사양에 확인된 항목과 미확정 항목, 원문 절·페이지.
4. [현재 Prefetch 모델과의 비교](docs/04_model_alignment_ko.md): 실제 구현, 지표, 4개 port와 AXI ID, 확장 순서.
5. [추가 확인 질문](docs/05_followup_questions_ko.md): 제품 담당자 및 내부 설계에서 확인할 사항.
6. [이미지의 한국어 메모 전사](docs/06_image_notes_ko.md): 원본에 포함된 별도 분석 메모. 검증된 조사 결과와 구분합니다.
7. [출처 및 검토 범위](sources/README.md): 공개 문서, 모델 소스, 이미지 출처, 증거 수준.

## 현재 논의의 핵심

| 원문 문의 | 알고 싶은 것 | 현재 모델에서 연결할 부분 |
|---|---|---|
| 1. Read latency / access patterns | 실제 요청부터 반환까지의 시간, 작은 읽기와 페이지 재방문의 영향 | AR→RLAST, 준비 시점, page 재사용, 반환 순서 |
| 2. Transaction shapes / flow control | 허용 주소·길이, 작은 요청의 비용, 반환 중 정지 | 요청 생성, burst별 조회, outstanding, 수신 stall |
| 3. Interleaving / mapping | 어떤 주소들이 내부 자원을 병렬로 사용하는지 | Port·주소·channel·die·bank 연결 |
| 4. Host responsibilities | 주소와 NAND 관리를 누가 수행하는지 | 주소 공개 시점, 변환, prefetch 발행 위치 |

현재 실험은 미리 준비된 데이터를 제한된 AXI outstanding으로 공급하는 효과를 보여줍니다. 실제 페이지별 부분 읽기·재방문, 주소 배치, ID별 순서 조건을 맞춰야 질문에 직접 대응하는 실험이 됩니다.

## 확정된 사용자 설계 조건: 4개 독립 port

- Port 0~3은 **독립 요청·응답 주체**입니다.
- AXI ID는 **`(port, AXI ID)`**로 구분합니다. 다른 port의 같은 숫자 ID를 하나의 순서 그룹으로 묶지 않습니다.
- 기존 코드는 port 간 전역 반환 순서를 강제하지 않습니다.
- 기존 코드는 각 port 내부에서 FIFO 반환을 수행합니다. 내부 ID를 하나의 순서 그룹으로 사용할지, 여러 ID를 독립 처리할지는 설계 조건에 맞춰 정합니다.
- Port의 독립성과 내부 NAND·버퍼 자원 공유 여부는 서로 다른 항목입니다.

따라서 기존 모델에 대한 비교는 **각 port 내부의 ordering 정책**에 한정합니다. 4개 port 전체가 하나의 FIFO로 묶여 있다는 해석은 사용하지 않습니다.

## 결과를 읽는 기준

- **질문 원문:** 이미지에 실제로 보이는 내용만 보존합니다. 질문의 지시문은 분석 대상입니다.
- **질문 의도:** 원문을 바탕으로 한 해석이며, 질문자의 의도를 확정한 진술은 아닙니다.
- **HBF 확인:** [조사 결과](docs/03_hbf_findings_ko.md)에 근거를 모았습니다. zNAND가 동일하게 구현됐다는 뜻은 아닙니다.
- **모델 확인:** 고정한 모델 소스와 기존 결과 문서를 검토했습니다. 이번 정리에서 시뮬레이션을 새로 실행하지 않았습니다.
- **제안:** 신규 실험과 미완료 구현은 완료된 결과로 취급하지 않습니다.

## 다음 작업 순서

1. 질문의 page·주소·요청 시점을 명시한 A-1~B-3 trace를 정의합니다.
2. Port별 ID 계약과 내부 자원 공유 관계를 고정합니다.
3. 현재 baseline을 보존하고 별도 HBF 비교 구성을 설계합니다.
4. Cache 재사용과 prefetch 기여도를 분리한 기준선을 만듭니다.
5. 제품별 지연·capability를 확인한 뒤 실험하고, 지연과 처리량을 함께 비교합니다.

관련 모델: [JBRARAPARK/NAND_Prefetch_Model](https://github.com/JBRARAPARK/NAND_Prefetch_Model)

## 변경 기록

| 날짜 | 내용 |
|---|---|
| 2026-10-08 | 질문 전사, 1~4번 분석, HBF 조사 근거, 모델 검토와 독립 port 조건을 최초 정리 |
