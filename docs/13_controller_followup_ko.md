# 컨트롤러 후속 스케줄링 적용과 튜닝

연속 물리 주소 우선 정책에서 버퍼와 Outstanding을 다시 평가하고, 제한적인 연속 Prefetch 우선과 NAND Data 선두 우선을 추가했다. 적용 위치는 기존 CA 스케줄러와 channel별 Data 중재기다. Host 주소열, lookup, NAND 지연값, Plane별 page buffer 1개, port 내부 in-order 응답 조건은 유지한다.

평가 조건·선택 결과·추가 확인은 [92개 조건 결과 보고서](../results/znand/scheduling_next/RESULTS_KO.md), 이전 정책의 전체 구조는 [컨트롤러 스케줄링 적용점](12_controller_scheduling_ko.md)을 따른다. 이 문서의 추가 기능은 모델 기본값에서 꺼져 있다.

**PF 자체와 우선순위 옵션을 구분한다.** 이 문서의 92개 실험은 `prefetch=true`였다. `pf_ahead_limit=0`은 PF의 Demand 추월 예외만 끈다. 이후 사용자 요청에 따른 [높은 QD의 Host-only 비교](../results/znand/pf_qd/RESULTS_KO.md)는 `prefetch=false`로 후보 생성부터 완전히 끄며, 높은 QD의 새 평가 기준선이다.

## 연속 Prefetch를 제한적으로 먼저 발행

기존 정책은 같은 Plane에 발행 가능한 Demand가 있으면 Prefetch를 후순위로 둔다. 새 옵션은 마지막 sensing 페이지의 다음 물리 페이지가 PF 후보일 때, 연속성을 유지하기 위해 제한적으로 먼저 발행한다.

```text
마지막 sensing: P0
같은 Plane의 발행 가능한 후보: Demand P100, PF P1

pf_ahead_limit=0: P100 발행
pf_ahead_limit=1: 보호 조건이 없으면 P1을 먼저 발행 가능
```

P1이 이미 발행 가능하고 같은 Group의 q+1이어야 한다. 아직 생성되지 않은 주소를 예측해서 후보로 넣거나, 미래 요청의 정답 여부를 보고 선택하지 않는다. Page buffer hit 또는 연속 주소인 Demand가 있으면 해당 Demand를 먼저 선택한다.

다음 보호 규칙도 유지한다.

1. 기존 oldest의 age와 연속 우회 한도를 먼저 적용한다.
2. CA 선두 우선 정책이 고른 긴급 선두를 먼저 처리한다.
3. 같은 Plane의 현재 선두 Demand가 `pf_head_wait_us` 이상 기다렸다면 PF 예외를 적용하지 않는다. 이 보호는 `locality`에서도 동작한다.
4. `pf_ahead_limit`에 도달하면 추가 PF 예외를 허용하지 않는다.

새 PF 계수는 `(channel, plane)`별로 관리하며 실제 CA 발행에서만 증가한다. 후보 검사나 다른 Plane과의 중재에서 탈락한 경우에는 증가하지 않는다. Demand 등 PF 예외 이외의 선택이 실제 발행되면 초기화한다. PF 예외 선택은 기존 `locality_max_bypass` 계수에도 포함된다.

Plane 간 중재에서는 해당 Plane의 oldest Demand가 가진 순번을 유지한다. 따라서 이 옵션은 같은 Plane의 선택 대상을 PF로 대체하되, 기존 Demand가 대표하던 channel 경쟁 순서를 이용한다. 모든 PF에 우선순위를 주는 규칙은 아니다.

## NAND Data 단계에서 선두 페이지 우선

기존 `data_policy=ready`는 전송 준비된 Demand 우선, 같은 등급에서는 준비 시각·생성 순번 순서다. 새 `data_policy=head`는 같은 channel에서 준비된 데이터 중 현재 port 선두의 페이지를 우선할 수 있다.

선두의 lookup이 끝났고 페이지가 `sensed` 상태여야 한다. 대기는 실제 선두가 된 시각과 lookup 완료 시각 중 늦은 시각부터 계산한다. 같은 페이지를 여러 port의 선두가 기다리면 가장 오래 기다린 선두를 기준으로 한다.

선택 순서는 다음과 같다.

1. 전송 준비 후 `data_age_us` 이상 기다린 Demand를 먼저 보호한다.
2. `data_head_wait_us`를 만족하는 선두 페이지를 선택한다.
3. 해당 후보가 없으면 기존 Demand·준비 시각 순서로 선택한다.

이미 시작한 NAND Data 전송은 중단하지 않는다. Data 전송 순서를 바꾸면 Plane이 해제되는 시점도 바뀌므로 이후 CA 순서와 tR 구성에 간접 영향을 줄 수 있다. Host 응답은 여전히 각 port의 수락 순서를 따른다.

## 설정값과 코드 위치

