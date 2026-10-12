# NAND 구조: DIE → Channel → Plane

2026-10-12 사용자 확인 구조를 모델에 반영했다.

```text
전체 NAND
├─ DIE 0: Channel 0 [Plane 0–3], Channel 1 [Plane 0–3]
├─ DIE 1: Channel 0 [Plane 0–3], Channel 1 [Plane 0–3]
├─ DIE 2: Channel 0 [Plane 0–3], Channel 1 [Plane 0–3]
└─ DIE 3: Channel 0 [Plane 0–3], Channel 1 [Plane 0–3]

4 DIE × 2 Channel/DIE × 4 Plane/Channel = 32 Plane
```

## 기존 구조와 달라진 점

| 항목 | 기존32Plane | 새32Plane |
|---|---|---|
| DIE 계층 | 정의하지 않음 | 4개 |
| 전체 Channel 수 | 4개 | 8개 |
| DIE당 Channel | 정의하지 않음 | 2개 |
| Channel당 Plane | 8개 | 4개 |
| 전체 Plane 수 | 32개 | 32개 |
| 외부에 표시하는 물리 주소 | Channel, Plane, q | DIE, DIE 내부 Channel, Plane, q |

Host Port 4개와 NAND Channel 8개는 별개의 자원이다. 특정 Host Port가 특정 DIE에 고정 연결된 구조를 추가하지 않았다. 주소 매핑 결과로 대상 DIE와 Channel이 정해진다.

스케줄러 내부의 전역 Channel 번호는 `die × 2 + local_channel`이다. DIE0은 CH0/1, DIE1은 CH2/3, DIE2는 CH4/5, DIE3는 CH6/7을 사용한다. 이는 내부 배열 인덱스이며, 각 DIE의 실제 Channel 이름은0/1이다. 서로 다른 DIE의 Channel0은 다른 자원이다.

## 채널별 독립 자원

현재 구현은 Channel마다 CA 경로1개와 Data 경로1개를 독립적으로 둔다. 따라서 같은 Channel의 네 Plane은 CA끼리, Data끼리 직렬화되고 서로 다른 Channel은 동시에 진행할 수 있다. 기존과 같이 CA와 Data는 별도 자원이다. Plane별 sensing 이력·page buffer·maintenance 상태도 각각 독립이다.

**DIE 내부 두 Channel의 CA·Data 경로가 서로 독립이라는 사용자 확인을 반영했다.** 다른 DIE의 채널 경로도 독립이며 전체8개 Channel을 각각 중재한다. 구조에서 지정하지 않은 별도의 DIE 공통 전력 제한이나 Die busy 제약은 추가하지 않았다.

채널당 `io_gbps=80.1125`, tR, CA·ECC·lookup 지연, 가용률, Host IF, 공유 Controller buffer, 고정 Port 수락 정책은 그대로다. 총 Channel 수는 늘었으므로 과거 처리량을 새 구조에 그대로 옮길 수 없다. 이번 작업은 구조 및 기능 검증이며, 새 구조의 최대 처리량이나 최적 Data placement·QD를 찾는 실험은 아니다.

## 실행과 과거 결과 재현

```sh
# 새 구조가 기본인 일반 실행
python3 -B -m znand.run --pattern A1 --per-port 2048 --trace --out results/local/die32-a1

# 구조를 명시한 설정 파일로 실행
python3 -B -m znand.run --config configs/die4_channel2_plane4.json --pattern A2 --trace --out results/local/die32-a2
```

Python에서 새 구조는 다음과 같이 생성한다.

```python
from znand.model import Config, Mapper

config = Config.die32(outstanding=512, buffer_pages=512)
mapper = Mapper(config)
physical_address, offset = mapper.map_hierarchical(2 * 4096)
assert physical_address == (1, 0, 0, 0)  # DIE1, local CH0, Plane0, q0
```

