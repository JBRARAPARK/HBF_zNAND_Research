# HBF 기준 zNAND 질의 분석과 Prefetch 모델 검토

**현재 워크로드 명칭:** A1/A2는4KiB 전체 읽기, **B는 페이지 내부64B 연속 읽기(신규)**, C1/C2/C3는 기존 B1/B2/B3다. [정의·실행·이전 결과 대응표](docs/15_workload_naming_ko.md)를 기준으로 읽는다. 과거 raw 파일과 재현용 모듈은 당시 B 이름을 보존하며, 아래 기존 약4GB/s 결과는 C1/C2다.

첨부 이미지의 영문 질의 1~4번, 질문별 의도, HBF 공개 사양 조사, `NAND_Prefetch_Model`과의 비교를 정리한 연구 기록입니다.

**Google 질문에 대한 현재 답변은 [최신 실험 기준 한영 답변](docs/17_google_answers_current_ko_en.md)에 정리했습니다.** 64Plane 지속 부하와 새 B 결과를 반영하고, 처리량·tR와 아직 확정할 수 없는 UCIe end-to-end 지연·제품 지원 사양을 구분합니다. 고객 원문의 B-1/B-2/B-3 명칭으로 질문별 답변과 영문 초안을 제공합니다.

- 최종 반영일: **2026-10-11, Asia/Seoul**
- 공개 사양 조사 기준: **OCP HBF Base Die Specification v0.7.0, 2026-08-03**
- 모델 검토 기준: [`NAND_Prefetch_Model` / `6456496`](https://github.com/JBRARAPARK/NAND_Prefetch_Model/tree/645649621a94c96de5a4d614267ab80387f06c0c)
- 저장소 성격: 질의 분석, 설계 검토, 실행 가능한 모델과 평가 데이터. 삼성 제품의 공식 답변이나 실측 성능 자료가 아닙니다.

높은 QD의 성능 평가는 현재 **PF 자체를 끈 Host-only 기준선**을 사용한다. [PF ON/OFF 비교와 실행 설정](results/znand/pf_qd/RESULTS_KO.md)에 같은 조건의 결과를 제공한다. 과거 PF ON 프로파일은 대조군으로 보존한다.

**현재 처리량 판단은 지속 부하의 실제 Device outstanding과 시간별 평균을 기준으로 한다.** [지속 부하 측정과 시간 그래프](results/znand/saturation/RESULTS_KO.md)는 총 명령 완료를 기다리지 않고 2.2ms에서 관측을 끝낸다. 초기 200µs 제외 후 고정 2ms 평균과 최고 연속 500µs 평균, Port별 실제 outstanding, 25µs별 수락·완료 수를 함께 제공한다. 42개 조합에서 **8MiB·QD512/Port**의 A1/A2 고정 평균은 **255.366/255.058GB/s**다. **4MiB·QD256/Port**도 **234.484/239.904GB/s**였다. 기존 유한 요청열의 전체 완료 평균과 구분한다.

**C1/C2의 64B 부분 읽기도 같은 지속 부하 기준으로 측정했다.** [30개 조건과 시간 그래프](results/znand/partial_saturation/RESULTS_KO.md)에서 **8MiB·QD512/port**의 C1/C2 고정 평균은 **3.995/4.001GB/s**, 최고 500µs 평균은 **4.014/4.031GB/s**다. 내부 NAND는 약 257GB/s를 전송하지만, 현재 모델은 물리 16KiB마다 Host 유효 256B를 사용해 약 1/64만 유효 데이터가 된다. Long tR 비율은 해당 고정 구간에서 둘 다 0%다. 64B 물리 분산이나 부분 NAND 출력은 추가하지 않았다.

C 그래프의 주기적 하락은 [maintenance·in-order 원인 대조](results/znand/partial_dips/RESULTS_KO.md)에서 확인했다. 100µs마다 Plane을 명목 15µs 쉬게 하는 85% 가용률 모델이 선두 요청을 지연시켜, 뒤의 ready 응답도 기다리게 한다. 유지보수 OFF 대조에서 큰 낙폭이 거의 사라졌으며 기준 85%·기존 tR·in-order는 보존했다.

[A 워크로드 확대 그래프](results/znand/ab_dips/RESULTS_KO.md)에서도 100µs 간격의 작은 하락을 확인했다. 8MiB·QD512/port의 25µs 구간 최저값은 A1/A2 **248.907/249.135GB/s**다. 기존 세로축에서는 작게 보이며, 4KiB 반환이 진행되는 동안 뒤쪽 데이터 준비가 이어지는 효과를 A1/C1 동일 설정 쌍으로 설명한다.

Host IF 목표는 geometry별로 구분한다. **32Plane은 현재 모델의 신규 데이터 공급량으로 256GB/s 달성이 불가능하고, 64Plane은 배치 변경으로 근접할 여지가 있다.** [물리 상한과 12개 비교 결과](results/znand/host_ceiling/RESULTS_KO.md)에 계산·실행 근거를 정리했다.

현재 후속 성능 평가 기준은 **4channel × 16Plane = 총 64Plane**이다. 기존 tR·PF OFF·32MiB·QD2,048/port를 유지한 [64Plane 재측정 보고서](results/znand/planes64/RESULTS_KO.md)에 A1/A2의 기존 배치·영역 배치, 8,192/32,768요청/port의 8개 신규 실행을 기록한다. 실행은 `python3 -m znand.host64_measure --workers 4`이며, 길이에 맞는 [64Plane 프로파일](results/znand/planes64/profiles/)을 사용한다. 과거 결과 재현을 위한 모델 기본값과 기존 32Plane 프로파일은 보존한다.

Controller buffer를 줄인 [64Plane 16MiB 비교](results/znand/planes64_buffer16/RESULTS_KO.md)는 같은 조건의 32MiB 대조군과 비교한다. `python3 -m znand.host64_buffer --workers 4`로 실행하며, [16MiB 프로파일](results/znand/planes64_buffer16/profiles/)을 별도로 제공한다. 기존 배치와 개선 배치의 용량 민감도를 구분한다.

개선 배치에서 더 줄일 수 있는 용량은 [200GB/s 버퍼 하한 측정](results/znand/planes64_buffer_floor/RESULTS_KO.md)에 기록한다. 64Plane·QD2,048/port·PF OFF·기존 tR 및 snapshot을 고정하고 공유 버퍼만 변경했다. 신규 44개와 대조군 8개에서 A1/A2 × 8,192/32,768요청/port를 모두 통과한 최소 측정 용량은 **7.75MiB**이며, 바로 아래 7.5MiB는 세 조건이 미달했다. **8MiB**의 전체 평균은 217.521~236.348GB/s, **10MiB**는 234.988~249.367GB/s다. 시작 지연을 포함한 전체 평균으로 판정하며, 작은 버퍼에서의 Port 진행 불균형을 함께 제공한다.

## Mac에서 빠르게 실행

Python 3.10 이상과 Git이 있는 Mac에서 저장소를 내려받은 뒤 실행합니다. 수치 모델에는 외부 Python 패키지가 필요하지 않습니다.

```sh
bash scripts/macos.sh setup
bash scripts/macos.sh smoke
bash scripts/macos.sh diagnostics
```

스크립트가 프로젝트 `.venv`를 사용하고 결과는 매번 `results/local/` 아래 새 폴더에 저장합니다. `smoke`는 테스트 63개와 Mac 방식의 spawn 병렬 실행을 확인하며, `diagnostics`가 실제 6개 추가 실험을 재현합니다. 처음 내려받는 절차, Python 선택, A2 재실행과 그래프 생성은 [Mac 실행 안내](docs/11_macos_run_ko.md)를 따릅니다.

## 먼저 읽을 내용

최신 성능 판단은 [Data placement·CA 우회·Port별 QD 교차 검증](docs/17_placement_qd_crosscheck_ko.md)을 참고합니다. 업데이트한17장 PPTX/PDF와 16개 대조 실행 원자료를 제공합니다. 현재 배치에서는 FIFO로 최대 수준의 처리량이 유지되며, Port별 충분한 공급과 공유 버퍼 편중 방지가 중요합니다. 큰 QD 자체나 정확히 같은 요청 수를 보편적 조건으로 보지 않습니다. [기존 개선 이력과 구조 설명](docs/14_performance_key_items_ko.md)은 과거 실험 맥락을 보존합니다.

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
12. [컨트롤러 스케줄링 적용점](docs/12_controller_scheduling_ko.md): CA 선택 위치, 연속 주소·선두 우선, 우회 계수, 버퍼·순서 제약, 현재 프로파일과 성능 근거.
13. [컨트롤러 후속 스케줄링과 튜닝](docs/13_controller_followup_ko.md): 버퍼×QD 재평가, 제한적 연속 PF 우선, NAND Data 선두 우선, 상태별 버퍼 계측.
14. [출처 및 검토 범위](sources/README.md): 공개 문서, 모델 소스, 이미지 출처, 증거 수준.

## 현재 논의의 핵심

| 원문 문의 | 알고 싶은 것 | 현재 모델에서 연결할 부분 |
|---|---|---|
| 1. Read latency / access patterns | 실제 요청부터 반환까지의 시간, 작은 읽기와 페이지 재방문의 영향 | AR→RLAST, 준비 시점, page 재사용, 반환 순서 |
| 2. Transaction shapes / flow control | 허용 주소·길이, 작은 요청의 비용, 반환 중 정지 | 요청 생성, burst별 조회, outstanding, 수신 stall |
| 3. Interleaving / mapping | 어떤 주소들이 내부 자원을 병렬로 사용하는지 | Port·주소·channel·die·bank 연결 |
| 4. Host responsibilities | 주소와 NAND 관리를 누가 수행하는지 | 주소 공개 시점, 변환, prefetch 발행 위치 |

신규 `znand/` 모델은 A1/A2, 신규 B, C1/C2/C3의 전체·부분 읽기·재방문, 논리/물리 주소 배치, Plane별 page buffer, port 내부 in-order를 반영합니다. 기존 공급 모델에 대한 검토 문서는 당시 기준을 보존하며, 신규 구현과 결과는 아래 실행 안내를 따릅니다.

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
| 2026-10-10 | 컨트롤러 스케줄링 적용점 통합 문서 추가: FIFO/locality/head_locality, 우회 제한 동작, 프로파일과 기존 실험 근거 정리 |
| 2026-10-10 | 버퍼×QD·제한적 연속 PF·NAND Data 선두 우선 92개 신규 실험, 상태별 버퍼 계측, 추가 조건 검증과 테스트 63개. 기존 실행용 프로파일 유지 |
| 2026-10-10 | PF 자체 ON/OFF의 QD별 비교 28개 조건(신규 18개·대조군 재사용 10개), Host-only 성능 기준선과 프로파일 분리 |
| 2026-10-10 | Host IF 물리 상한 검토, 정적 주소 영역별 Plane 배치와 물리 가정 진단 12개 조건(신규 8개·대조군 4개). 실제 지연의 64Plane에서 전체 235~236GB/s와 중간 구간 약 255GB/s 관측 |
| 2026-10-10 | 최종 tR 확인: 네 배치 비교 쌍에서 snapshot만 변경됨을 전수 대조. 종류별 tR 고정값·발생 횟수·별도 2μs 진단 구분을 상세 보고서와 검증 JSON에 추가 |
| 2026-10-10 | 총 64Plane을 후속 평가 기준으로 적용. 기존/영역 배치와 8,192/32,768요청/port를 새로 측정. 긴 영역 배치 A1/A2는 고정 tR에서 전체 249.508/249.325GB/s |
| 2026-10-10 | 64Plane controller buffer 16MiB 신규 8개 조건과 32MiB 대조군 비교. 개선 배치 네 쌍의 실행 지표는 동일, 기존 배치의 긴 A1/A2는 −36.87/−40.12% |
| 2026-10-10 | 개선 배치의 200GB/s 버퍼 경계 측정: 1~32MiB의 13개 용량 × A1/A2 × 두 길이, 신규 44개·대조군 8개. 공통 최소 측정 용량 7.75MiB, 8MiB에서 217.521~236.348GB/s. Port 수락·진행 불균형과 후속 튜닝 기록 |
| 2026-10-10 | 측정 기준을 지속 부하·실제 outstanding·시간별 평균으로 변경. 42개 신규 조합, 25µs 시간 데이터, 초기 200µs 제외 고정 2ms 및 최고 500µs 평균. 8MiB·QD512에서 약 255GB/s, 큰 QD의 Port 편중 관측. 원본 NAND 모델 유지 및 신규 검증 5개 통과 |
| 2026-10-11 | C1/C2 64B 지속 부하 신규 30개 조건. 실제 QD·시간별 요청 수·NAND 내부 전송량 동시 계측, 8MiB·QD512에서 약 4GB/s 유효 처리량 및 64배 내부 데이터량 확인. 이전 A 결과 보존, 전체 테스트 71개 통과 |

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
python3 -m znand.run --config znand/observed_best/B3.json --pattern C3 --per-port 8192 --out results/znand/replay_B3
python3 -m znand.diagnostics
```

긴 trace의 80개 비교 그룹 모두 QD4,096→8,192 처리량 변화가 3% 미만이었습니다. 이는 해당 부하·버퍼·모델 조건의 포화 확인이며 실제 제품의 전역 최대 성능을 보장하지 않습니다. C2는 4KiB 분산, C3는 16KiB 분산이 유리한 조건이 관측되어 배치를 workload별로 비교해야 합니다.

추가 진단의 같은 A2 조건에서는 32Plane·8MiB가 72.265081GB/s, 64Plane·8MiB가 87.965665GB/s였습니다. 버퍼만 32MiB로 늘리면 32Plane에서 Long sensing이 증가해 37.116439GB/s로 낮아졌습니다. Word 보고서는 추가 진단 전의 1,488개 결과를 기준으로 작성한 자료이며, 최신 병목과 Plane 확장 결과는 문서 08·09와 별도 진단 폴더에 보관합니다.

원래 `NAND_Prefetch_Model`의 simulator 파일은 보존했습니다. 이 공개 저장소에는 별도 `znand/` 모듈과 실행 설정·결과를 함께 보관합니다.

## FIFO 기준 Controller buffer 확대 평가

4port·32Plane에서 공유 buffer 8/16/24/32MiB, Outstanding 2,048/4,096/8,192를 비교했다. 기존 8MiB 60개와 신규 180개, 총 240개 조건이다. A1/A2는 16MiB에서 비교 범위 내 최고 처리량을 보였고, C1/C2/C3는 8MiB가 유리했다. [비교 보고서](results/znand/buffer_expansion/RESULTS_KO.md), [원본 CSV](results/znand/buffer_expansion/sweep.csv), [후속 튜닝](docs/07_prefetch_tuning_ko.md)을 참조한다.

## 연속 물리 주소 우선 정책

Controller의 NAND CA 발행에 `ca_policy=locality`를 추가했다. Host 요청열과 port 내부 in-order 응답은 유지한다. 기존 FIFO와 동일 조건의 신규 56개 비교에서 모두 처리량이 개선됐으며, 이번 범위의 4port·32Plane 최고값은 118.780GB/s다. [비교 보고서](results/znand/locality/RESULTS_KO.md)와 [동일 조건 CSV](results/znand/locality/matched_comparison.csv)를 확인한다. FIFO 대조군 4개 포함 총 60개를 실행·검증했고 테스트 42개가 통과했다. 기본 정책은 기존 재현성을 위해 fifo로 유지한다.

A2·32MiB의 locality 설정 재실행:

```sh
python3 -m znand.run --config znand/locality_A2_32MiB.json --pattern A2 --per-port 8192 --out results/local/locality_A2_32MiB
```

## Locality 적용 후 32~64MiB 확대 결과

공유 버퍼를 8MiB 간격으로 32/40/48/56/64MiB까지 비교했다. 4port·32Plane·PF ON·port당 8,192개 요청을 유지하고, A1/A2는 QD2,048/4,096/8,192, C1/C2/C3는 QD8,192를 평가했다. 신규 39개와 동일 조건 재사용 6개, 총 45개 조건을 검증했다.

이번 범위에서는 32MiB·QD2,048/port가 A1/A2 모두 최고였다(118.780/118.257GB/s). 같은 QD에서 40~64MiB는 110.653/111.147GB/s로 같았다. 예약 peak가 약 34MiB이고 buffer 수락 실패가 0회이므로, 이 조건에서 40MiB 초과 공간은 성능에 기여하지 않았다. 높은 QD에서는 버퍼 부족 횟수가 감소했지만 기존 최고 처리량을 넘지 못했다. C계열도 고정 QD 비교에서 32MiB가 유리했다.

[비교 보고서와 그래프](results/znand/buffer_growth/RESULTS_KO.md), [45개 원본 결과](results/znand/buffer_growth/sweep.csv), [용량별 요약](results/znand/buffer_growth/summary.csv), [버퍼 제한 확인](results/znand/buffer_growth/capacity_check.json), [후속 튜닝](docs/07_prefetch_tuning_ko.md)을 참조한다. 물리 buffer 용량과 admission 예약 한도는 결합되어 있으며, 64Plane이나 장시간 정상 상태의 최적 용량을 확정한 결과는 아니다.

## 선두 요청 우선과 연속 우회 한도 평가

구현 위치와 동작을 처음부터 확인하려면 [컨트롤러 스케줄링 적용점](docs/12_controller_scheduling_ko.md)을 읽는다. Plane별 우회 계수 예시와 현재 실행용 설정을 함께 정리했다.

`ca_policy=head_locality`를 추가하고, 공유 32MiB·QD2,048/port에서 우회 4/8/16/32회와 선두 대기 0/12.16/48.64μs를 비교했다. 총 47개 조건을 실행·검증했고 51개 모델 테스트가 통과했다. Port 내부 in-order는 유지한다. [결과 보고서](results/znand/head_locality/RESULTS_KO.md)와 [원본 CSV](results/znand/head_locality/sweep.csv)에 우회 한도 조정 효과와 선두 우선 기능 자체의 효과를 분리했다.

실행용 프로파일은 A1에 선두 우선 ON·대기 48.64μs·우회 32회, A2/C1/C2/C3에 기존 locality·우회 32회를 적용한다. Port당 8,192개 요청에서 이전 locality·우회 8회 대비 A1은 118.780→134.339GB/s(+13.10%), A2는 118.257→135.035GB/s(+14.19%)다. C1/C2/C3도 같은 QD2,048 비교에서 각각 +17.91/+17.71/+18.08%다.

선두 우선 기능만의 추가 효과는 A1에서 +4.00%, port당 16,384개 확인에서 +2.09%였다. A2의 추가 효과는 +0.31/−0.01%로 작았고 C계열에서는 성능이 크게 낮아져 선두 우선을 끈 프로파일을 제공한다. 긴 요청열에서 권장 A1/A2 프로파일은 각각 143.352/143.164GB/s다. 서로 다른 길이의 수치를 같은 조건의 개선률로 섞지 않는다.

[A1 설정](results/znand/head_locality/profiles/A1.json), [A2 설정](results/znand/head_locality/profiles/A2.json), [C1](results/znand/head_locality/profiles/B1.json), [C2](results/znand/head_locality/profiles/B2.json), [C3](results/znand/head_locality/profiles/B3.json)를 해당 패턴과 함께 지정한다. 이는 개별 workload의 오프라인 설정이며 혼합 부하에 대한 자동 정책 전환은 아니다.

```sh
python3 -m znand.run --config results/znand/head_locality/profiles/A1.json --pattern A1 --per-port 8192 --out results/local/head_A1
```

## 버퍼·QD 재평가와 PF·Data 후속 실험

신규 92개 조건과 모델 테스트 63개를 검증했다. [결과 보고서](results/znand/scheduling_next/RESULTS_KO.md), [통합 CSV](results/znand/scheduling_next/all_results.csv), [검증 기록](results/znand/scheduling_next/validation.json), [구현·튜닝 문서](docs/13_controller_followup_ko.md)를 함께 제공한다.

**기존 실행용 프로파일을 유지한다.** 32Plane의 버퍼 32/40/48MiB × QD1,024/2,048/4,096 비교에서는 32MiB·QD2,048/port가 A1/A2 모두 최고였다(134.339/135.035GB/s). 제한적 PF 우선 후보의 작은 평균 이득은 seed·주소 재배치 조건에서 유지되지 않았다. NAND Data 선두 우선도 A1의 긴 요청열에서 143.352→140.442GB/s로 낮아져 기본 OFF를 유지한다.

상태 계측에서 평균 예약 대기 약 14MiB와 ready 약 13MiB가 버퍼 점유의 대부분이었다. 다음 구현 후보는 요청 정보와 payload 예약을 분리하고 발행 범위를 조절하는 방식이다. 이번에는 그 변경을 구현하지 않았다. A1/A2의 기존 정책을 64Plane에 적용한 결과는 186.803/191.508GB/s였으며, 이는 geometry 확장 효과로 별도 해석한다.

## 높은 QD의 PF 자체 OFF 비교

이후 성능 튜닝의 기준선을 **Host-only (`prefetch=false`)**로 분리했다. 이전의 `pf_ahead_limit=0`은 PF ON에서 Demand 추월 예외만 끈 설정이었다. [28개 조건의 비교 보고서](results/znand/pf_qd/RESULTS_KO.md), [원본 CSV](results/znand/pf_qd/sweep.csv), [검증](results/znand/pf_qd/validation.json)에 신규 18개와 동일 조건 재사용 10개를 구분했다. Simulator 소스 변경 없이 각 쌍의 PF Boolean만 바꿨다.

4port·32Plane·32MiB·8,192요청/port에서 Host-only 관측 최고는 QD2,048/port의 A1 **133.772GB/s**, A2 **137.212GB/s**다. QD4,096/8,192에서는 두 패턴 모두 PF OFF가 ON보다 빠르지만, OFF 상태에서도 QD2,048의 처리량을 넘지 못했다. 긴 요청열은 OFF 141.492/146.007GB/s, ON 143.352/143.164GB/s였다. PF OFF를 기준선으로 쓰되 항상 최고 성능인 공통 QD cutoff는 확정하지 않는다.

[A1 Host-only 설정](results/znand/pf_qd/profiles/A1_host_only.json), [A2 Host-only 설정](results/znand/pf_qd/profiles/A2_host_only.json)을 제공한다. QD에 따른 동적 PF 전환은 구현하지 않았다. 이후 요청 정보와 payload 예약 분리 실험도 Host-only부터 평가한다.

```sh
python3 -m znand.run --config results/znand/pf_qd/profiles/A1_host_only.json --pattern A1 --per-port 8192 --out results/local/A1_host_only
```

## Host IF 목표와 정적 배치의 효과

현재 모델은 Plane을 CA부터 NAND Data 전송 완료까지 점유한다. 모든 tR가 최단 2μs여도 32Plane의 공급량은 내부 점유가 없을 때 222.674GB/s, 가용률 85% 근사는 189.273GB/s다. Short/Mid 교대를 반영하면 약 186.111GB/s다. 따라서 32Plane에서 256GB/s는 스케줄러 개선만으로 달성할 수 없다.

실제 지연값·85% 가용률·PF OFF·in-order를 유지하고, 각 주소 영역을 모든 channel에 걸친 별도 Plane 그룹에 배치했다. A1/A2 전체 처리량은 32Plane에서 **177.115/174.788GB/s**, 64Plane에서 **236.361/234.988GB/s**였다. 64Plane의 중간 완료 구간은 255.475/255.041GB/s다. 같은 배치의 발행 정책만 바꾼 실험이 아니라 정적 L2P/배치 비교이며, 네 영역의 균형 부하라는 조건을 가진다.

**이 배치 비교의 tR 입력값은 First 20.69 / Short 2.00 / Mid 2.08 / Long 12.16 / Group 20.69μs로 모두 동일하다.** 같은 geometry의 네 쌍에서 설정 차이는 `snapshot`뿐이다. A2·64Plane의 평균 tR가 3.595→2.189μs로 낮아진 이유는 Long의 시간이 아니라 횟수가 1,142→3회로 줄었기 때문이다. 별도 `all_tr_2us` 진단은 물리 가정을 바꾼 대조군이며 배치 개선 실적에 포함하지 않는다. [상세 설명](results/znand/host_ceiling/RESULTS_KO.md)과 [설정 대조 검증](results/znand/host_ceiling/timing_validation.json)에 근거를 남겼다.

이번 요청 길이에서는 최초 데이터 준비 21.7445μs를 포함해도 전체 평균의 Host 경로 상한이 약 245.805GB/s다. Cold 전체 평균과 장시간 지속 256GB/s를 구분한다. NAND Data 경로 상한도 turnaround 포함 257.496GB/s여서 지속 256에는 약 99.42% 활용이 필요하다.

[상한 계산과 결과 보고서](results/znand/host_ceiling/RESULTS_KO.md), [12개 CSV](results/znand/host_ceiling/sweep.csv), [검증](results/znand/host_ceiling/validation.json), [진단용 배치와 프로파일](results/znand/host_ceiling/profiles/)을 제공한다. 기존 실행용 설정은 유지하며 장시간·다른 seed·주소 편향·실제 L2P 상태 검증 전에는 이 배치를 범용 설정으로 채택하지 않는다.

## 새 B: 페이지 내부 64B 연속 읽기 성능

64Plane·4Port·8MiB·PF OFF에서 새 B의 QD별 지속 성능을 측정했습니다. 초기 200µs를 제외한 고정 2ms 평균, 실제 outstanding, 완료 요청 수, NAND 데이터 활용률을 [새 B 성능 보고서](docs/16_b_sequential_performance_ko.md)에 정리했습니다. A1/C1과 동일한 장치 설정을 기준으로 QD를 변경하며, tR과 컨트롤러 스케줄링은 유지합니다.