| 설정 | 모델 기본값 | 이번 비교 |
|---|---|---|
| `pf_ahead_limit` | 0, OFF | 0 / 1 / 2회 |
| `pf_head_wait_us` | 48.64μs | 고정. PF 예외가 선두를 추가로 미루지 못하게 하는 기준 |
| `data_policy` | `ready` | `ready` / `head` |
| `data_head_wait_us` | 0μs | 고정. 준비된 현재 선두를 바로 우선 후보로 허용 |
| `data_age_us` | 1,000μs | 고정. 오래 기다린 준비 완료 Demand 보호 |
| `locality_max_bypass` | 8 | 기존 권장값 32 유지 |
| `head_wait_us` | 12.16μs | CA 선두 ON 비교에서는 48.64μs |

PF 예외는 `locality` 또는 `head_locality` CA 정책에서만 사용할 수 있다. Data 정책은 CA 정책과 독립 옵션이다. `prefetch_limit=128`은 미사용 PF 후보 예산이며, 새 PF 우회 한도와 별개다.

| 구현 | 역할 |
|---|---|
| [`model.py`](../znand/model.py)의 `head_pages()` | CA/PF 보호/Data 선택에서 실제 port 선두와 lookup 완료 상태를 공통으로 확인 |
| `ca_candidates()` | 연속 PF 예외 후보와 기존 age·우회·선두 보호 적용 |
| `dispatch()` | 실제 발행 시 PF 우회 계수 갱신, CA/Data 전송 시작 |
| `data_candidates()` | 기존 Data 순서 및 선두·age 우선 선택 |
| [`scheduling_probe.py`](../znand/scheduling_probe.py) | 버퍼 상태별 시간 적분과 Long 발생 시점의 후보 상태 진단 |
| [`scheduling_sweep.py`](../znand/scheduling_sweep.py) | 단계별 탐색·후보 고정·추가 확인·checkpoint 및 결과 검증 |
| [`scheduling_report.py`](../znand/scheduling_report.py) | 단계별 표·추가 확인 쌍·그래프 생성 |

## 버퍼 점유를 해석하는 방법

`buffer_peak_pages`는 준비된 payload뿐 아니라 미도착 데이터의 예약 공간도 포함한다. 이번 계측은 첫 Host 요청 제시부터 마지막 반환까지 아래 상태의 점유 페이지 수를 시간 적분한다.

| 계측 | 의미 |
|---|---|
| `diag_buffer_mean_waiting_mib` | 예약되었지만 아직 CA를 발행하지 않은 작업의 평균 공간 |
| CA/sensing/sensed/transfer/ECC 평균 공간 | 실제 처리 중이거나 NAND Data 전송을 기다리는 작업 |
| `diag_buffer_mean_ready_mib` | 준비된 데이터의 평균 공간. 응답 순서 대기·현재 반환 중·미사용 PF를 포함 |
| `diag_buffer_mean_total_mib` | 전체 상태를 합한 평균 예약 공간 |

Ready 공간 전체를 HOL 때문에 낭비된 공간으로 취급하지 않는다. Port HOL 시간, 선두 데이터 준비 시간, 응답 완료 시점과 함께 해석한다. 공간이 어디에 묶이는지 확인한 뒤 물리 용량, admission window, 발행 범위 중 조정할 대상을 선택한다.

Long 진단은 스케줄러가 결정을 마친 뒤 다음 물리 페이지의 상태를 분류한다. 미수락·lookup 미완료·PF 우선순위·이미 처리된 페이지 등을 구분하되, 전체 trace를 읽는 진단 정보가 실제 스케줄링 선택에 들어가지는 않는다. 특정 상태의 건수만큼 성능 손실을 모두 제거할 수 있다고 가정하지 않는다.

## 실험 순서와 적용 범위

| 단계 | 조건 수 | 비교 |
|---|---:|---|
| A | 18 | A1/A2 × 공유 버퍼 32/40/48MiB × QD1,024/2,048/4,096 per port |
| B | 18 | A에서 선택한 자원 설정 × A1/A2 × 합성 PF 정확도 100/75/50% × PF 우회 0/1/2회 |
| C | 8 | B의 선택을 고정하고 A1/A2 × CA 선두 OFF/ON × Data 선두 OFF/ON |
| 추가 확인 | 42 | 고정 후보와 이전 프로파일을 긴 요청열·seed·합성 재배치·1~3port·B계열·64Plane에서 쌍으로 비교 |
| 상호작용 확인 | 4 | A1에서 PF 우선 OFF를 유지한 CA 선두 OFF/ON × Data 선두 OFF/ON |
| 긴 요청열 Data 확인 | 신규 2 | A1·16,384요청/port에서 PF 우선 OFF/1회 각각 Data 선두 ON. OFF 대조군 2개는 기본 실험에서 재사용 |

