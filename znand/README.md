# 주소 기반 zNAND Read와 Prefetch 실험

기존 `axi_burst_sim.py`, `multiport_sim.py`, `deep_prefetch_sim.py`는 그대로 보존하고, 합의한 주소 배치와 부분 Read·재방문·page buffer를 표현하는 이벤트 모델을 추가했다. 시간 단위는 μs, 대역폭은 decimal GB/s, 저장 단위는 KiB/MiB다. 제품 RTL 또는 실제 NAND 사양의 검증을 대체하지 않는다.

현재 CA 정책의 적용 위치·선택 순서·우회 계수·패턴별 실행 설정은 [컨트롤러 스케줄링 적용점](../docs/12_controller_scheduling_ko.md)을 따른다. 아래 구현 기준 표의 `fifo`·8MiB 등 기본값과 평가 프로파일을 구분한다.

추가 옵션인 제한적 연속 PF 우선과 NAND Data 선두 우선은 [후속 스케줄링과 튜닝](../docs/13_controller_followup_ko.md)에 정리했다. 새 옵션의 기본값은 OFF이며, 단계별 비교는 `python3 -m znand.scheduling_sweep --workers 6`으로 실행한다. 과거 실험의 모델 해시가 다른 checkpoint는 이어 쓰지 않고 별도 `--out` 경로를 지정한다.

[92개 후속 실험 결과](../results/znand/scheduling_next/RESULTS_KO.md)에 따라 기존 패턴별 실행 프로파일을 유지한다. 새 PF/Data 정책은 opt-in 실험 옵션이다. `python3 -m znand.validate_scheduling`으로 결과·설정·선택 규칙·소스 해시를 함께 확인한다. 원본 모델의 기본값과 실험용 프로파일은 구분한다.

높은 QD의 성능 평가는 이후 [Host-only 기준선](../results/znand/pf_qd/RESULTS_KO.md)으로 분리했다. `prefetch=false`로 PF 자체를 끄고 Host 요청만 처리한다. 기존 `pf_ahead_limit=0`은 PF ON에서 Demand 추월 예외만 끈 설정이다. 같은 CA 정책의 [A1 Host-only](../results/znand/pf_qd/profiles/A1_host_only.json), [A2 Host-only](../results/znand/pf_qd/profiles/A2_host_only.json)를 제공하며, 기존 PF ON 설정은 대조군으로 보관한다. QD에 따른 자동 PF 전환은 구현하지 않았다.

[Host IF 256GB/s 가능성 검토](../results/znand/host_ceiling/RESULTS_KO.md)는 32/64Plane의 물리 공급 상한과 정적 L2P 배치 효과를 구분한다. `python3 -m znand.host_ceiling --workers 6`은 8개 신규 진단과 4개 기존 대조군을 검증한다. Region snapshot은 동일 8,192요청/port의 주소 범위만 포함하므로 요청 범위를 늘릴 때 매핑도 새로 생성해야 한다. 이 진단용 배치를 기본 실행 설정에 적용하지 않았다.

## 실행

Mac에서는 저장소 루트에서 `bash scripts/macos.sh setup`, `bash scripts/macos.sh smoke`, `bash scripts/macos.sh diagnostics`를 순서대로 실행한다. Python 3.10 이상을 사용하며 스크립트가 `.venv`를 직접 선택한다. 새 결과는 `results/local/`에 저장한다. 그래프는 `setup --plots` 후 `report`, 주소 배치는 `layout`으로 연다. 상세 절차는 [Mac 실행 안내](../docs/11_macos_run_ko.md)를 따른다.

이 저장소의 루트에서 실행한다. 최초 실행 위치는 `/Users/bagjunbeom/Downloads/NAND_Prefetch_Model`이었다. 모델과 sweep은 Python 표준 라이브러리만 사용한다. 보고서 그림 생성에는 기존 가상환경의 matplotlib을 사용한다.

