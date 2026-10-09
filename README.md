# HBF 기준 zNAND 질의 분석과 Prefetch 모델 검토

첨부 이미지의 영문 질의 1~4번, 질문별 의도, HBF 공개 사양 조사, `NAND_Prefetch_Model`과의 비교를 정리한 연구 기록입니다.

- 최종 반영일: **2026-10-09, Asia/Seoul**
- 공개 사양 조사 기준: **OCP HBF Base Die Specification v0.7.0, 2026-08-03**
- 모델 검토 기준: [`NAND_Prefetch_Model` / `6456496`](https://github.com/JBRARAPARK/NAND_Prefetch_Model/tree/645649621a94c96de5a4d614267ab80387f06c0c)
- 저장소 성격: 질의 분석, 설계 검토, 실행 가능한 모델과 평가 데이터. 삼성 제품의 공식 답변이나 실측 성능 자료가 아닙니다.

## Mac에서 빠르게 실행

Python 3.10 이상과 Git이 있는 Mac에서 저장소를 내려받은 뒤 실행합니다. 수치 모델에는 외부 Python 패키지가 필요하지 않습니다.

```sh
bash scripts/macos.sh setup
bash scripts/macos.sh smoke
bash scripts/macos.sh diagnostics
```

스크립트가 프로젝트 `.venv`를 사용하고 결과는 매번 `results/local/` 아래 새 폴더에 저장합니다. `smoke`는 테스트 35개와 Mac 방식의 spawn 병렬 실행을 확인하며, `diagnostics`가 실제 6개 추가 실험을 재현합니다. 처음 내려받는 절차, Python 선택, A2 재실행과 그래프 생성은 [Mac 실행 안내](docs/11_macos_run_ko.md)를 따릅니다.

## 먼저 읽을 내용

1. [영문 질문 원문](docs/01_questions_en.md): 중복 제거한 1~4번. 이미지에서 잘린 마지막 문장을 표시했습니다.
2. [질문별 의도](docs/02_question_intent_ko.md): 질문의 본질과 답변에 필요한 조건.
3. [HBF 조사 결과](docs/03_hbf_findings_ko.md): 사양에 확인된 항목과 미확정 항목, 원문 절·페이지.
4. [현재 Prefetch 모델과의 비교](docs/04_model_alignment_ko.md): 실제 구현, 지표, 4개 port와 AXI ID, 확장 순서.
5. [추가 확인 질문](docs/05_followup_questions_ko.md): 제품 담당자 및 내부 설계에서 확인할 사항.
6. [이미지의 한국어 메모 전사](docs/06_image_notes_ko.md): 원본에 포함된 별도 분석 메모. 검증된 조사 결과와 구분합니다.
7. [Prefetch 배치와 L2P 튜닝 기준](docs/07_prefetch_tuning_ko.md): 2026-10-09 합의한 초기 배치, 제외 사항, 튜닝 변수와 실험 설계.
8. [Host IF 상한 미달 원인](docs/08_host_if_bottleneck_ko.md): Buffer·Long sensing·in-order의 연동과 같은 조건의 추가 진단 6개.
9. [32→64Plane 확장과 NAND 주소 배치](docs/09_plane_expansion_layout_ko.md): 지원 코드, 주소 비트, 물리 Die 구성의 가정과 한계.
10. [Google 문의 답변용 모델 자료](docs/10_google_model_answers_ko.md): 기존 1,488개 실험 기준 최대 성능, A2 설명, 질문별 답변 가능 범위와 영문 초안.
11. [Mac 실행과 후속 분석](docs/11_macos_run_ko.md): 가상환경, 32/64Plane 재현, spawn 확인, 그래프와 전체 평가 실행.
12. [출처 및 검토 범위](sources/README.md): 공개 문서, 모델 소스, 이미지 출처, 증거 수준.

## 현재 논의의 핵심

| 원문 문의 | 알고 싶은 것 | 현재 모델에서 연결할 부분 |
|---|---|---|
| 1. Read latency / access patterns | 실제 요청부터 반환까지의 시간, 작은 읽기와 페이지 재방문의 영향 | AR→RLAST, 준비 시점, page 재사용, 반환 순서 |
| 2. Transaction shapes / flow control | 허용 주소·길이, 작은 요청의 비용, 반환 중 정지 | 요청 생성, burst별 조회, outstanding, 수신 stall |
| 3. Interleaving / mapping | 어떤 주소들이 내부 자원을 병렬로 사용하는지 | Port·주소·channel·die·bank 연결 |
| 4. Host responsibilities | 주소와 NAND 관리를 누가 수행하는지 | 주소 공개 시점, 변환, prefetch 발행 위치 |

신규 `znand/` 모델은 A-1~B-3의 부분 읽기·재방문, 논리/물리 주소 배치, Plane별 page buffer, port 내부 in-order를 반영합니다. 기존 공급 모델에 대한 검토 문서는 당시 기준을 보존하며, 신규 구현과 결과는 아래 실행 안내를 따릅니다.

## 확정된 사용자 설계 조건: 4개 독립 port

- Port 0~3은 **독립 요청·응답 주체**입니다.
- AXI ID는 **`(port, AXI ID)`**로 구분합니다. 다른 port의 같은 숫자 ID를 하나의 순서 그룹으로 묶지 않습니다.
- 기존 코드는 port 간 전역 반환 순서를 강제하지 않습니다.
- Port 내부는 사용자 필수 조건에 따라 ID와 무관하게 요청 수락 순서대로 반환합니다. 앞선 요청의 마지막 데이터 반환 뒤 다음 요청을 반환하며, port 간 전역 순서는 강제하지 않습니다. 기존 코드는 port별 FIFO 반환을 수행합니다.
- 4개 port는 4개 NAND channel을 공유하며, Read 주소의 저장 위치로 channel을 선택합니다. 고정 1:1 연결이 아니므로 한 port도 4개 channel을 활용할 수 있습니다.
- 2026-10-09 확정된 초기 배치와 후속 실험 범위는 [튜닝 기준](docs/07_prefetch_tuning_ko.md)을 따릅니다.

따라서 기존 모델에 대한 비교는 **각 port 내부의 ordering 정책**에 한정합니다. 4개 port 전체가 하나의 FIFO로 묶여 있다는 해석은 사용하지 않습니다.

## 결과를 읽는 기준

- **질문 원문:** 이미지에 실제로 보이는 내용만 보존합니다. 질문의 지시문은 분석 대상입니다.
- **질문 의도:** 원문을 바탕으로 한 해석이며, 질문자의 의도를 확정한 진술은 아닙니다.
- **HBF 확인:** [조사 결과](docs/03_hbf_findings_ko.md)에 근거를 모았습니다. zNAND가 동일하게 구현됐다는 뜻은 아닙니다.
- **모델 확인:** 2026-10-08에는 고정한 기존 소스를 검토했고, 2026-10-09에는 별도 주소 기반 모델을 구현해 1,488개 조건을 실행했습니다.
- **제안:** 신규 실험과 미완료 구현은 완료된 결과로 취급하지 않습니다.

## 후속 작업

실제 예측기와 coverage, 부분 NAND 출력, Die/LUN 공유 자원, 실제 GC와 동적 L2P, controller cache 여부를 후속 튜닝 대상으로 남겼습니다. 초기값·실행 범위·한계는 [튜닝 문서](docs/07_prefetch_tuning_ko.md)를 따릅니다.

관련 모델: [JBRARAPARK/NAND_Prefetch_Model](https://github.com/JBRARAPARK/NAND_Prefetch_Model)

## 변경 기록

| 날짜 | 내용 |
|---|---|
| 2026-10-08 | 질문 전사, 1~4번 분석, HBF 조사 근거, 모델 검토와 독립 port 조건을 최초 정리 |
| 2026-10-09 | 4port·4channel 공유 관계, 4KiB 논리 영역과 초기 패킹, 64B 분산 제외 및 튜닝 계획 추가 |
| 2026-10-09 | Google 문의용 보고서 본문 정리, Host IF 병목 진단 6개, 채널당 16Plane 지원과 배치 설명, 확장 회귀 테스트 7개 추가 |
| 2026-10-09 | Mac 가상환경·실행 스크립트, spawn 병렬 확인, 로컬 결과 분리, 보고서와 상위 QD 실행의 출력 경로 옵션 추가 |

## 실행 가능한 모델과 결과

**기존 1,488개 실험과 추가 병목 진단 6개를 완료**했습니다. 기존 모델 저장소에서 회귀 테스트 포함 84개가 통과했으며, 이 저장소의 주소 기반 모델 테스트는 기존 28개와 확장 7개를 합쳐 35개가 통과했습니다. 8개 물리 주소 전환 분석값 비교와 결과 CSV의 독립 검증도 통과했습니다. 모든 수치는 현재 모델 가정에 따른 시뮬레이션 결과입니다.

- [결과 보고서와 그래프](results/znand/full/RESULTS_KO.md)
- [전체 결과 CSV — 1,488개 조건](results/znand/all_results.csv)
- [상위 Outstanding 결과](results/znand/extended/sweep.csv)
- [모델 실행 안내와 가정](znand/README.md)
- [초기 설정](znand/baseline.json) / [패턴별 관측 최고 설정](znand/observed_best/)
- [요청별 예제 trace](results/znand/example/requests.csv)
- [MQSim 배치 추출과 변환](znand/mqsim/README.md)
- [후속 튜닝 문서](docs/07_prefetch_tuning_ko.md)
- [추가 A2 진단 6개 요약](results/znand/diagnostics_2026-10-09/summary.csv) / [설정과 상세 계측](results/znand/diagnostics_2026-10-09/)
- [Google 문의 답변용 보고서 본문](docs/10_google_model_answers_ko.md)
- [8/16Plane 주소 배치 비교](docs/plane_layout/index.html)

저장소 루트에서 실행합니다. 모델 실행에는 Python 표준 라이브러리만 필요합니다. 그래프 재생성에는 matplotlib이 필요합니다.

```sh
python3 -m unittest test_znand test_znand_expansion -q
python3 -m znand.validate_results
python3 -m znand.run --config znand/observed_best/B3.json --pattern B3 --per-port 8192 --out results/znand/replay_B3
python3 -m znand.diagnostics
```

긴 trace의 80개 비교 그룹 모두 QD4,096→8,192 처리량 변화가 3% 미만이었습니다. 이는 해당 부하·버퍼·모델 조건의 포화 확인이며 실제 제품의 전역 최대 성능을 보장하지 않습니다. B2는 4KiB 분산, B3는 16KiB 분산이 유리한 조건이 관측되어 배치를 workload별로 비교해야 합니다.

추가 진단의 같은 A2 조건에서는 32Plane·8MiB가 72.265081GB/s, 64Plane·8MiB가 87.965665GB/s였습니다. 버퍼만 32MiB로 늘리면 32Plane에서 Long sensing이 증가해 37.116439GB/s로 낮아졌습니다. Word 보고서는 추가 진단 전의 1,488개 결과를 기준으로 작성한 자료이며, 최신 병목과 Plane 확장 결과는 문서 08·09와 별도 진단 폴더에 보관합니다.

원래 `NAND_Prefetch_Model`의 simulator 파일은 보존했습니다. 이 비공개 저장소에는 별도 `znand/` 모듈과 실행 설정·결과를 함께 보관합니다.

## FIFO 기준 Controller buffer 확대 평가

4port·32Plane에서 공유 buffer 8/16/24/32MiB, Outstanding 2,048/4,096/8,192를 비교했다. 기존 8MiB 60개와 신규 180개, 총 240개 조건이다. A1/A2는 16MiB에서 비교 범위 내 최고 처리량을 보였고, B1/B2/B3는 8MiB가 유리했다. [비교 보고서](results/znand/buffer_expansion/RESULTS_KO.md), [원본 CSV](results/znand/buffer_expansion/sweep.csv), [후속 튜닝](docs/07_prefetch_tuning_ko.md)을 참조한다.

## 연속 물리 주소 우선 정책

Controller의 NAND CA 발행에 `ca_policy=locality`를 추가했다. Host 요청열과 port 내부 in-order 응답은 유지한다. 기존 FIFO와 동일 조건의 신규 56개 비교에서 모두 처리량이 개선됐으며, 이번 범위의 4port·32Plane 최고값은 118.780GB/s다. [비교 보고서](results/znand/locality/RESULTS_KO.md)와 [동일 조건 CSV](results/znand/locality/matched_comparison.csv)를 확인한다. FIFO 대조군 4개 포함 총 60개를 실행·검증했고 테스트 42개가 통과했다. 기본 정책은 기존 재현성을 위해 fifo로 유지한다.

A2·32MiB의 locality 설정 재실행:

```sh
python3 -m znand.run --config znand/locality_A2_32MiB.json --pattern A2 --per-port 8192 --out results/local/locality_A2_32MiB
```

## Locality 적용 후 32~64MiB 확대 결과

공유 버퍼를 8MiB 간격으로 32/40/48/56/64MiB까지 비교했다. 4port·32Plane·PF ON·port당 8,192개 요청을 유지하고, A1/A2는 QD2,048/4,096/8,192, B1/B2/B3는 QD8,192를 평가했다. 신규 39개와 동일 조건 재사용 6개, 총 45개 조건을 검증했다.

이번 범위에서는 32MiB·QD2,048/port가 A1/A2 모두 최고였다(118.780/118.257GB/s). 같은 QD에서 40~64MiB는 110.653/111.147GB/s로 같았다. 예약 peak가 약 34MiB이고 buffer 수락 실패가 0회이므로, 이 조건에서 40MiB 초과 공간은 성능에 기여하지 않았다. 높은 QD에서는 버퍼 부족 횟수가 감소했지만 기존 최고 처리량을 넘지 못했다. B계열도 고정 QD 비교에서 32MiB가 유리했다.

[비교 보고서와 그래프](results/znand/buffer_growth/RESULTS_KO.md), [45개 원본 결과](results/znand/buffer_growth/sweep.csv), [용량별 요약](results/znand/buffer_growth/summary.csv), [버퍼 제한 확인](results/znand/buffer_growth/capacity_check.json), [후속 튜닝](docs/07_prefetch_tuning_ko.md)을 참조한다. 물리 buffer 용량과 admission 예약 한도는 결합되어 있으며, 64Plane이나 장시간 정상 상태의 최적 용량을 확정한 결과는 아니다.