선택 규칙은 실행 전에 고정했다. A와 C는 기준선 대비 offer p99 +5% 이내의 조건에서 처리량을 최대화한다. B는 정확도별 처리량 −2%와 p99 +5% 범위를 모두 만족하는 예산 중 처리량 비율 기하평균을 최대화한다. 이는 이번 실험의 선택 기준이며 제품 SLA는 아니다.

상호작용 확인 4개는 A1의 B 단계 선택이 정확도 100%에서 기존 설정보다 느려 추가했다. 기본 86개 실험의 후보와 확인 조건은 고정한 채 유지한다.

긴 요청열 Data 확인은 짧은 A1에서 중간 완료 구간 처리량과 전체 처리량의 변화 방향이 달라 추가했다. 기존 대조군 2개를 재사용하므로 총 신규 실행 수는 92개다. 중간 완료 구간은 정상 상태 처리량과 구분한다.

긴 요청열은 port별 주소 범위도 바뀌며, 64Plane에서는 같은 논리 요청열을 확장된 geometry에 매핑한다. 추가 seed는 maintenance 위상을 바꾸며 A2를 균일 무작위 접근으로 만드는 것은 아니다. B계열은 기존 locality CA를 유지하고 새 자원·PF·Data 선택의 전이만 확인한다.

새 기능의 기본 OFF 동작은 [`reference_model_b5c195b.py`](../znand/reference_model_b5c195b.py)에 보존한 이전 모델과 비교한다. 새로운 소스 해시에서 과거 실험 checkpoint를 이어 붙이지 않는다. 이전 head 실험을 현재 모델로 새로 실행할 때는 `--out`으로 별도 폴더를 지정한다.

## 후속 튜닝

실행 결과와 원본은 [92개 실험 보고서](../results/znand/scheduling_next/RESULTS_KO.md)에 정리했다. **기존 실행용 프로파일을 유지하고 새 PF/Data 옵션은 기본 OFF로 둔다.**

- 버퍼 32/40/48MiB × QD1,024/2,048/4,096에서 기존 32MiB·QD2,048/port가 A1/A2 모두 가장 빨랐다(134.339/135.035GB/s).
- A1의 PF 우선 1회 후보는 정확도 100/75/50%의 상대 처리량 기하평균에서 +0.28%였지만, 정확도 100%에서는 −1.28%였고 maintenance seed 17에서는 기존 대비 −10.43%로 낮아졌다. 범용 기본값으로 승격하지 않는다.
- A2의 CA 선두 ON 후보는 기본 조건 +0.31%였지만 합성 L2P 재배치 25%에서 −8.18%였다. A2의 기존 locality 설정을 유지한다.
- A1·16,384요청/port에서 Data 선두 우선은 기존 143.352→140.442GB/s였고 p99도 822.47→862.85μs로 증가했다. PF 우선 1회 조건에서도 전체 처리량이 낮아졌다.
- A1/A2의 기존 정책을 64Plane에 적용하면 186.803/191.508GB/s였다. 동일 논리 요청열의 32Plane보다 +39.05/+41.82%지만 geometry가 바뀌어 물리 주소 이력도 바뀐다. Plane 확장과 정책 개선을 구분한다.

새 옵션 OFF와 상태 계측 ON을 이전 모델과 비교하는 회귀 검증, PF 보호 조건, Data 비선점, 작은 버퍼의 진행성, 버퍼 상태 적분의 분석값 비교를 포함해 테스트 63개가 통과했다. [통합 검증](../results/znand/scheduling_next/validation.json)은 원본 조건·CSV·JSON·소스 해시·선택 규칙·과거 대조군의 일치를 검사한다.

이번 비교는 단계별 탐색이므로 버퍼·PF·CA·Data 전체 조합의 전역 최적화는 아니다. 다음 우선순위는 **요청 메타데이터의 수락과 payload 공간 예약을 분리하는 실험**이다. 기본 A1/A2에서 Long 선택 시 다음 연속 페이지가 미수락 상태인 경우는 361/600, 332/591이었다. Buffer와 QD가 동시에 가득 찬 경우도 포함되며, 아직 Host가 제시하지 않은 요청까지 모두 해결 가능하다는 뜻은 아니다.

다음 항목을 분리해 검토한다.

- 수락한 요청 정보와 payload 공간의 분리, 발행 가능한 범위 제한. 기존 in-order 진행성을 다시 검증해야 한다.
- 선두 대기시간 외에 해당 페이지가 준비되면 이어서 반환 가능한 byte 수를 고려한 선택.
- PF 예외의 보호시간·예산과 실제 예측기의 coverage·오예측 분포.
- 실제 SSD 상태를 반영한 여러 L2P snapshot, 주소 편향·port 위상·공유 영역 변화.
- 64B 저장 분산을 도입하지 않는 범위에서 NAND 부분 출력과 ECC 단위의 별도 가정 비교.

64B 저장 분산과 소비 후 controller cache는 이번 변경에 포함하지 않는다. 임시 버퍼링과 현재 데이터 배치를 유지하며 정책 효과를 평가한다.
