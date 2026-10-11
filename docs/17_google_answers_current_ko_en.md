# Google zNAND 질의에 대한 최신 실험 기준 답변

2026년 10월 11일 기준. Google의 영어 질문 1~4에 대해 현재 모델과 저장된 실험 결과로 답한다. 4KiB 전체 읽기는 약 255GB/s, 각 4KiB 영역의 64B만 소비하는 부분 읽기는 약 4GB/s다. 페이지를 64B씩 끝까지 읽는 추가 실험은 충분한 outstanding에서 약 255GB/s에 도달했다. 이 차이는 내부 전송 데이터의 활용률과 동시에 보이는 물리 페이지 수로 설명된다.

수치는 모델의 조건부 예측이며 제품 사양이나 하드웨어 실측값이 아니다. 최신 포화 실험은 처리량을 측정했다. Google이 요청한 UCIe 발행부터 반환까지의 요청별 end-to-end latency와 두 IO 모드의 차이는 아직 완성된 측정값으로 제시할 수 없다.

## 답변에 사용하는 조건과 이름

| 항목 | 조건 |
|---|---|
| 구조 | 독립 4Port가 4Channel을 공유, Channel당 16Plane, 총 64Plane |
| 페이지 | Host 논리 영역 4KiB, NAND 물리 페이지 16KiB, Plane당 page buffer 1개 |
| Controller buffer | 공유 8MiB, 연결된 요청이 모두 반환되면 항목을 해제하는 임시 버퍼 |
| Host 반환 | Port당 512bit·1GHz, payload 상한 64GB/s, 4Port 합산 256GB/s |
| 내부 조건 | PF OFF, availability 85%, 기존 Short/Mid/Long/First/Group tR 유지 |
| 순서 | Port 내부는 요청 수락 순서로 반환, Port 간 전역 순서는 없음 |
| 배치 | 정적 논리 주소 영역별 Plane 배치, 모든 영역이 4Channel을 사용 |
| 관측 | 계속 요청을 공급, 초기 200µs 제외, 200~2,200µs 고정 2ms 평균 |

원문의 B-1/B-2/B-3는 현재 모델의 C1/C2/C3다. 현재의 새 B는 페이지 내부를 64B씩 끝까지 읽는 추가 패턴이다. 아래 고객 답변에서는 원문 이름을 우선한다. 원문의 KB는 모델에서 KiB로 해석했고 GB/s는 십진 단위다.

## 1 읽기 지연과 접근 패턴

### 지연 분해

현재 모델의 요청 흐름은 `요청 제시 → 수락 대기 → lookup → NAND 발행 대기 → CA → sensing → NAND Data 대기·전송 → ECC → Port 내 순서·반환 대기 → Host 전송 완료`다. 다른 요청의 처리 단계와 겹칠 수 있으므로 전체 구간 처리량의 역수를 개별 요청 지연으로 사용하지 않는다.

| 구성 요소 | 현재 모델 값 또는 동작 | 답변 범위 |
|---|---|---|
| 수락 전 대기 | QD·공유 버퍼·Port 간 수락 경쟁에 따라 발생 | 고정 지연이 아님 |
| 조회 | 요청당 0.500µs, 별도 pipeline 대기 가능 | 모델 입력값 |
| NAND 명령·주소 | 0.100µs, channel CA 자원 대기 가능 | 모델 입력값 |
| NAND sensing | 아래 tR 표 | 물리 접근 관계에 따라 선택 |
| NAND 전송 | 16KiB / 80.1125GB/s + turnaround 0.050µs = 약 0.254512µs | 64B 요청에도 전체 16KiB 출력 |
| ECC | 0.200µs | 고정 처리 지연 추상화 |
| 준비 후 반환 대기 | Port 내 선행 요청·Host 반환 경로에 따라 발생 | 고정 지연이 아님 |
| Host payload 전송 | 64B는 0.001µs, 4KiB는 0.064µs | UCIe 패킷·adapter·credit 비용 미포함 |

| tR 종류 | 값 | 모델의 적용 조건 |
|---|---:|---|
| First | 20.69µs | 해당 Plane에서 최초 sensing |
| Short | 2.00µs | 같은 Group의 다음 물리 페이지 q+1, 목적지 q가 홀수 |
| Mid | 2.08µs | 같은 Group의 다음 물리 페이지 q+1, 목적지 q가 짝수 |
| Long | 12.16µs | 같은 Group의 비연속 물리 페이지로 이동 |
| Group | 20.69µs | 다른 Group으로 이동 |