```sh
python3 -m unittest test_znand test_znand_expansion -q
python3 -m znand.run --config znand/baseline.json --pattern B3 --per-port 2048 --out results/znand/single --trace
python3 -m znand.sweep --workers 4 --snapshot znand/mqsim/snapshot.json
python3 -m znand.report
```

`results/znand/full/RESULTS_KO.md`가 결과 보고서다. `sweep.csv`는 모든 설정별 결과, `cases.json`은 실행 입력, `saturation.csv`는 포화 탐색 요약이다. `single/requests.csv`와 `single/events.json`으로 개별 요청과 자원 이벤트를 추적할 수 있다.

## 구현한 기준

| 항목 | 구현 |
|---|---|
| Host | 활성 1~4port, 각각 512bit·1GHz, port 내부 strict in-order |
| 요청 | 64B 또는 4KiB, 요청당 lookup 1회·Outstanding 1개, 마지막 반환 시 해제 |
| Lookup | Port별 500ns, 500MHz·2파이프라인, 동시 slot 500개 |
| NAND | 기본 4channel × 8plane; 실험 확장 4channel × 16plane. Plane별 page buffer 1개 |
| 주소 | 4KiB 논리 영역, 16KiB 물리 페이지; 4KiB/16KiB channel 분산; Plane 순환 |
| Plane 내부 | E/O→SSL→Block→WL(420→0)→Group |
| tR | 최초·Group 20.69μs, Short 2μs, Mid 2.08μs, Long 12.16μs. Plane별 이력 |
| CA | Channel별 독립, Read 및 page-buffer 재출력에 각각 초기 가정 100ns |
| Data | Channel당 80.1125GB/s, 페이지 전체 16KiB 전송, turnaround 50ns |
| ECC | 기존 기본값 200ns 유지. 별도 처리량 제약 없는 고정 지연 |
| 중재 | 발행 가능한 Demand 우선, CA는 대기 순서, Data는 준비 순서 |
| Plane 점유 | CA부터 NAND 데이터 전송 완료까지. 같은 Plane의 다음 sensing은 이후 시작 |
| 내부 작업 | 평균 목표 15% 점유. 기본 100μs 주기·15μs, Plane별 seed 시차 |
| Buffer | 전체 공유 8MiB. 진행 중 Read 병합, 연결 응답 완료 시 해제. LRU 미도입 |
| Prefetch | 미래 요청을 아는 합성 후보. 정확도와 선행 시간, 미사용 후보 상한을 별도 설정 |
| 미사용 Prefetch | 공간 부족 시 ready 시각이 오래된 미사용 항목 폐기. 진행 중·연결 요청 보호 |

동일 page buffer에 유효 데이터가 있으면 추가 sensing 없이 재출력한다. 기존 controller buffer가 남아 있으면 그 데이터로 응답한다. 서로 다른 port 요청도 같은 물리 페이지면 Read를 병합하지만 각 Host 전송과 credit은 유지한다.

## 이번에 정한 추가 가정

