# Prefetch 모델과의 비교

검토 대상은 [NAND_Prefetch_Model](https://github.com/JBRARAPARK/NAND_Prefetch_Model/tree/645649621a94c96de5a4d614267ab80387f06c0c)의 코드와 기존 결과입니다. 이 문서 작성 중 모델 변경이나 신규 시뮬레이션은 수행하지 않았습니다.

## 1. 현재 구현의 중심

현재 모델은 NAND에서 데이터를 준비하는 시점, burst별 조회 비용, AXI outstanding, 반환 순서가 처리량과 응답시간에 미치는 영향을 평가합니다.

| 항목 | 4포트 구성의 현재 값·동작 |
|---|---|
| 논리 요청 | 64KiB |
| 모델 NAND page | 16KiB, 논리 요청당 4개 |
| AXI burst | 64B, 논리 요청당 1,024개 |
| Host port | 4개, 각 512bit·1GHz |
| Outstanding | 각 port의 AR 수락부터 RLAST까지 점유하는 burst credit |
| 조회 | 각 port에 queue·slot·pipeline 자원이 있음 |
| NAND 배치 | `global_striped`에서 page 번호에 따라 chip·plane·channel 배치 |
| 내부 공유 자원 | NAND와 page buffer |
| 반환 | Port별 FIFO, port 간 전역 순서 없음 |
| Page 수명 | 해당 page의 모든 burst 반환이 끝나면 buffer 용량 해제 |

근거: [multiport_sim.py](https://github.com/JBRARAPARK/NAND_Prefetch_Model/blob/645649621a94c96de5a4d614267ab80387f06c0c/multiport_sim.py), [axi_burst_sim.py](https://github.com/JBRARAPARK/NAND_Prefetch_Model/blob/645649621a94c96de5a4d614267ab80387f06c0c/axi_burst_sim.py).

## 2. 독립 port와 AXI ID

사용자 확인사항: **Port 0~3은 독립 주체이고 AXI ID를 분리하여 처리할 수 있습니다.**

현재 코드도 AR admission, 조회 자원, R 반환을 port별로 처리합니다. 같은 숫자의 ID가 다른 port에 존재한다는 이유로 이들 사이에 순서 제약을 추가하지 않습니다.

| 범위 | 현재 구현 | 해석 |
|---|---|---|
| Port 간 | 독립 R 반환 | 사용자 조건과 일치 |
| Port 내 하나의 순서 그룹 | FIFO | 현재 코드로 표현 가능 |
| Port 내 여러 ID 독립 반환 | 명시적인 ID별 queue 없음 | 이 기능이 필요한 설계라면 추가 모델링 |
| 논리 요청 완료 | 모든 구성 burst 중 가장 늦은 RLAST | Port별 진행과 논리 요청 완료를 구분 |

현재 코드에는 host가 제공하는 ARID 자체를 모델 입력으로 받는 구조가 없습니다. 따라서 현재 FIFO를 곧바로 설계 오류로 분류하지 않고, **각 port 내부 ID 계약**과 비교합니다.

예를 들어 `(Port 0, ID 7)`과 `(Port 1, ID 7)`은 별도 순서 그룹입니다. `(Port 0, ID 7)`과 `(Port 0, ID 8)`의 독립 반환 여부는 해당 port가 여러 ID를 어떻게 사용하는지에 따라 결정합니다. 여러 port가 내부 bridge에 합쳐지는 경우에는 그 경계의 식별·순서 규칙을 따로 명시해야 합니다.

## 3. 현재 지연 지표와 Google 질문의 경계

현재 주된 경로:

```text
AR 수락
  → Host 판단(설정 시)
  → 조회 queue 대기 / 조회
  → 데이터 준비 대기
  → port 내 반환 순서 대기
  → R 전송 / RLAST
```

- `mean_burst_latency_us`: 각 burst의 AR 수락→RLAST 평균.
- 논리 요청 지연: demand 도착→해당 요청의 모든 burst 완료.
- AR 이전 admission 대기는 burst 지연에는 없지만 논리 요청 지연에는 영향을 줍니다.
- UCIe 자체의 패킷화·전송·credit 지연을 따로 구현한 모델은 아닙니다.
- 현재 `r_start`는 반환 시작이며, cycle별 첫 beat handshake를 모두 구현한 신호 수준 관측과 동일시하지 않습니다.

따라서 Google의 요청 발행→데이터 반환 기준과 비교할 때 시작점을 발행/수락 중 하나로 정하고, 첫 데이터/전체 데이터 완료를 모두 기록하는 것이 좋습니다.

## 4. 현재 NAND 시간 가정

| 단계 | 경합 없는 page 준비 시간 |
|---|---:|
| Command | 0.1µs |
| Sensing | 2.08µs |
| 16KiB / 2.4GB/s 전송 | 6.826667µs |
| Turnaround | 0.05µs |
| ECC | 0.2µs |
| 합계 | **9.256667µs** |

이 값은 현재 모델의 가정과 계산입니다. 제품의 실측 지연이나 HBF 보장값으로 사용하지 않습니다. NAND 작업과 조회가 겹치는 경우 전체 요청 시간을 단순 합산해서는 안 됩니다.

`prefetch_decision_us`는 speculative NAND 발행 전 판단 지연이고, `host_decision_us`는 AR 이후 조회 queue 전 판단 지연입니다. 같은 판단 회로를 양쪽에 중복 계상하지 않습니다.

근거: [기존 64GB/s 판단 지연 실험](https://github.com/JBRARAPARK/NAND_Prefetch_Model/blob/645649621a94c96de5a4d614267ab80387f06c0c/results/prefetch_decision_64/RESULTS_KO.md).

## 5. 질문 패턴과 기존 workload의 차이

### 64B 전체 소비와 64B 부분 읽기

현재 모델은 하나의 16KiB page를 가져온 뒤 64B burst 256개로 전체 데이터를 소비합니다. Google의 B-1/B-2는 페이지마다 64B만 읽는 예시이므로 다음 workload를 추가해야 합니다.

1. 페이지 전체 소비: 기존 실험과 같은 조건.
2. 페이지당 64B 하나만 소비: 작은 요청이 여러 페이지에 흩어진 조건.
3. 동일 페이지의 여러 offset 소비: page를 가져온 비용을 어느 정도 재사용하는지 평가.
4. 다른 페이지를 거친 뒤 재방문: 같은 offset/다른 offset을 구분.

### Page 재방문

현재 page 번호는 burst 순서에서 생성됩니다. 재방문을 표현하려면 요청 순번과 물리 page 식별자를 분리해야 합니다. 반환 후에도 데이터를 보관하는 정책, 교체, version, refcount, 진행 중인 읽기의 병합을 함께 정의해야 합니다.

### 순차·비순차와 배치

`single / striped / global_striped`는 배치 옵션입니다. 접근 순서를 직접 지정하는 trace를 대신하지 않습니다. A-1/A-2 비교에서는 페이지 배치를 고정하고 순서만 바꾸는 실험부터 진행해야 합니다.

## 6. Prefetch 효과를 나누어 측정할 것

요청 도착 시 다음 상태를 별도 기록합니다.

- 사전 준비 완료: 필요한 데이터가 AR 전에 준비됨.
- 준비 진행 중: prefetch를 시작했지만 AR 시점에는 완료되지 않음.
- 미준비: demand로 새 작업을 시작해야 함.
- 기존 demand 데이터 재사용: 이전 실제 요청으로 가져온 데이터에 접근.

Hit를 AR 시점과 조회 완료 시점에서 각각 기록해야 조회 시간 동안 데이터가 준비되는 경우를 구분할 수 있습니다. Cache 재사용의 효과를 prefetch 효과로 모두 집계하지 않습니다.

현재 심화 코드의 `online`은 미래 요청과 도착 시각을 아는 합성 모델입니다. 과거 관측만으로 예측하는 predictor가 아닙니다. `ready`는 사전 준비 비교이고, 잘못된 page를 ready 시점에 즉시 폐기하는 가정도 남아 있습니다.

또한 `same_total`의 host burst credit과 speculative page descriptor를 합산한 수치는 동일 실제 하드웨어 비용 비교가 아닙니다.

근거: [심화 검토 현황](https://github.com/JBRARAPARK/NAND_Prefetch_Model/blob/645649621a94c96de5a4d614267ab80387f06c0c/docs/deep_prefetch_review/STATUS_KO.md).

## 7. 권장 확장 순서 — 아직 실행하지 않음

1. **입력 계약:** 주소 단위, page 식별자, offset, 길이, 도착 시각, port, ID를 trace에 포함.
2. **기준선:** 기존 모델과 결과를 보존하고 [HBF 확인사항](03_hbf_findings_ko.md)에 대응하는 별도 설정 추가.
3. **Page 수명:** 동일 물리 page 재방문·교체·진행 중 병합 구현.
4. **순서 계약:** Port 독립을 유지하면서 port 내부 ID 정책을 선택 가능하게 함.
5. **흐름 제어:** Port별 RREADY stall, 중간 FIFO와 credit 회복 모델링.
6. **측정:** 첫 데이터·전체 완료, 평균·tail, 대기 원인, 내부 트래픽, 낭비, backlog를 함께 기록.
7. **예측기:** 알려진 demand 조기 발행과 미래 주소 예측을 구분하고 인과적 제어를 검증.

실험별로 cold 시작, 이전 데이터가 남아 있는 시작, 사전 준비 시작을 명시합니다. Outstanding을 늘려 유지한 처리량을 개별 요청의 지연 감소로 해석하지 않습니다.