Plane page buffer hit이면 sensing을 생략한다. Controller buffer에 준비된 데이터가 남아 있으면 NAND 재전송까지 생략할 수 있다. 이것은 항상 hit하도록 설정한 캐시가 아니다.

**계산 예시:** Controller buffer와 Plane page buffer에 목표 데이터가 없고 모든 자원 대기가 0이며 Short tR가 적용되면, 모델에 포함된 직렬 경로 합은 4KiB 약 **3.119µs**, 64B 약 **3.056µs**다. 최초 접근에는 Short 대신 First가 적용된다. 이 값은 설정값의 단순 합이며 포화 부하에서 측정한 평균·p99 또는 UCIe end-to-end latency가 아니다.

고객에게 제시할 실제 지연에는 UCIe 요청·응답 경로를 추가하고, 발행 시점을 제시와 수락 중 무엇으로 볼지 및 반환 완료를 첫 데이터와 마지막 데이터 중 무엇으로 볼지 일치시켜야 한다. 현재 반환 완료 기준은 마지막 데이터다. 최신 64Plane 포화 조건의 패턴별 평균·p99 지연 분해는 별도 계측이 필요하다. 과거 32Plane 유한 요청열의 지연값을 최신 조건에 옮겨 쓰지 않는다.

근거: [모델 구현](../znand/model.py), [tR와 구조 설명](14_performance_key_items_ko.md), [과거 조건의 지연 계측](10_google_model_answers_ko.md).

### 원문 패턴별 현재 답변

아래 값은 **Host 유효 처리량**이며 개별 요청 지연이 아니다.

| Google 원문 | 현재 이름 | 요청 형태 | QD/Port | 고정 2ms 평균 GB/s |
|---|---|---|---:|---:|
| A-1 | A1 | P1→P2→P3, 각각 4KiB | 512 | 255.366 |
| A-2 | A2 | P1→P3→P2, 각각 4KiB | 512 | 255.058 |
| B-1 | C1 | P1→P2→P3, 각 페이지 시작 64B | 512 | 3.995 |
| B-2 | C2 | P1→P3→P2, 각 페이지 시작 64B | 512 | 4.001 |
| B-3 | C3 | P1→P3→P1의 다음 64B→P2 | — | 최신 64Plane 지속 부하 수치 미확보 |
| 추가 비교 | 새 B | P1의 64B×64개 후 P2, 반복 | 512 | 31.457 |
| 추가 비교 | 새 B | 위와 동일 | 16,384 | 241.611 |
| 추가 비교 | 새 B | 위와 동일 | 32,768 | 255.335 |

A1/C1/C2/새 B는 4KiB stripe와 head_locality를 사용한다. A2 대표값은 16KiB stripe와 locality다. 따라서 A1/A2 수치의 차이를 접근 순서 하나만 바꾼 대조 결과로 설명하지 않는다. A1/C1/새 B는 QD 차이를 별도로 표시하면 장치 설정과 배치가 같은 비교다. A2와 원문 B-2는 3개 페이지의 국소 순열이며 전체 주소 공간의 균등 난수 읽기를 대표하지 않는다.

**A-1과 A-2:** 현재 배치와 스케줄링, 충분한 병렬성이 있는 각 대표 구성에서 두 패턴 모두 Host 상한에 근접했다. 논리 페이지 순서가 바뀌어도 같은 Plane에서의 실제 sensing 순서는 연속일 수 있다. 따라서 이름에 Random이 있다는 이유만으로 매 요청에 Long tR를 부여하지 않는다.

**B-1과 B-2:** NAND는 물리 16KiB를 전송하지만 패킹된 4개의 4KiB 영역에서 각각 64B만 사용한다. 유효 데이터는 256B, 명목 활용률은 1/64다. 대표 조건의 내부 NAND 전송률은 각각 256.778/256.991GB/s인데 Host 유효 처리량은 3.995/4.001GB/s다. 해당 관측 창에서 Long tR 비율은 둘 다 0%다. Long tR를 줄이는 것만으로 이 활용률 손실을 해결할 수 없다. 현재 전체 페이지 출력 가정에서 Data 전송과 turnaround만 고려한 공급 상한은 약 257.496GB/s이고, 이를 1/64로 환산하면 약 4.023GB/s다. 짧은 구간에는 미리 준비된 버퍼 데이터의 방출 때문에 이 값보다 높게 보일 수 있다.

**B-3:** 재방문 비용은 데이터가 남아 있는 위치에 달려 있다.