1. **Die/LUN:** 기본 실행에서는 32개, 확장에서는 64개 Plane을 독립 array 자원으로 모델링한다. Die 전원·명령 수·multi-plane 동기 제약은 없다. MQSim 입력 geometry는 추출 목적이며 그 Die 제약을 본 모델에 가져오지 않는다.
2. **내부 작업:** 주기 점유가 기존 Read와 겹치면 해당 Read의 NAND 전송까지 완료한 후 내부 점유를 시작한다. 점유 동안 NAND page buffer 접근은 불가하지만 내용은 유지한다. CA/Data를 별도로 소비하는 GC 복사나 L2P 갱신은 포함하지 않는다. 실제 점유 비율을 결과에 기록한다.
3. **출력 비용:** Page buffer 재출력은 CA 100ns + 16KiB 전송 + turnaround + ECC다. 신규 Read의 별도 출력 CA는 Read CA에 흡수한 추상화다.
4. **Trace:** A2/B2는 1→3→2의 지역 순열, B3는 1→3→1의 다음 64B→2로 읽고 다음 세 페이지 묶음으로 이동한다. 최초 offset은 0, B3 재방문은 64다. 무한 반복으로 작은 작업 영역만 적중시키지 않는다.
5. **Prefetch:** 각 물리 페이지의 첫 요청 제시 시각보다 lead만큼 먼저 후보 생성. 정확도 1/.75/.5/.25, lead 1/5/10/25μs, 기본 미사용 예산 128개. 잘못 예측한 주소는 다른 Group의 실제 물리 주소로 구성한다. 정답 여부로 즉시 폐기하지 않는다. 같은 채널·Plane에서 오예측이 발생하는 보수적 경쟁 조건이다.
6. **부하:** 기본은 port당 요청량 고정이며 총 요청량 고정 실험을 추가했다. 요청은 반환 경로의 명목 속도로 제시되고, Outstanding·AR·버퍼 제한에 의해 수락이 지연될 수 있다. Offered와 accepted 시간을 모두 남긴다.
7. **Cold 상태:** 각 실행은 빈 controller buffer와 초기 NAND 이력으로 시작한다. Prefetch ON은 첫 요청 이전에 데이터를 준비할 수 있다. Host 측정 구간과 사전 NAND 작업을 포함한 구간의 처리량을 함께 출력한다.

## 버퍼 진행성 보호 구현

선두 요청용 여유 공간만 동적으로 남겨 두면, 이전 선두의 페이지를 후속 요청이 계속 고정하는 경우 순환 대기가 발생할 수 있다. 이번 구현은 **Host 수락 시 물리 페이지 공간을 공유 예약**하는 보수적인 admission 제어를 사용한다. 동일 페이지 요청은 예약을 공유하고, 새로운 페이지를 위한 공간이 없으면 AR 수락을 늦춘다. 새 선두 요청이 없는 port에도 한 페이지분을 보호한다.

이는 기존 'NAND 발행 직전 공간 예약'보다 이른 용량 예약이다. 결과의 buffer_peak_pages는 도착한 payload만이 아니라 예약 공간도 포함한다. 모델은 주소 변환 결과를 admission bookkeeping에 사용할 수 있다고 가정하며, 실제 장치에서 이 정보가 그 시점에 가능한지 확인이 필요하다. Lookup 500ns는 여전히 적용한다. 모든 수락 요청의 공간이 확보되므로 후속 요청이 선두에 필요한 공간을 빼앗는 교착을 피한다. 요청 수락 지연과 in-flight 수를 함께 평가한다.

## MQSim 배치 사용

`mqsim/precondition_raw.csv`는 업스트림 revision `51f0f2d3fed92d88ef4a0fa61a38024b07bf9d16`의 사전 조건화 매핑을 추출한 파일이다. 원본 주소값을 새로 만들어 MQSim 출력이라고 표시하지 않았다. 추출 전용 모드는 매핑 할당 이후 파일을 닫고 종료하며, 본 workload 성능을 MQSim에서 측정하는 단계가 아니다.

- Geometry: 4channel, channel당 1chip, chip당 4die, die당 2plane, plane당 32block, block당 64page, page 16KiB.
- 초기 점유율 75%, streaming 합성 workload. 단일 seed 예시이며 실제 SSD의 aging 상태를 보장하지 않는다.
- 전체 페이지가 유효한 행만 사용한다. 45,711개 중 45,708개를 변환하고 나머지 3개는 제외했다.
- 유효 LPA를 정렬하여 dense packed-slot index에 대응한다. channel과 plane은 보존하고, block/page를 plane-local 선형 인덱스로 변환해 zNAND decoder로 재해석한다.
- 따라서 snapshot은 **MQSim 유래 재패킹 배치**이며 원본 LPA 공간·물리 구조와 동일하지 않다. 물리 점유·배치 민감도 비교에 사용한다. 본 모델은 유효/무효 블록의 GC 동작을 재생하지 않는다.
- `export.patch`, XML, raw CSV, export log, `snapshot.json`의 revision과 SHA256을 보존했다.

