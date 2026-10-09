# Host IF 상한 미달 원인과 추가 진단

2026-10-10 후속 판단은 [Host IF 256GB/s의 물리 한계와 배치 실험](../results/znand/host_ceiling/RESULTS_KO.md)에 정리했다. 현재 32Plane의 신규 데이터 공급량은 최단 tR·내부 점유 제거 조건에서도 약 222.7GB/s여서 알고리즘만으로 256GB/s를 채울 수 없다. 64Plane에서는 실제 지연값·PF OFF·port 내부 in-order를 유지한 정적 L2P 배치 변경으로 전체 235~236GB/s와 중간 완료 구간 약 255GB/s를 확인했다. 아래 6개 진단은 이전 정책의 기록으로 보존한다.

최종 설정 대조 결과, 위 배치 실험의 tR는 First 20.69 / Short 2.00 / Mid 2.08 / Long 12.16 / Group 20.69μs로 변경하지 않았다. 같은 geometry의 네 비교 쌍 모두 `snapshot`만 다르다. 평균 tR 감소는 Long 발생 횟수가 줄어든 결과이며, 모든 tR를 2μs로 바꾼 별도 한계 진단과 구분한다. [tR 및 설정 검증](../results/znand/host_ceiling/timing_validation.json)에 기계 검증 결과를 기록했다.

분석일 2026-10-09. 기준 소스는 `2b1a831882dbf23855508c3f5478aadc973d8a23`의 주소 기반 모델이다. 이 문서는 실제 제품 실측이 아니라 같은 유한 A2 요청열을 사용한 모델 진단이다. 기존 1,488개 결과에 추가 진단 6개를 합쳐 전역 최적값을 주장하지 않는다.

## 같은 조건으로 재실행한 결과

공통 조건은 4port, 4channel, 16KiB stripe, QD 2,048 per port, Prefetch ON, accuracy 1, lead 10µs, 미사용 후보 예산 128, seed 7, port당 4KiB 요청 4,096개, port 간 주소 중첩 0%다. 총 Host 데이터는 64MiB이며 외부 응답은 모든 경우 port 내부 strict in-order다. 8MiB는 물리 페이지 512개분, 32MiB는 2,048개분이다. Snapshot과 합성 remap은 사용하지 않았다.

| 조건 | 독립 Plane 총수 | 처리량 GB/s | 평균 sensing µs | Long sensing 비율 |
|---|---:|---:|---:|---:|
| 기존 버퍼 8MiB | 32 | 72.265081 | 4.007025 | 18.021713% |
| 버퍼만 32MiB로 확대 | 32 | 37.116439 | 11.435879 | 91.406250% |
| 32MiB에서 내부 점유 제거 | 32 | 43.913001 | 11.396094 | 91.015625% |
| 32MiB에서 모든 tR를 2µs로 고정 | 32 | 182.314302 | 2.000000 | 주소 분류는 유지하되 각 tR 값만 2µs로 변경 |
| Plane을 채널당 16개로 확장, 버퍼 8MiB | 64 | 87.965665 | 5.408710 | 30.431620% |
| Plane을 채널당 16개로 확장, 버퍼 32MiB | 64 | 68.720863 | 12.293281 | 98.437500% |

마지막 두 경우에는 같은 Host 주소를 64Plane으로 다시 매핑한다. 내부 점유 제거와 모든 tR=2µs 조건은 병목을 분리하기 위한 진단 가정이다. 실제 지원 사양이나 예측기의 실현 성능을 뜻하지 않는다.

## 1 NAND 공급량과 Plane 점유

Host 명목 상한은 `4 × 512bit/8 × 1GHz = 256GB/s`다. 기존 A2 결과는 상한의 28.228547%다. 기존 결과의 채널별 Data 점유율은 약 28.4%, CA 점유율은 약 11.2%다. Lookup 큐 대기는 평균 약 0.96ns이며 고정 lookup 500ns는 파이프라인 처리된다.

현재 모델에서 Plane은 CA부터 NAND 데이터 전송 완료까지 점유된다. ECC 200ns는 그 이후 지연이며 Plane의 다음 sensing을 막는 점유에는 포함하지 않는다. 16KiB 전송 시간은 `16384 / (80.1125 × 1000) = 0.204512µs`이고 turnaround는 0.05µs다.

모든 sensing이 2µs라도 Plane당 최소 처리 주기는 `2 + 0.1 + 0.204512 + 0.05 = 2.354512µs`다. 독립 Plane 32개와 평균 가용률 85%의 이상적인 지속 공급량 근사는 `32 × 16384 × 0.85 / 2.354512 / 1000 = 189.272649GB/s`다. 실제 위 진단은 182.314302GB/s다. 유한 요청열의 정확한 상한으로 가용률을 다시 곱하거나 기존 측정치에 15%를 이중 감산하지 않는다.