1. Controller 항목이 남아 있으면 기존 작업에 합류하거나 준비된 데이터를 재사용한다. 데이터가 아직 준비되지 않았다면 기존 읽기 완료를 기다린다.
2. Controller 항목은 해제됐어도 해당 Plane의 page buffer가 같은 물리 페이지를 유지하면 sensing 없이 16KiB를 다시 출력한다.
3. 같은 Plane의 다른 페이지 sensing으로 page buffer가 교체됐다면 다시 sensing한다. 직전 물리 페이지와의 관계에 따라 Long 또는 Group 등의 tR가 적용된다.

P1→P3→P1이라는 논리 순서만으로 page buffer 교체를 확정할 수 없다. 4KiB stripe 예에서는 P1과 P3가 다른 channel에 있으므로 P3 읽기 자체가 P1의 Plane page buffer를 덮어쓰지 않는다. 모델은 재방문 P1의 offset을 +64B로 선택했지만, Google 원문에는 재방문 offset이 지정되어 있지 않다.

**추가한 페이지 내부 연속 읽기:** 새 B는 64B 요청을 사용해도 전체 페이지 데이터를 소비하므로 충분한 QD에서 255.335GB/s에 도달했다. A1의 QD512×4KiB와 새 B의 QD32,768×64B는 모두 Port당 2MiB의 미완료 payload 상한이다. QD는 미완료 요청 수이며 AXI ID 개수가 아니다. 큰 QD의 요청 메타데이터 비용은 8MiB payload 버퍼에 포함하지 않았다. 새 B의 QD128 조건에서는 임시 버퍼 해제 후 16KiB 재출력이 발생해 read amplification이 4배였으므로, 페이지를 끝까지 읽는다고 항상 한 번의 내부 전송만 필요한 것은 아니다.

**IO 모드 비교:** Command-based와 Memory-semantic에 대한 서로 다른 요청·완료 경로를 구현하지 않았다. 모드 간 latency가 같거나 다르다는 결론은 현재 결과로 낼 수 없다.

근거: [A 지속 부하](../results/znand/saturation/RESULTS_KO.md), [원문 B-1과 B-2 지속 부하](../results/znand/partial_saturation/RESULTS_KO.md), [새 B 측정](16_b_sequential_performance_ko.md), [명칭과 offset 정의](15_workload_naming_ko.md), [A1 및 C1과의 설정 대조](../results/znand/b_sequential/reference_validation.json).

## 2 주소 정렬과 Burst 및 흐름 제어

### 주소 정렬

모델은 64B 요청의 64B 정렬 주소와 4KiB 요청의 4KiB 정렬 주소를 허용한다. 새 B의 offset 64, 128, …, 4032 접근으로 4KiB 경계에 놓이지 않은 64B 주소도 평가했다. 따라서 모델상의 읽기는 모두 4KiB 시작 주소를 요구하지 않는다. 실제 zNAND 인터페이스의 native 지원 여부는 제품 명세에서 확인해야 한다.

### Burst 길이와 작은 요청의 비용

실제로 실행한 요청 길이는 64B와 4KiB다. 모델의 입력 검증도 두 길이만 허용하므로 128B·192B 등 모든 64B 배수를 지원한다고 답할 수 없다. Burst의 4KiB 경계 통과, 최대 길이, ECC 및 column 출력 단위도 제품 확인 대상이다.

작은 요청의 성능 부담은 세 가지다. 요청마다 lookup과 outstanding 슬롯을 사용하고, 물리 16KiB 전체 출력에 비해 사용하는 데이터가 적을 수 있으며, 작은 응답이 빠르게 소진되면 Port 선두의 미준비 요청에 더 빨리 도달한다. 새 B가 충분한 QD에서 Host 상한에 도달한 결과는 작은 요청 크기만으로 최대 처리량이 낮아지는 것은 아니라는 근거다. 필요한 QD와 실제 구현 비용은 함께 검토해야 한다.

### Back-pressure

모델은 outstanding이나 공유 버퍼가 부족할 때 요청 수락을 지연시킨다. 응답은 Port별 순서와 전송 시간으로 처리하며 burst 중간의 RREADY deassert, adapter FIFO, UCIe credit 소진·회복을 cycle 단위로 구현하지 않는다. 따라서 임의 cycle에서 멈출 수 있는지, burst 경계에서만 가능한지, 멈춘 뒤 이미 전송 중인 데이터를 어디에 저장하는지는 이 실험으로 확정할 수 없다. AXI 측 handshake와 UCIe 링크 측 흐름 제어의 대응 관계를 실제 adapter 설계와 함께 확인해야 한다.

