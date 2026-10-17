# 4 DIE × 2 Pseudo Channel × 8 Plane: 계층 반영과 배치 실험

2026-10-17. 기준 커밋 `d3232364a20624629fb6d480c919f52b23abb4e4`에 사용자가 확인한 Die당 2개 Pseudo Channel을 반영했다. 기존 최신 실험의 채널당 8Plane과 총64Plane을 유지하므로 Die 수는 4개다.

## 구조와 적용 범위

- DIE0: PC0(global0), PC1(global1); DIE1: PC0(global2), PC1(global3).
- DIE2: PC0(global4), PC1(global5); DIE3: PC0(global6), PC1(global7).
- Pseudo Channel당 8Plane, Die당 16Plane, 합계64Plane.
- `channels`는 전체 Pseudo Channel 수, `channels_per_die`는 Die당 Pseudo Channel 수다.
- CA와 Data는 각각 Pseudo Channel별 독립 자원이다. 동일 PC의 8Plane은 각 경로를 공유한다.
- 2026-10-17 사용자가 같은 Die의 두 PC에 대해 CA·Data 모두 독립임을 확인했다. Die 공통 CA, 전원 한도, 공통 busy, Die 사이 버스 또는 multi-plane 동기 제약은 추가하지 않았다. 새 물리 정보로 이 조건이 바뀌면 본 결과를 그대로 사용하지 않는다.
- Plane당 page buffer 16KiB 1개, 합계1MiB. Controller buffer는 별도 공유8MiB다.
- 같은 Plane의 다음 sensing은 현재 NAND Data 전송 완료 뒤 시작한다. NAND 출력은16KiB다.

## 실험 조건

PF OFF, CA FIFO, round-robin 수락,4 Host Port·합계256GB/s, 기존 tR·85% 가용률·100µs 유지보수 주기·seed7을 유지했다. A1/A2는4KiB 요청·QD512/Port, B는 페이지를 끝까지 소비하는64B 연속 요청·QD32768/Port다. 부하 시작 뒤200µs를 제외한200–2200µs 고정2ms를 측정하고25µs 구간별 결과를 저장했다. NAND 경로별 수치는 이 구간에 전송이 완료된16KiB 페이지로 계산하므로 Host wire-byte 수치와 경계가 다르다.

half BW에서 Die당 raw Data BW는80.1125GB/s, 전체는320.45GB/s다. 페이지마다50ns turnaround를 포함하고 데이터가 계속 준비된다고 가정한 Data 경로 상한은 PC당35.693GB/s, Die당71.386GB/s, 전체285.544GB/s다. 이는 sensing·유지보수·Host 제한을 포함한 장치 성능 상한과 구분한다.

14개 조건을 새로 실행했다. 전체8PC의 full/half BW × A1/A2/B 6개와, half BW의4개 집중/분산 배치 × A1/A2 8개다. BW half는40.05625GB/s/PC, full은80.1125GB/s/PC다.

## 새 측정 결과

아래는40.05625GB/s/PC 조건이다. 설치된 geometry는 모든 행에서64Plane이다. 사용 PC를 제한하면 실제 주소가 사용하는 Plane 수도 줄어든다. 총64Plane을 모두 사용하면서 Die 수만 바꾼 실험으로 해석하지 않는다.

| 주소 배치 | 사용 PC 수 | 사용 Plane 수 | A1 GB/s | A2 GB/s |
| --- | --- | --- | --- | --- |
| 1 Die · 1 PC | 1 | 8 | 35.202 | 35.178 |
| 같은 Die · 2 PC | 2 | 16 | 69.618 | 69.640 |
| 서로 다른 Die · 2 PC | 2 | 16 | 70.056 | 70.056 |
| 4 Die · 각 1 PC | 4 | 32 | 134.933 | 134.746 |
| 전체 4 Die · 8 PC | 8 | 64 | 256.000 | 256.000 |

전체8PC의6개 결과는 A1/A2/B 모두256.000GB/s다. 과거 flat8×8 결과의88개 시간 구간, 전체 counter 및 sensing 집계와 정확히 일치했다. 두 독립 PC를 하나의 Die로 표시하는 것만으로 성능 비용은 발생하지 않는다.