과거 실험 스크립트의 `Config()`는 기존4×8, `Config(planes=16)`은 기존4×16을 유지한다. 저장된 config를 `--config`로 주면 해당 geometry를 그대로 사용하며 자동 변환하지 않는다. `dies=0, channels_per_die=0`은 DIE 수가 물리적으로0이라는 뜻이 아니라 과거 모델에서 DIE 계층을 정의하지 않았다는 표시다.

새 config의 `channels=8`은 전체 Channel 수, `planes=4`는 Channel당 Plane 수다. `dies=4, channels_per_die=2`와 일치하지 않는 조합은 거부한다. 신규 일반 CLI 기본값을 변경했지만 과거 측정 모듈의 조건과 저장 결과는 변경하지 않았다.

## 주소 배치와 snapshot

4KiB stripe는 전역 Channel 0~7을 순환한다. 같은 Channel로 돌아올 때마다16KiB 페이지 안의 offset0/4/8/12KiB를 채우고, 그다음 Plane을 순환한다. 16KiB stripe는 완전한 물리 페이지 단위로 여덟 Channel을 순환한다. Plane 내부의 E/O·SSL·Block·WL·Group 순회와 `q`의 의미는 유지한다.

새 snapshot에는 전체 계층을 명시해야 한다.

```json
{
  "page_bytes": 16384,
  "model_geometry": {
    "channels": 8,
    "planes_per_channel": 4,
    "dies": 4,
    "channels_per_die": 2
  },
  "address_format": "die_channel_plane_page",
  "mapping": {"0": [3, 1, 2, 9]}
}
```

위 예시는 packed page0을 DIE3, local CH1, Plane2, q9로 옮기는 최소 예시다. 실제 실행에서는 접근하는 모든 packed page를 포함해야 한다. `address_format`을 생략하거나 `global_channel_plane_page`로 주면 기존처럼 전역 Channel·Plane·q 세 좌표를 사용한다. 새 구조에 과거4×8/4×16 snapshot이나 계층 정보가 없는 snapshot을 연결하면 거부한다.

`znand.host_ceiling.region_snapshot()`은 새 구조의 계층 metadata도 저장하며, Channel과 페이지 내 offset을 보존한다. 이 생성기의 영역별 Plane 배치는 사용할 수 있지만 이번 구조 변경만으로 새 배치의 성능 최적성을 검증한 것은 아니다.

## 출력과 검증

일반 실행의 `result.json`에는 `nand_topology`가 추가된다. `events.json`의 물리 key가 있는 이벤트에는 DIE·DIE 내부 Channel·Plane·q를 나타내는 `physical_address`가 추가된다. 기존 `key`는 내부 전역 Channel 형식으로 유지한다. 지속64B 실행인 `znand.stream64`도 새 config를 받을 수 있으며 결과에 topology를 기록한다.

```sh
python3 -B -m unittest discover -p 'test_znand*.py'
python3 -B scripts/die_layout_smoke.py --out results/local/die-layout-smoke
```

기존82개 테스트와 새9개 테스트를 통과했다. 새 테스트는32Plane의 전체 페이지 패킹, DIE 경계 주소, 독립8채널의 동시 CA/Data 진행, 같은 Channel의 직렬화, DIE 간 page buffer 독립성, 부적합 snapshot 거부, 영역별 배치 불변조건, 버퍼 압박에서의 여섯 워크로드 진행·in-order, 신규 CLI 기본값과 과거 config 보존을 확인한다. [기능 실행 결과](../results/znand/die_layout_smoke/)는 짧은 유한 요청열의 smoke이며 성능 상한 측정으로 해석하지 않는다.

## 후속 성능 측정

구조 검증 후 [18개 조건의 지속 처리량 측정](19_die32_performance_ko.md)을 완료했다. 영역별 배치와 적정 QD에서 A1/A2/B는 약185.82GB/s이며, 새 구조의 결과는 기존64Plane 결과와 별도로 보존했다.