근거: [요청 검증과 반환 구현](../znand/model.py), [새 B의 요청 크기와 QD 비교](16_b_sequential_performance_ko.md).

## 3 주소 Interleaving과 물리 배치

### 색상 블록과 번호의 의미

삼성 원본 슬라이드의 색상 블록 크기와 번호별 die 분포는 원본 주소 매핑 정의 없이는 확정할 수 없다. 현재 모델에서는 P1 등의 논리 페이지 하나가 4KiB이고, 네 논리 영역을 물리 16KiB 페이지 하나에 패킹한다. 하나의 4KiB 영역 자체를 여러 die에 나눠 저장하는 방식은 사용하지 않는다. Die/LUN의 별도 공유 자원은 구현하지 않았다.

### 4KiB Interleaving 예시

아래는 현재 4KiB stripe의 한 논리 주소 영역 시작에서 확인한 패킹이다. 각 행의 P 네 개가 해당 channel의 **한 물리 16KiB 페이지**를 구성한다. P 하나는 4KiB다.

| Channel | 물리 offset 0 | 4KiB | 8KiB | 12KiB |
|---|---|---|---|---|
| CH0 | P1 | P5 | P9 | P13 |
| CH1 | P2 | P6 | P10 | P14 |
| CH2 | P3 | P7 | P11 | P15 |
| CH3 | P4 | P8 | P12 | P16 |

연속 논리 페이지의 channel은 CH0→CH1→CH2→CH3로 돌아간다. 모든 Port가 주소를 따라 네 channel에 접근할 수 있다. Port와 channel은 1대1 연결이 아니다. 다만 현재 Host 반환 경로가 Port당 64GB/s이므로 한 Port가 네 NAND channel을 활용한다고 해서 그 Port의 Host 반환이 256GB/s가 되는 것은 아니다.

### 배치 개선으로 확인한 것

현재 개선 배치는 각 논리 영역이 모든 channel을 사용하되 channel 안에서는 영역0을 PL0~3, 영역1을 PL4~7, 영역2를 PL8~11, 영역3을 PL12~15에 배치한다. Port 번호가 아닌 논리 주소로 위치를 결정한다. 네 영역에 부하가 고르게 걸릴 때 같은 Plane에서 멀리 떨어진 영역을 번갈아 읽는 일을 줄이고, Plane 내부 q+1 진행과 Short/Mid 활용을 늘린다. tR 상수는 바꾸지 않았다.

영역별 배치 효과는 이전 동일 조건 대조에서도 확인했다. 64Plane의 유한 요청열에서 A1은 185.862→236.361GB/s, A2는 189.324→234.988GB/s로 개선됐다. 이 수치는 배치만 바꾼 대조 근거이며, 최신 지속 부하의 약 255GB/s와 측정 구간이 다르다.

4KiB interleaving만으로 항상 최고 대역폭을 보장하지는 않는다. Plane 내 물리 연속성, 영역별 부하 균형, 충분한 QD, 버퍼 예약의 Port 분포를 함께 맞춰야 한다. 현재 A2 대표값은 16KiB stripe를 사용하므로 모든 패턴에서 4KiB stripe가 최적이라는 결론도 아니다. 실제 동적 L2P와 편향된 부하에서 같은 이득이 유지되는지는 후속 평가 항목이다.

근거: [Mapper](../znand/model.py), [배치만 바꾼 대조](../results/znand/host_ceiling/RESULTS_KO.md), [실제 outstanding과 Port 편중](../results/znand/saturation/RESULTS_KO.md).

## 4 Host와 Device의 관리 책임

### Queue와 Global address 및 Block 관리

모델의 Host는 논리 주소 요청을 제시하고, controller는 수락·버퍼 예약·NAND 작업 순서·Port별 in-order 반환을 처리한다. 논리 영역 배치는 미리 생성된 정적 mapping으로 주어진다. 실행 중 block 할당·write·erase·GC는 수행하지 않는다.

따라서 원문의 “Host가 queue management, global address management, block management를 담당한다”는 설명의 실제 계약을 확정할 수 없다. Host 측 큐 관리와 device 내부의 NAND 스케줄링은 함께 존재할 수 있다. 제출·완료 큐, 주소 공간 배정, block 할당·회수·erase 각각의 주체를 제품 인터페이스에서 명시해야 한다.

### L2P 변환