같은 Die의2PC와 다른 Die의2PC는 동일한 자원 수를 사용한다. 현재는 Die 공통 제약이 없으며, 유지보수 위상은 global PC·Plane 인덱스로 결정된다. 따라서 두 행의 작은 차이를 물리적 Die 분산 이득으로 해석하지 않는다. 유지보수를 끈 별도 회귀 테스트에서는 두 PC 배치의 모든 요청 수락·준비·반환 시간이 같았다.

## 주소 배치

기존8×8 snapshot의16KiB 페이지 패킹과 페이지 내4개4KiB offset을 유지했다. Port별 주소 영역은 각 활성 PC에서 서로 다른2Plane을 사용한다: 영역0→PL0/1, 영역1→PL2/3, 영역2→PL4/5, 영역3→PL6/7. Port와 Die를 하드웨어로 고정 연결한 것은 아니다.

전체8PC는 기존 물리 `(global PC, Plane, q)` 매핑을 그대로 쓰고 Die metadata만 명시한다. 집중 배치는 원래 PC를 활성 PC 집합에 압축하고 충돌을 피하도록 q를 재배정한다. 이것은 정적 주소 배치 실험이며, 모든 조건에서 동일 물리 주소열을 보장하지 않는다. 원본 snapshot의 SHA256, 새 snapshot의 전체 주소 단사성, 페이지 offset 완전성, 영역별 Plane 분리를 검사했다.

Plane 내부 E/O→SSL→Block→WL420…0→Group 순서와 tR first/group20.69, short2.00, mid2.08, long12.16µs는 바꾸지 않았다. 유한 실제 NAND 용량과 Group 상한은 모델에 없다.

## 검증

- `python3 -B -m unittest discover -p 'test_znand*.py' -q`:105개 테스트 통과.
- 신규5개 테스트: 전체64Plane·offset·Die 경계,6개 워크로드×두 stripe의 flat/Die 동일성, 같은 Die의 독립PC 동시 실행과 같은PC 직렬화, 유지보수 OFF의 동일PC 수 비교, 전체 Die geometry를 요구하는 snapshot 검증.
- 기존 die32 테스트의 지원하지 않는 geometry 검사값만 변경했다.32Plane 동작 검증을 유지했다.
- 14개 실험의88개 시간 구간에서 Port별 수락−완료=outstanding, QD 한도,8MiB 용량, Host 상한, 미사용PC의 전송0, 소스·입력 해시를 확인했다.
- 전체8PC의6개 실행은 기존 flat 결과와 모든 시간 구간이 정확히 동일했다.

## 재현

저장소 루트에서 실행한다. 새 출력 경로는 저장소 내부에 둔다. 기존 측정값은 덮어쓰지 않는다.

```sh
python3 -B scripts/measure_die64_pseudo.py --out results/local/die64_pseudo_new
python3 -B scripts/measure_die64_pseudo.py --out results/local/die64_pseudo_new --validate
```

이 실험 프로파일로 유한 요청열을 실행할 수도 있지만, 그 전체 완료 평균을 위 지속 부하 평균과 혼용하지 않는다.

```sh
python3 -B -m znand.run --config results/local/die64_pseudo_20261017/profiles/half_bw_all8_A1.json --pattern A1 --per-port 2048 --out results/local/die64_finite
```

`Config.die64()`를 추가했다. `Config()`의 과거32Plane 기본값, 일반 CLI의flat4×16 기본값,`Config.die32()` 및 과거 결과는 유지한다. 신규 구조를 쓰려면 새 프로파일을 명시한다. 결과는 시뮬레이션이며 재현 코드와 원자료를 이 저장소에 함께 보관한다.

원자료: `results/local/die64_pseudo_20261017/summary.json`, `summary.csv`, `validation.json`, `manifest.json`, `snapshot_validation.json`, 조건별`result.json`·`timeline.json`, 실행 프로파일과 snapshot.