재추출은 새 폴더를 지정한다. 기존 checkout을 덮어쓰지 않는다.

```sh
sh znand/mqsim/reproduce.sh /tmp/mqsim-znand-reproduction
```

## 후속 튜닝 우선순위

1. 합성 정확도 외에 **coverage·후보 발행량·선행 시간**을 독립적으로 조절하고 실제 예측기로 대체한다. Offered 기준 lead와 accepted 기준 lead 차이를 비교한다.
2. CA·Data 우선순위에 따른 Prefetch starvation을 보고 필요하면 aging을 추가한다.
3. 16KiB 전체 전송과 부분 출력, ECC 처리 단위·처리율, command packet 상세 비용을 비교한다.
4. Die/LUN 공유 제약, WL Jumping, page buffer 무효화 조건을 실제 정보로 보정한다.
5. 내부 점유 주기·동시성, 실제 GC 이벤트와 buffer 상태 영향을 확장한다. 85%를 추가 대역폭 감산으로 중복 적용하지 않는다.
6. L2P 사전 상태를 점유율·주소 편향·seed별로 확장하고, 실제 layout 정책을 보존하는 재배치를 비교한다.
7. Buffer admission 예약과 실제 L2P 가용 시점을 정교화한다. 작은 버퍼·공유 요청·in-order 조건의 진행성 테스트를 유지한다.
8. 동시에 발생한 Host 수락 경쟁은 고정 port 순서로 처리한다. 포화 시 port별 지연 편향과 물리 주소 순서에 영향을 줄 수 있으므로 round-robin admission과 비교한다.
9. Controller cache ON/OFF·LRU는 추후 검토한다. 64B channel 분산은 사용자 결정에 따라 계속 제외한다.

## 결과의 한계

기존 multiport 기본값은 128channel·128chip·chip당 6plane이며 전체 페이지 소비 흐름이었다. 이번 4channel·32plane·부분 Read 수치와 이전 공급 모델의 처리량을 직접 개선율로 비교하지 않는다.

최대 처리량은 지정한 유한 trace와 모델 가정에서 관측한 값이다. QD를 늘려도 개선되지 않는 구간과 더 긴 trace의 비교를 함께 보고하며, 실제 제품 최대 대역폭이라고 주장하지 않는다. Host/NAND bytes 비율은 중복 Host 요청을 포함하므로 유일 데이터 효율과 다르다. `mean_return_wait_us`는 Head-of-Line 대기뿐 아니라 정상적인 반환 직렬화도 포함한다.

## 독립 계산 검증

`python3 -m znand.validate_results`로 저장된 CSV의 처리량 상한·요청량·지연 분해·자원 점유를 다시 검사할 수 있다. `python3 -m znand.microbench`는 page buffer 재사용과 E/O·SSL·Block·WL·Group 전환 8개 조건을 분석식과 비교한다. 상위 Outstanding 추가 실험은 `python3 -m znand.extend`로 재실행한다.

## 관측 최고 조건 재실행

`observed_best/A1.json`부터 `B3.json`까지는 긴 trace의 4port 비교에서 관측한 최고 처리량 설정이다. 해당 유한 workload에서 고른 설정이며 다른 workload의 최적값을 보장하지 않는다.

```sh
python3 -m znand.run --config znand/observed_best/B3.json --pattern B3 --per-port 8192 --out results/znand/replay_B3
```

기존 실험은 기본·민감도 1,248개와 상위 Outstanding 240개, 총 1,488개다. 압축 배포본은 압축을 푼 루트에서 실행한다. 기존 모델 테스트 28개에 확장 테스트 7개를 추가했으며 `python3 -m unittest test_znand test_znand_expansion -q`로 35개를 실행한다. 84개 통과 기록은 기존 저장소 테스트를 포함한 결과다. 그림을 다시 생성하려면 matplotlib이 설치된 Python으로 `python3 -m znand.report`를 실행한다.