모델은 Host 논리 주소를 channel·Plane·물리 페이지·offset으로 변환하며 요청당 lookup 500ns를 부여한다. 이것은 성능 추상화다. 실제 제품에서 변환을 controller 내부가 하는지, Host가 raw physical die 주소를 제공하는지는 결정하지 않는다. 현재 고성능 배치는 합성 정적 snapshot이며 실행 중 mapping이 바뀌지 않는다. 또한 수락 시 버퍼 예약에 매핑 결과를 사용하는 가정이 있어 실제 주소 정보 확보 시점과의 정합성도 확인해야 한다.

### Wear leveling과 Bad block 및 Repair

실제 wear leveling, bad block 교체, repair와 GC 데이터 이동은 구현하지 않았다. availability 85%는 Plane별 100µs 주기에 명목 15µs의 내부 점유를 넣는 성능 추상화다. 이를 실제 GC 동작이나 고장 복구 기능의 검증으로 해석할 수 없다. Read/write 혼합 트래픽도 실행하지 않았다. ECC는 고정 지연만 포함한다.

원문의 마지막 문장은 “Does zNAND internally handle”에서 잘려 있으므로 보이지 않는 세부 질문은 복원하지 않았다. 관리 주체와 지원 범위는 완전한 질문 및 제품 설계로 확인해야 한다.

근거: [모델 코드](../znand/model.py), [튜닝 범위](07_prefetch_tuning_ko.md), [Google 질문 원문](01_questions_en.md).

## English response draft

The following responses are based on our current performance model and the experiments completed to date. They are conditional simulation results, not confirmed zNAND product specifications or hardware measurements.

The representative sustained-throughput results use four independent host ports sharing four NAND channels, 16 planes per channel, one page buffer per plane, a shared 8 MiB temporary controller buffer, prefetch disabled, and strict response ordering within each port. The logical read region is 4 KiB and the physical NAND page is 16 KiB. We continuously supply requests and report the fixed 2 ms average after excluding the initial 200 µs. The aggregate modeled host payload limit is 256 GB/s.

### 1 End-to-End Read Latency Breakdown and Access Patterns

The model separates request admission, lookup, NAND command scheduling, sensing, NAND data transfer, ECC, and ordered host return. Configured sensing times are 2.00 µs for Short, 2.08 µs for Mid, 12.16 µs for Long, and 20.69 µs for First or Group transitions. These values were not reduced in the latest performance experiments. The sensing class depends on the physical access sequence within each plane, rather than the logical workload name alone.

A retained plane page buffer can avoid re-sensing. An active controller buffer entry can also avoid another NAND data transfer. Entries are released after all attached requests complete; persistent cache hits are not assumed.

The latest representative sustained host payload throughput is:

| Original question pattern | Outstanding limit per port | Host payload throughput |
|---|---:|---:|
| A-1, 4 KiB linear reads | 512 | 255.366 GB/s |
| A-2, 4 KiB local 1-3-2 permutation | 512 | 255.058 GB/s |
| B-1, one 64-byte read per 4 KiB region | 512 | 3.995 GB/s |
| B-2, the same partial reads in local 1-3-2 order | 512 | 4.001 GB/s |
| B-3, page revisit pattern | — | No result yet under the latest 64-plane sustained-load setup |

A-1 uses 4 KiB channel striping and head_locality scheduling; the representative A-2 uses 16 KiB striping and locality scheduling. This table therefore does not isolate access order as the only difference between A-1 and A-2. The implemented A-2 and B-2 patterns are local permutations, not uniformly random addresses across the full address space.

For B-1 and B-2, the model transfers a complete 16 KiB NAND page to the controller, while the host consumes only 64 bytes from each of its four packed 4 KiB regions. The nominal useful fraction is 256 B / 16 KiB, or 1/64. Internal NAND throughput was approximately 257 GB/s, while useful host throughput was approximately 4 GB/s. Long sensing accounted for 0% of sensing operations in these representative observation windows; the low useful throughput is therefore not explained by Long sensing in those runs.

As an additional experiment, sequential 64-byte requests consuming every byte of each 4 KiB region reached 255.335 GB/s at 32,768 outstanding requests per port. At 512 outstanding requests per port, this pattern reached 31.457 GB/s. Full-page consumption and sufficient outstanding payload are both relevant. The additional pattern is distinct from the original B-1/B-2 questions. Request-state metadata costs at these large outstanding limits are not modeled as part of the 8 MiB payload buffer.

