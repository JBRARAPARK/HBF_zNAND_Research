# A / B / C 워크로드 정의

2026-10-11 사용자 결정에 따라 **페이지 내부를 64B씩 연속 읽는 새 패턴을 B**, 기존 B1/B2/B3를 **C1/C2/C3**로 부른다. 현재 명칭의 schema는 2다.

| 현재 이름 | 요청 크기 | 접근 방식 | 이전 이름 |
|---|---:|---|---|
| A1 | 4KiB | 논리 페이지 P1, P2, P3 순서로 전체 읽기 | A1 |
| A2 | 4KiB | P1, P3, P2처럼 3개씩 순서를 바꿔 전체 읽기 | A2 |
| **B** | **64B** | **P1의 offset 0, 64, …, 4032를 모두 읽고 P2로 이동** | 신규 |
| C1 | 64B | P1, P2, P3 각 페이지의 시작 64B만 읽기 | B1 |
| C2 | 64B | P1, P3, P2 각 페이지의 시작 64B만 읽기 | B2 |
| C3 | 64B | P1, P3, P1의 offset +64B, P2 순서로 읽기 | B3 |

P 한 개는 **4KiB 논리 페이지**이며 NAND 물리 페이지는 **16KiB**다. B는 하나의 패턴으로 정의했다. B1/B2라는 새 세부 패턴은 추가하지 않았다. A2/C2는 인접한 3개 페이지의 국소 순열이며 전체 주소 공간의 균등 난수 패턴이 아니다.

## 새 B의 의미

```text
P1: 0, 64, 128, …, 4032    64B 요청 64개
P2: 0, 64, 128, …, 4032    64B 요청 64개
P3: …
```

A1은 4KiB 요청 1개, B는 64B 요청 64개로 같은 4KiB 데이터를 소비한다. C1은 시작 64B만 소비하고 다음 페이지로 이동한다. B의 긴 스트림은 16KiB 물리 페이지에 패킹된 유효 데이터를 모두 소비하지만, 관측 경계나 버퍼 재출력 때문에 실측 Host/NAND 비율이 항상 정확히 100%라고 가정하지 않는다.

NAND tR, 16KiB 출력 단위, Plane당 page buffer 1개, Controller buffer의 기존 수명, Port 내부 in-order와 요청당 lookup/QD 차감은 유지한다. 항상 buffer hit 또는 물리 페이지당 tR 한 번을 강제하지 않는다.

QD512/Port에서 A의 미완료 payload 상한은 2MiB/Port, B/C는32KiB/Port다. B의 인접한64개 요청이 하나의4KiB 논리 페이지에 모이므로, 동일 QD만으로 동일한 NAND 병렬성을 가정할 수 없다. `--per-port`는 Host 요청 수다. 같은 논리 데이터 범위를 비교하려면 B 요청 수를 A1의64배로 설정한다.

## 구현과 실행

현재 진입점은 [workloads.py](../znand/workloads.py)다. 일반 실행 CLI는 현재 이름을 사용한다. 기존 `--pattern B1/B2/B3`는 경고와 함께 C1/C2/C3로 해석하고 결과 JSON에 현재 이름·요청 이름·schema를 남긴다. 새로운 B는 `--pattern B`다.

```sh
# 유한 요청열의 동작 확인. per-port는 64B 명령 개수다.
python3 -m znand.run --pattern B --per-port 4096 --out results/local/B_smoke
python3 -m znand.run --pattern C1 --per-port 4096 --out results/local/C1_smoke

# 기존 A1의 64Plane·8MiB·QD512·4KiB stripe·PF OFF 설정으로 지속 부하 실행
python3 -m znand.stream64 --pattern B \
  --config results/znand/saturation/profiles/A1_b8_q512.json \
  --out results/local/B_b8_q512
python3 -m znand.stream64 --pattern C1 \
  --config results/znand/saturation/profiles/A1_b8_q512.json \
  --out results/local/C1_b8_q512
```

지속 부하 CLI는 현재4 Port 기준으로 200µs 초기 구간 제외·고정2ms·최고 연속500µs를 측정한다. 주소 영역 크기는 snapshot의 기존 영역 크기를 우선 사용하며 도메인 끝에서 wrap하지 않는다. 결과에는 실제 outstanding·완료 요청 수·NAND 전송량·tR 종류별 횟수를 기록한다. B의 정식 QD별 성능 측정은 [새 B 성능 보고서](16_b_sequential_performance_ko.md)에 정리했다. 기존 약4GB/s는 C1/C2 결과이며 B의 성능으로 재사용하지 않는다.

## 이전 자료와 결과의 읽는 법

고객 원문 질문, 과거 이미지 전사, 기존 raw CSV/JSON·파일명·source hash는 당시 표기를 보존한다. 그 안의 **B1/B2/B3는 현재 C1/C2/C3**다. 과거 실험 모듈의 `model.workload()`와 `PartialReadSimulator`도 결과 재현을 위해 기존 이름을 유지한다. 새로운 실행은 `znand.workloads`와 `znand.stream64`를 사용한다.

- [C1/C2 현재 명칭으로 제공한 기존 30개 결과](../results/znand/workloads_v2/partial_saturation.csv)
- [이름 대응과 원자료 해시](../results/znand/workloads_v2/labels.json)
- [최신 발표 자료와 설명](14_performance_key_items_ko.md)

30개 결과는 기존 숫자를 재실험 없이 재표시한 view다. `legacy_pattern`과 `legacy_name`을 남기며 새 B 결과 행은 없다. 기존 원시 결과와 참조 모델을 보존해 명칭 변경을 성능 개선으로 오해하지 않도록 한다.