## Host IF 진단과 64Plane 확장

`Config.planes`는 채널당 Plane 수이며 8 또는 16을 지원한다. 기본값과 기존 1,488개 결과는 8을 유지한다. 16에서는 busy·sensing 이력·page buffer·maintenance 자원이 64개가 되지만 CA/Data는 여전히 4개 channel에서 공유한다. Host 반환 순서와 Controller buffer 크기를 자동으로 변경하지 않는다.

같은 A2 요청열에서 버퍼, 내부 점유, tR, Plane 수를 비교하는 추가 진단 6개를 다음과 같이 실행한다. 모델 동작을 바꾸지 않는 별도 계측으로 실제 발행 q, port 전환, 버퍼 점유와 선두 대기 중 후속 ready 구간을 기록한다.

```sh
python3 -m znand.diagnostics
python3 -m znand.diagnostics --cases 64plane_8MiB 64plane_32MiB --out results/znand/replay_64plane
```

기본 진단 조건은 A2, 4port, 16KiB stripe, port당 4,096개 4KiB 요청, QD 2,048, Prefetch ON, port 간 주소 중첩 0%다. 결과 폴더의 `cases.json`은 전체 입력, `results.json`은 상세 계측, `sweep.csv`는 독립 검증용 행, `summary.csv`는 비교표, `manifest.json`은 모델 해시와 검증 기록이다. 실행 시간은 환경에 따라 달라진다.

16Plane/channel에서 외부 snapshot을 사용하려면 `model_geometry: {"channels": 4, "planes_per_channel": 16}` metadata가 일치해야 한다. 기존 32Plane MQSim snapshot에 metadata만 붙여 64Plane 배치로 간주하지 않는다. 기존 8Plane/channel의 metadata 없는 snapshot은 계속 지원한다.

- [Host IF 병목 원인과 6개 진단 해석](../docs/08_host_if_bottleneck_ko.md)
- [NAND 주소 비트와 물리 Die 구성 예](../docs/09_plane_expansion_layout_ko.md)
- [추가 결과와 설정](../results/znand/diagnostics_2026-10-09/)

## 연속 물리 주소 우선 CA 스케줄링

`Config.ca_policy`는 `fifo`(기존 기본값)와 `locality`를 지원한다. Locality는 같은 Plane의 이미 발행 가능한 요청에서 page buffer 재사용 또는 같은 Group의 q+1을 우선한다. Demand 우선순위와 port 내부 in-order 반환을 유지하며, 후보가 없으면 기존 요청을 발행한다. 미도착 주소를 기다리거나 Host 요청열을 바꾸지 않는다.

`locality_max_bypass=8`은 가장 오래된 해당 우선순위 요청을 연속 우회할 수 있는 최대 CA 선택 횟수다. `locality_age_us=1000`을 넘게 기다린 oldest 요청도 우선한다. Busy·maintenance를 포함한 절대 응답시간 보장은 아니다. Prefetch starvation은 기존 Demand 우선 원칙의 별도 튜닝 대상이다.

`python3 -m znand.locality_sweep`와 `python3 -m znand.locality_report`로 평가를 재현한다. 결과는 `results/znand/locality/`에 기록한다. 동일 실험을 중복 실행하지 않도록 진행 중인 프로세스를 먼저 확인한다. 이번 비교는 버퍼·예약 정책과 Host 입력을 그대로 유지하고 CA 선택만 바꾼다.

## Locality 정책의 32~64MiB 버퍼 비교

```sh
python3 -m znand.buffer_growth --workers 8
python3 -m znand.buffer_growth_report
```

4port·32Plane·PF ON·port당 8,192개 요청을 유지하고 공유 버퍼를 32/40/48/56/64MiB로 바꾼다. A1(4KiB stripe)과 A2(16KiB stripe)는 QD2,048/4,096/8,192를 각각 비교한다. B1/B2(4KiB stripe), B3(16KiB stripe)는 QD8,192를 고정한다. 총 45개 조건이며 동일 모델·설정의 기존 32MiB 결과 6개를 재사용한다.