For B-3, a revisit may reuse an active controller entry, re-output a retained NAND page buffer, or require another sensing operation if that plane's buffer has been overwritten. Logical page switching alone does not determine which case occurs. Our implemented revisit uses offset +64 bytes, whereas the original question does not specify the revisit offset.

These bandwidth figures are not per-request latency measurements. UCIe packetization, adapter, link and credit delays are not separately modeled, and the latest sustained tests do not provide a complete mean/p99 end-to-end latency breakdown. The request-start boundary and first-data versus full-data completion boundary should be aligned before reporting the requested latency. Separate command-based and memory-semantic paths have not been evaluated, so we cannot quantify a latency difference between those modes from the present results.

### 2 Supported NAND Transaction Shapes and Flow Control

The model evaluates 64-byte requests at 64-byte-aligned addresses and 4 KiB requests at 4 KiB-aligned addresses. Sequential 64-byte accesses within a 4 KiB region have been exercised. This establishes model behavior, not native product-interface support.

Only 64-byte and 4 KiB request lengths are implemented in these experiments. Support for 128-byte, 192-byte and other lengths, cross-boundary bursts, and maximum transaction size must be confirmed against the device interface. Sub-4 KiB performance depends on per-request processing, available outstanding requests, and the fraction of the internally transferred page consumed by the workload. Partial NAND column output has not been modeled.

The model delays request acceptance when outstanding or controller-buffer limits are reached. It does not implement cycle-level RREADY deassertion, adapter FIFO behavior, or UCIe credit stalls within a response. Consequently, arbitrary-cycle versus burst-boundary response back-pressure remains an interface-design question rather than an experimentally established capability.

### 3 Bank Architecture and Address Interleaving

The sizes and die distribution of the colored blocks in Samsung's original slide require its actual mapping definition. In our model, a logical page is 4 KiB and four logical regions are packed into a 16 KiB physical NAND page. A 4 KiB region is not itself striped across multiple dies. Additional die/LUN shared-resource constraints are not implemented.

For 4 KiB channel interleaving, an example physical-page packing is CH0: P1/P5/P9/P13; CH1: P2/P6/P10/P14; CH2: P3/P7/P11/P15; and CH3: P4/P8/P12/P16. Each P is 4 KiB. Any host port may access all four channels according to the requested address; there is no fixed one-port-to-one-channel connection. A single port remains limited by its own modeled 64 GB/s host return path.

The improved static placement also assigns different logical address regions to separate plane groups within every channel. This reduces large physical-address jumps within a plane and preserves Short/Mid sensing opportunities. The address determines placement, not the issuing port. The gains depend on balanced region activity and should be re-evaluated with dynamic L2P and skewed workloads. Four-channel interleaving alone is insufficient to guarantee peak throughput, and the present results do not establish one stripe size as optimal for every workload.

### 4 Memory Management and Host Responsibilities

The modeled host supplies logical-address requests, while the controller model handles admission, buffer reservation, NAND scheduling and ordered return. A static mapper translates addresses to channel, plane, physical page and offset, with an assumed 500 ns lookup stage. This abstraction does not establish whether the product's L2P implementation resides in the host or device, or whether the external interface accepts logical or raw physical die addresses. Mapping is already available to buffer reservation at admission in the model; the implementation's address-availability timing should be checked.

Submission/completion queues, global address allocation, block allocation and erase responsibilities should be specified separately. Host queue ownership can coexist with internal controller NAND scheduling.

Dynamic wear leveling, bad-block replacement, repair, write/erase traffic and GC data movement are outside the current model. The 85% availability setting represents periodic internal plane occupancy, not a detailed GC implementation. The final supplied question is truncated after “Does zNAND internally handle”; its missing text should be confirmed before providing a complete product response.

## 실험 데이터와 재현 기준

- [A1과 A2의 지속 부하 결과](../results/znand/saturation/rows.json)
- [원문 B-1과 B-2의 지속 부하 결과](../results/znand/partial_saturation/rows.json)
- [페이지 내부 64B 연속 읽기 결과](../results/znand/b_sequential/rows.json)
- [최고 B 조건의 원시 결과와 설정](../results/znand/b_sequential/cases/B_b8_q32768/result.json)
- [B 실험 검증](../results/znand/b_sequential/validation.json)

이번 답변은 기존 저장 결과를 재정리했다. 새 성능 실험이나 NAND 모델 변경은 없다. 기준 코드 커밋은 `a2d3ddc`, core `znand/model.py` SHA256은 `755f822a6b7c1f44f65117b4892078419a766d4963ad4d49931e8aa1db679baf`다.
