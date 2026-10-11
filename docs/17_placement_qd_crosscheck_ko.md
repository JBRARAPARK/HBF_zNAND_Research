# Data placement·CA 우회·Port별 QD 교차 검증

2026-10-11. 현재 모델의 최대 처리량 조건을 분리하기 위해 CA 우회 ON/OFF 6개 실행과 배치·수락 순서·QD 대조 10개 실행을 수행했다. **영역별 Data placement, 각 Port에 충분한 요청 공급, 공유 버퍼의 편중 방지가 핵심이며, 우회32나 Port별 동일 요청 수는 이 조건의 필수가 아니다.**

- [업데이트 PPTX: 17장](performance_key_items/zNAND_Performance_Placement_QD_Update_ko.pptx)
- [동일 내용 PDF](performance_key_items/zNAND_Performance_Placement_QD_Update_ko.pdf)
- [실험 원자료·manifest·검증](../results/znand/placement_qd_crosscheck/)

## 공통 조건과 해석 범위

4 Port, 4 Channel × 16 Plane, 공유 데이터 버퍼 8MiB, PF OFF, 가용률 85%, Port 내부 in-order 반환, 기존 tR을 유지했다. 초기 200µs를 제외한 200–2,200µs 고정 2ms 평균이며 종료 drain이나 최고 구간을 선택하지 않았다. A1은 순차 4KiB, A2는 국소 1-3-2 순열 4KiB, B는 페이지 전체를 덮는 연속 64B 요청이다.

이는 정적 합성 배치와 지속 읽기의 **시뮬레이션 결과**다. 실제 하드웨어 실측, 모든 워크로드의 전역 최대값, 동적 FTL·실제 UCIe 경로·Die/LUN 공유 제약까지 검증한 결과는 아니다. 요청 상태 메타데이터 비용은 8MiB 데이터 버퍼에 포함되지 않으며 QD는 AXI ID 수가 아니다. 모델 core는 수정하지 않았다.

## 1. Data placement만 바꾼 비교

CA FIFO, QD512/Port, Plane 수 등 나머지 설정을 유지하고 기본 Mapper와 영역별 L2P snapshot을 비교했다. Channel, 페이지 내 offset과 페이지 패킹은 유지하며 전체 논리 주소 영역에서 매핑의 일대일 대응을 검증했다.

| 패턴 | 기본 배치 GB/s | 영역별 배치 GB/s |
|---|---:|---:|
| A1 | 71.201843 | 255.365922 |
| A2 | 71.357144 | 255.058330 |

기본 배치 A1의 실제 outstanding 평균도 Port별 약 509~510개로 충분하고 균등했다. 요청 수만 균등하게 쌓는 것으로는 성능이 회복되지 않았다. 영역별 Plane 분리는 같은 Plane에 서로 먼 영역의 요청이 섞이는 것을 줄여 물리 주소 연속성과 Short/Mid sensing을 유지한다. 따라서 현재 조건에서 배치가 핵심 전제라는 판단은 지지되지만, 모든 부하에서 다른 요소보다 영향이 크다는 보편적 순위는 확정하지 않는다.

## 2. 우회32를 끄면 최대 성능이 유지되는가

`ca_policy=fifo`로 locality와 urgent-head CA 재정렬을 모두 끄고 비교했다. 우회 한도만 무제한으로 푼 것이 아니다. 발행 가능한 Plane 간 중재와 나머지 조건은 유지한다.

| 패턴 | QD/Port | 기존 우회32 GB/s | FIFO GB/s |
|---|---:|---:|---:|
| A1 | 512 | 255.365922 | 255.365922 |
| A2 | 512 | 255.058330 | 255.058330 |
| B | 32,768 | 255.335498 | 255.335498 |

기존 세 실행에서도 실제 같은 Plane의 오래된 작업을 추월한 횟수는 0이었다. 시간별 계측, 평균 처리량, 측정창 내 완료 요청의 평균·p99 지연도 쌍별로 동일했다. **현재 배치의 최대 성능에 우회32는 필수 조건이 아니다.** 과거 혼합 배치나 다른 요청 순서에서의 재정렬 이득까지 부정하지 않는다.

우회 한도는 쉽게 말하면, 먼저 기다린 작업을 뒤의 유리한 작업이 계속 추월하지 못하게 하는 제한이다. 동일 Plane에서 연속 주소 작업을 먼저 처리할 수 있지만 추월 누적이 한도에 도달하면 오래된 작업을 보호한다. 32라는 값 자체가 대역폭 목표에서 계산된 필수 상수는 아니다. 구현 세부는 [CA 스케줄링 설명](12_controller_scheduling_ko.md)을 참고한다.

## 3. QD가 너무 크면 본질적으로 느려지는가

다음 비교는 CA FIFO와 영역별 배치를 유지하고, 수락을 항상 Port 0부터 확인하는 기존 정책과 마지막 성공 Port 다음부터 순환하는 진단 정책을 비교했다. QD·버퍼 용량·병합·lookup·NAND·응답 규칙은 그대로다.

| 패턴 | QD/Port | 수락 순서 | GB/s | 실제 outstanding 평균: Port 0 / 1 / 2 / 3 |
|---|---:|---|---:|---|
| A1 | 2,048 | 고정 시작 | 68.857856 | 2026.5 / 1.0 / 1.0 / 1.0 |
| A1 | 2,048 | 순환 시작 | 255.339697 | 440.2 / 515.6 / 563.9 / 485.4 |
| A2 | 2,048 | 고정 시작 | 71.888925 | 2033.8 / 2.6 / 2.5 / 2.5 |
| A2 | 2,048 | 순환 시작 | 255.265435 | 442.5 / 530.6 / 574.8 / 491.4 |