결과는 `results/znand/buffer_growth/`에 저장한다. 중단 후 재실행은 모델 해시와 저장된 조건을 검증하고 남은 조건만 실행한다. 여러 프로세스에서 이 실행기를 동시에 실행하지 않는다. 물리 용량과 reservation 한도는 여전히 결합된 모델이다. 처리량뿐 아니라 실제 예약 peak, 수락 실패 횟수, Long sensing 비율도 [결과 보고서](../results/znand/buffer_growth/RESULTS_KO.md)에서 확인한다.

이 과거 버퍼 비교의 실행기는 `reference_model_17e7d52.py`에 보존한 당시 모델을 사용한다. 이후 CA 정책 추가에 영향을 받지 않고 기존 checkpoint와 결과를 재현한다.

## Port 선두 요청 대기를 고려한 CA 정책

`ca_policy=head_locality`는 `locality`에 선두 요청 우선을 추가한다. 대기는 실제 port FIFO 선두가 된 시각과 lookup 완료 시각 중 늦은 시각부터 센다. `head_wait_us`(기본 12.16μs)를 넘고 아직 CA 대기 중인 페이지가 우선 후보가 된다. 이미 sensing·전송 중인 작업은 선점하지 않는다. 같은 페이지를 여러 port가 기다리면 가장 오래 기다린 선두를 기준으로 선택한다.

Plane 내부에서는 기존 age·연속 우회 한도 보호를 먼저 적용하고, 그다음 오래 기다린 선두, page buffer 재사용/연속 q+1, oldest 순으로 선택한다. 같은 channel의 발행 가능한 Plane 사이에서도 선두 후보를 우선하되, age 한도에 도달한 Demand가 있으면 이를 먼저 처리한다. 발행 가능한 선두 우선 후보가 없으면 기존 순서를 유지한다. 선두 우선에 따른 우회도 기존 우회 한도에 포함한다. Busy·maintenance 등까지 포함한 절대 대기시간 보장은 아니다.

Host 요청열·수락 및 버퍼 예약·lookup·NAND Data 중재·외부 port 내부 in-order는 유지한다. 기본 `fifo` 및 기존 `locality` 설정의 동작도 유지한다. `count_ca_selection_head`는 선두 우선 규칙으로 선택한 횟수이며, 해당 페이지가 기존 정책에서도 선택됐을 가능성을 포함한다.

```sh
python3 -m unittest test_znand test_znand_expansion test_znand_locality test_znand_head -q
python3 -m znand.head_sweep --workers 8
python3 -m znand.head_report
```

A1/A2·32MiB·QD2,048/port에서 우회 4/8/16/32회 각각에 대해 기존 정책과 선두 대기 0/12.16/48.64μs를 비교한다. A1/A2 처리량 비율의 기하평균으로 선두 우선 후보 하나를 고정한 뒤, B1/B2/B3와 더 긴 A1/A2 요청열에서 확인한다. 처리량 선택이 p99 개선을 보장하지 않으므로 둘 다 보고한다. 중간 결과가 있으면 모델·실행기 해시와 저장 조건을 검증하고 이어서 실행한다. [결과 보고서](../results/znand/head_locality/RESULTS_KO.md)에 기존 우회 8회 대비와 같은 우회 한도 대비를 따로 기록한다.

47개 비교 후 [실행용 프로파일](../results/znand/head_locality/profiles/)을 저장했다. A1은 `head_locality`·우회32·대기48.64μs, A2/B1/B2/B3는 `locality`·우회32다. A2는 긴 요청열에서 선두 우선의 추가 효과가 없었고 B계열은 선두 우선으로 성능이 낮아졌다. 패턴별 설정을 명시하며 모델이 workload를 자동 분류하지 않는다. `znand.run`의 요청별 CSV에는 실제 선두가 된 시각 `head_since`도 기록한다.
