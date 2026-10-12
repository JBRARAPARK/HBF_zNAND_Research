# 200GB/s 이상 성능 기준으로 복원: DIE 없는64Plane

> 후속 [8Channel×8Plane 및 BW 절반 비교](23_channel_split64_ko.md)에서 이 결과를 대조군으로 사용합니다.8×8 지원 추가 뒤4×16을 재측정할 때는 `--out results/local/restored64_new`처럼 새 출력 경로를 사용하세요. 이 문서의 원본 소스 해시 재현은 커밋 `45e9d72` 기준입니다.

2026-10-12. 사용자 요청으로 **4 Channel × 16 Plane = 총64Plane**을 현재 성능 평가 기준으로 복원했다. 영역별 Data placement와 A1/A2/B별 Config는 DIE 도입 이전의 FIFO 대조 실험과 동일하다. 이후 요청한 **순환 수락은 유지**한다.32Plane DIE 실험은 보관 자료로만 남기며 현재 성능 판단에 사용하지 않는다.

이번 작업은 과거 커밋으로 이력을 강제 되돌리는 작업이 아니다. 검증된64Plane 프로파일을 현재 실행 기준으로 복원하고, 코드·문서·새 측정을 새 커밋으로 남긴다.

## 새로 확인한 성능

초기200µs를 제외한0.2–2.2ms의 고정2ms 평균이다. 이전 기록은 고정 수락, 현재 결과는 순환 수락이다.

| 요청 | QD/Port | 이전64Plane 고정 수락 GB/s | 복원64Plane 순환 수락 GB/s | Port별 GB/s | 후반1ms / 전반1ms 변화 |
|---|---:|---:|---:|---|---:|
| A1 | 512 | 255.366 | **255.275** | 63.98 / 63.74 / 63.56 / 64.00 | +0.18% |
| A2 | 512 | 255.058 | **255.281** | 64.00 / 63.72 / 63.56 / 64.00 | -0.06% |
| B | 32,768 | 255.335 | **255.360** | 64.00 / 63.71 / 63.65 / 64.00 | -0.23% |

A1/A2/B 모두200GB/s를 넘는 것을 이번 실행에서 확인했다. 이 수치는 해당 부하·배치·시간 구간의 시뮬레이션 처리량이며 실측이나 전역 최대값을 뜻하지 않는다.

## 복원한 조건

- 독립 Channel4개, Channel당 Plane16개. DIE 계층과 DIE 단위 공유 자원을 추가하지 않는다.
- 4 Host Port, Port당64GB/s, 합계256GB/s. 공유 데이터 버퍼8MiB.
- Data placement: 과거64Plane 영역별 snapshot을 그대로 사용한다. A1/B는4KiB stripe, A2는16KiB stripe.
- PF OFF, CA FIFO, Host 수락은 round-robin. CA locality 우회는 사용하지 않는다.
- 기존 tR First·Group20.69µs, Short2.00µs, Mid2.08µs, Long12.16µs, 명목 가용률85%, 유지보수 주기100µs.
- A1/A2는4KiB 읽기·QD512/Port, B는 페이지 전체를 소비하는 연속64B 읽기·QD32,768/Port.
- Config는 과거 결과와 필드별 일치한다. 나중에 추가된 DIE 필드는 현재 모델에서0으로 해석된다. 순환 수락은 Config 밖의 공통 모델 정책이다.

앞선 DIE 실험은64Plane에서32Plane으로 줄이고 Channel을4개에서8개로 바꾼 구성이다. 따라서185.82GB/s와 약255GB/s의 차이를 단순한 DIE 이름·계층 추가 비용으로 해석하지 않는다. 여기서는 사용자 요청대로 이전64Plane 구성을 다시 기준으로 삼았다.

## 실행 및 검증

저장소 루트에서 실행한다.

```sh
python3 -B scripts/measure_restored64.py
# 기존 결과를 보존하며 새로운 실행을 하려면:
python3 -B scripts/measure_restored64.py --out results/local/restored64_new
# 저장된 현재 기준 결과 검증:
python3 -B scripts/measure_restored64.py --validate
python3 -B -m unittest discover -p "test_znand*.py"
```

프로파일은 [A1](../configs/performance64/A1.json), [A2](../configs/performance64/A2.json), [B](../configs/performance64/B.json)에 있다. 유한 요청열 CLI `python3 -m znand.run`도 기본 형상을 DIE 없는64Plane으로 바꿨으나, 이 CLI의 기본 배치·요청 공급·fill/drain 평균은 위 지속 부하 측정과 다르다.200GB/s 확인에는 위 측정 명령을 사용한다.

- A1/A2는 DIE 도입 전64Plane·QD512 순환 수락 대조 실험과 모든 시간창 집계가 정확히 일치했다. [대조 검증](../results/znand/restored64/historical_rr_crosscheck.json).
- 전체96개 단위·회귀 테스트 통과. 무설정 CLI의64Plane·DIE 없음·순환 수락과 명시한 과거 설정 유지도 검증했다.
- 3개 측정에서 당시 Config와 snapshot 일치, 소스·설정·과거 결과 해시,2ms 집계, Port별 수락−완료=outstanding, QD 상한,8MiB 용량, 주소 범위를 검증했다.
- [새 결과](../results/znand/restored64/summary.json), [검증 결과](../results/znand/restored64/validation.json), [실행 manifest](../results/znand/restored64/manifest.json).

## 보관된 실험

32Plane DIE 구조와 측정 파일은 삭제하지 않았다. [구조](18_die_channel_plane_layout_ko.md), [기본 측정](19_die32_performance_ko.md), [고QD](20_die32_high_qd_ko.md), [32Plane 순환 수락](21_die32_round_robin_ko.md)은 과거 비교 기록이다. 현재 코드의 `Config.die32()`는 명시적인 과거 비교에만 사용할 수 있다. 현재 복원 명령과 프로파일은 이를 호출하지 않는다.