같은 큰 QD에서 수락 순서만 바꿔 약255GB/s를 회복했다. 이 낙폭은 QD 자체의 필연적 비용이 아니라 기존 고정 수락 순서가 허용하는 공유 버퍼 예약 편중과 연결된다. 순환 수락 시 실제 요청 수는 정확히 같지 않아도 최대 수준을 유지했다. Port당 상한이64GB/s이므로 합계256GB/s에 근접하려면 네 Port 모두 충분히 동작해야 한다.

QD512 순환 수락 대조도 A1 255.275481, A2 255.281404GB/s였다. 순환 수락은 실험 worker 메모리에서만 적용한 진단이며 생산 모델이나 기본 정책에 적용한 변경은 아니다.

## 4. B의 큰 QD 반례와 적정 QD

| B QD/Port | 고정 수락 GB/s | 순환 수락 GB/s |
|---|---:|---:|
| 32,768 | 255.335498 | 미측정 |
| 65,536 | 255.042517 | 255.350453 |

B는 고정 수락에서도 QD를 두 배로 늘려 약255GB/s를 유지했다. 큰 QD의 성능 낙폭은 보편적인 현상이 아니다. A의 `512 × 4KiB`와 B의 `32,768 × 64B`는 모두 Port당2MiB의 요청 payload 상한이다. 이는 실제 물리 버퍼 점유량이나 메타데이터 비용과 같은 값은 아니다.

현재 고정 수락·8MiB의 실용적인 기준점은 A QD512/Port, B QD32,768/Port다. 무조건 많은 요청보다 각 Port의 공급 부족과 버퍼 편중을 함께 확인해야 하며, 요청 크기·배치·버퍼·수락 정책이 바뀌면 다시 측정해야 한다. 정확한 최소 포화 QD나 모든 조건의 최적 QD를 찾았다는 뜻은 아니다.

## 5. 약4GB/s의 출처와 모델 생략 요소

약4GB/s는 C1/C2가 물리16KiB 페이지에서 `4 × 64B = 256B`만 사용하는 희소 읽기 결과다. 명목 유효 비율은1/64이므로 약256GB/s 내부 전송이 약4GB/s의 Host 유효 데이터에 대응한다. 모든64B 요청의 상한이 아니며, 전체 페이지를 활용하는 B는 충분한 QD에서 약255GB/s다. [A/B/C 정의](15_workload_naming_ko.md), [B 기존 측정](16_b_sequential_performance_ko.md).

생략 요소가 이번 상대 비교에 모두 필수인 것은 아니다. 같은 가정 아래 배치·CA·수락 순서의 효과는 분리할 수 있다. 다만 구현 가능성이나 제품 최대 성능을 주장하려면 실제 인터페이스와 공유 자원 제약, 큰 QD의 요청 상태 비용 등을 추가 검증해야 한다. 이번 자료에서는 조건부 모델 결론과 제품 검증을 구분한다.

## 재현과 검증

저장된 결과를 검증하려면 저장소 루트에서 다음을 실행한다.

```sh
python3 -B scripts/placement_qd_crosscheck/validate_evidence.py
```

새 출력 디렉터리를 지정하면 원자료를 보존하며 전 실험을 재실행할 수 있다. 두 명령은 같은 절대 출력 경로를 사용해야 한다.

```sh
ZNAND_RESULTS_DIR=/tmp/znand-placement-recheck python3 -B scripts/placement_qd_crosscheck/run_experiment.py
ZNAND_RESULTS_DIR=/tmp/znand-placement-recheck python3 -B scripts/placement_qd_crosscheck/crosscheck.py
ZNAND_RESULTS_DIR=/tmp/znand-placement-recheck python3 -B scripts/placement_qd_crosscheck/validate_evidence.py
```

원자료 디렉터리의 두 Python 파일과 manifest는 당시 원본 경로 및 SHA-256을 포함한 실행 기록으로 보존했다. `scripts/placement_qd_crosscheck/`의 별도 실행기는 저장소 상대 경로와 출력 디렉터리 환경 변수만 적용한 이식용 버전이다. 검증은 core hash, 대조군의 설정 차이, 고정 시간창 평균, 전체 주소 영역의 배치 불변조건을 확인한다. 당시 쌍별 동일성은 `paired_equality_validation.json`, 계측·용량·QD 검증은 각 result와 validation에 기록되어 있다.

PPT 재생성 소스는 `docs/performance_key_items/update_placement_qd.mjs`다. `@oai/artifact-tool`, presentations skill과 bundled Python/Node runtime이 필요하다. `PRESENTATIONS_SKILL`에 skill 디렉터리, `CODEX_RUNTIME_DEPENDENCIES`에 runtime dependencies 디렉터리를 지정하고 Node에서 artifact-tool을 import할 수 있게 설치/연결한 뒤 실행한다. 출력은 기본 `work/placement_qd_presentation/output`이며 기존14장 PPT를 입력으로 보존한다. PDF는 생성 PPTX를 LibreOffice로 내보냈다. 최종17장 렌더를 전부 확인했으며 PDF17장 텍스트와 주요 그래프·표 렌더도 확인했다.

모델 core SHA-256: `755f822a6b7c1f44f65117b4892078419a766d4963ad4d49931e8aa1db679baf`.
