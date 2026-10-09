# 채널당 8Plane에서 16Plane으로 확장

2026-10-09. 소프트웨어 모델에서는 4channel × 8Plane = 32Plane을 4channel × 16Plane = 64Plane으로 확장할 수 있다. 실제 NAND die를 구성하는 Plane 수나 TSV 연결 가능성을 제품 자료 없이 확정하지 않는다.

## 지원 코드와 공유 자원

`Config.planes`는 채널당 독립 Plane 수다. 기존 `planes == 8` 검증을 8 또는 16 허용으로 변경했다. 주소 계산과 busy, sensing 이력, page buffer, maintenance 상태는 이미 `c.planes`를 사용한다. 기본값은 8이며 기존 결과의 동작을 보존한다.

| 자원 | 기본 | 확장 |
|---|---:|---:|
| NAND channel | 4 | 4 |
| 독립 array/Plane 총수 | 32 | 64 |
| NAND page buffer | Plane당 16KiB 1개 | 동일, 개수만 증가 |
| NAND page buffer 총 용량 | 512KiB | 1MiB |
| CA 경로 | 채널당 1개 | 동일 |
| Data 경로 | 채널당 1개, 80.1125GB/s | 동일 |
| Host port | 4개, 각각 512bit 1GHz | 동일 |
| Controller buffer | 기본 8MiB | 자동 확대하지 않음 |

CA와 Data는 채널 안에서 공유한다. 16Plane이 동시에 별도 Data 버스로 출력한다는 의미가 아니다. 모든 port가 모든 channel을 사용할 수 있으며 port-channel 1:1 고정 연결을 추가하지 않았다. 독립 Plane을 늘려도 Host 응답의 port 내부 in-order를 완화하지 않았다.

## 16KiB stripe의 주소 배치

Host byte 주소 A에 대해 다음을 계산한다.

```text
physical_page = A // 16384
channel = physical_page % 4
slot = physical_page // 4
plane = slot % N
q = slot // N
offset = A % 16384
N = 8 또는 16
```

q의 내부 디코드는 기존 E/O→SSL→Block→감소하는 WL→Group 순서를 유지한다. N을 늘리면 같은 주소 영역을 더 많은 Plane으로 나누며, 같은 Plane으로 되돌아오는 간격이 512KiB에서 1MiB로 바뀐다.

| Byte 주소 필드 | N=8 | N=16 |
|---|---|---|
| 물리 페이지 안 offset | A[13:0] | 동일 |
| Channel | A[15:14] | 동일 |
| 채널 내 평탄화 Plane 번호 | A[18:16], 3bit | A[19:16], 4bit |
| Plane-local q | A의 bit19 이상 | A의 bit20 이상 |

이 비트 구분은 정돈 배치의 모델 매핑이다. 실제 제품의 명령 주소 비트와 동일하다고 보장하지 않는다. 4KiB stripe에서도 `plane=slot%N`, `q=slot//N`은 유지하지만 channel은 A[13:12]에서 선택하고 물리 페이지 안 4KiB sector 선택에는 A[15:14]를 사용한다.

P1은 byte 주소 0부터 시작하는 4KiB 논리 페이지다.

| 논리 영역 | 시작 주소 | 기본 8Plane/channel | 확장 16Plane/channel |
|---|---|---|---|
| P1–P4 | 0x00000 | CH0 PL0 q0 | 동일 |
| P5–P8 | 0x04000 | CH1 PL0 q0 | 동일 |
| P17–P20 | 0x10000 | CH0 PL1 q0 | 동일 |
| P129–P132 | 0x80000 | CH0 PL0 q1 | CH0 PL8 q0 |
| P253–P256 | 0xFC000 | CH3 PL7 q1 | CH3 PL15 q0 |
| P257–P260 | 0x100000 | CH0 PL0 q2 | CH0 PL0 q1 |

[채널과 Die/Plane 배치 비교](plane_layout/index.html)는 Die당 2Plane을 가정한 구성 예다. 실제 삼성 제품의 물리 배치를 의미하지 않는다.

## 실제 NAND 구성으로 해석할 때

모델은 Die/LUN의 전원, 동시에 가능한 명령 수, multi-plane 동기 제약을 구현하지 않는다. 따라서 64개의 번호를 만드는 것과 실제 독립 sensing 자원 64개를 확보하는 것을 구분한다.

가능한 구성 예는 다음과 같다. 기존 MQSim 추출 geometry는 채널당 1chip, chip당 4die, die당 2Plane을 사용했지만 이 구조는 실제 zNAND 제품의 확정 배치가 아니다.

| 구성 예 | 채널당 기본 | 채널당 확장 | 의미 |
|---|---|---|---|
| 같은 2Plane die를 추가 | 4die × 2Plane | 8die × 2Plane | Die/LUN 식별 범위와 적층/배선/전력 제약 확인 |
| Die 자체의 Plane 수 변경 | 4die × 2Plane | 4die × 4Plane | 다른 die 설계 및 독립 sensing 가능 여부 확인 |

첫 구성에서 평탄화 번호는 `die=plane//2`, `plane_in_die=plane%2`로 풀 수 있다. Die ID가 2bit에서 3bit로 늘고 die 내부 Plane ID는 1bit를 유지한다. 모델에는 별도 die 계층을 추가하지 않았으며 이 표는 물리 설계 선택지다.

Plane당 동일한 block/page 수를 유지한다면 물리 총 용량도 두 배가 된다. 총 용량을 고정하려면 Plane당 block 수 등 별도 geometry를 조절해야 한다. 현재 q/Group 모델은 유한 실제 총 용량을 제한하는 모델이 아니며 이번 실험은 같은 Host 주소 요청열을 비교했다.

## Snapshot의 geometry 확인

기존 32Plane MQSim snapshot을 64Plane 입력으로 그대로 사용하지 않는다. 16Plane/channel에서 snapshot을 쓰려면 다음 metadata가 필요하며 일치하지 않으면 Mapper가 거절한다.

```json
"model_geometry": {"channels": 4, "planes_per_channel": 16}
```

Metadata를 붙이는 것만으로 유효한 64Plane layout을 얻는 것은 아니다. 실제 geometry로 다시 추출하고 Plane 범위, 페이지 배치와 공유 제약을 검증해야 한다. 기존 8Plane/channel의 metadata 없는 snapshot은 계속 지원한다. 이번 추가 실험은 snapshot을 사용하지 않았다.

## 실험 결과와 한계

같은 A2, port당 4,096개 요청, 16KiB stripe, QD 2,048 per port, Prefetch ON에서 총 64Plane은 8MiB 버퍼로 87.965665GB/s, 32MiB로 68.720863GB/s를 기록했다. 비교할 32Plane의 값은 각각 72.265081GB/s와 37.116439GB/s다. Plane 수 증가를 성능 두 배 또는 256GB/s 보장으로 해석하지 않는다. 같은 Plane에서 port 주소 영역이 섞이는 Long sensing과 in-order 대기가 남아 있다.

실행 설정과 원본 결과는 [diagnostics 결과](../results/znand/diagnostics_2026-10-09/)에 보관한다. 예를 들어 전체 추가 진단은 다음과 같이 재현한다.

```sh
python3 -m znand.diagnostics
python3 -m znand.diagnostics --cases 64plane_8MiB 64plane_32MiB --out results/znand/replay_64plane
```

보다 긴 요청열, buffer/QD/lead 조합, port 공정성과 Plane-local 순차성을 함께 조절하는 중재는 후속 실험이다.