64Plane의 같은 sensing 근사는 378.545298GB/s지만, 4개 Data 경로의 turnaround 포함 상한은 257.496290GB/s이고 Host 상한은 256GB/s다. 독립 array 수를 늘린 뒤에는 이 공유 경로와 실제 발행 순서가 한계가 된다.

## 2 Port 주소 스트림을 섞으며 발생하는 Long sensing

A2는 논리 페이지의 지역 순열 `1→3→2→4→6→5`다. 각 port의 주소 영역은 별도다. 같은 Plane에서 port를 교대로 서비스하면 Plane-local q가 멀리 이동한다. CH0/PL0의 실제 발행 예는 `q32(port0)→q64(port1)→q96(port2)→q128(port3)→q34(port0)`다. q는 Plane-local 페이지 인덱스이며 4KiB 논리 페이지 번호가 아니다.

같은 Group에서 `q→q+1`은 Short 또는 Mid, 그 외 이동은 Long으로 분류한다. 기존 8MiB의 Long 747개 중 741개가 서로 다른 port 주소 스트림 사이의 전환이었다. 버퍼 32MiB에서는 Long 3,744개 중 3,717개가 port 전환이었다. 큰 버퍼가 더 많은 요청과 Prefetch를 보유하면서 현재 Demand 우선·대기 순서 중재의 발행 순서를 바꿨다. 따라서 버퍼 확대만으로 처리량이 단조 증가하지 않는다.

## 3 In-order와 버퍼 예약의 연동

기존 8MiB의 요청 제시 후 수락 대기는 평균 315.640442µs다. 수락 이후 지연은 102.955967µs이며 그중 데이터 ready 이후 반환 시작까지 대기는 평균 70.049673µs다. 이 반환 대기에는 Head-of-Line뿐 아니라 정상적인 Host 반환 직렬화도 포함된다.

별도 계측에서는 선두 요청이 아직 ready가 아니고 같은 port의 후속 ready 요청이 존재하는 구간을 추출했다. 그 시간은 전체 측정기간 대비 port 평균 24.453157%다. 버퍼가 512개 예약 슬롯을 모두 사용한 시간은 83.151288%다. 평균 예약 슬롯은 470.807531개, 평균 ready 슬롯은 310.204102개다. Ready 슬롯에는 미사용 Prefetch도 포함될 수 있으며 모두 순서 때문에 고정된 payload라고 해석하지 않는다.

Prefetch 후보 4,096개 중 3,543개, 즉 86.499023%가 버퍼 부족으로 거절됐다. Accuracy 1은 후보 주소의 정답률이며 coverage 또는 요청 전에 준비된 hit 비율이 아니다. 예약은 수락 시점에 이루어지므로 buffer peak에는 미도착 payload의 공간도 포함된다.

계측의 `host_idle_no_accepted_pct`에는 요청이 아직 제시되지 않았거나 해당 port의 모든 요청이 이미 완료된 시간도 포함된다. 이를 모두 admission starvation으로 해석하지 않는다. 네 port의 busy 비율은 공통 전체 측정기간을 분모로 사용한다.

## 개선 방향

- 외부 strict in-order를 유지하면서 내부 NAND 발행의 Plane-local 연속성을 높이는 정책을 검토한다.
- Port 공정성, 선두 요청의 데이터 준비, locality 유지 기간을 함께 조정한다. 순차 우선만으로 특정 port를 무기한 지연시키지 않는다.
- Prefetch의 offered 기준 lead와 실제 수락 시점을 비교하고, 수락 가능한 window와 자원 상황에 맞춰 후보를 제어한다.
- Buffer, QD, Plane 수를 함께 평가한다. 이번 6개 조건만으로 최적 용량이나 전역 최대값을 결정하지 않는다.
- 실제 Die/LUN의 공유 제약과 제품이 지원하는 sensing/출력 중첩을 보정한다.

## 재현과 근거

```sh
python3 -m unittest test_znand test_znand_expansion -q
python3 -m znand.diagnostics
```

- [추가 결과와 상세 계측](../results/znand/diagnostics_2026-10-09/results.json)
- [추가 결과 CSV](../results/znand/diagnostics_2026-10-09/sweep.csv)
- [실행 설정](../results/znand/diagnostics_2026-10-09/cases.json)
- [모델과 독립 계측 구현](../znand/diagnostics.py)
- [64Plane 주소 배치와 물리 구성의 구분](09_plane_expansion_layout_ko.md)
- [기존 1,488개 결과](../results/znand/all_results.csv)
