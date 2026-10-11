# Google 문의 답변용 모델 자료

**최신 답변:** 이 문서는 2026-10-09의 32Plane 실험 기록입니다. 64Plane 지속 부하 및 페이지 내부 64B 연속 읽기를 반영한 현재 고객 답변은 [최신 실험 기준 한영 답변](17_google_answers_current_ko_en.md)을 사용하세요.

**명칭 안내:** 이 문서의 기존 B1/B2/B3(또는 B-1/B-2/B-3)는 현재 C1/C2/C3에 해당합니다. 새 B는 페이지 내부 64B 연속 읽기입니다. [현재 정의](15_workload_naming_ko.md)를 참고하세요. 원문 질의·과거 재현 명령은 당시 표기를 유지합니다.

2026-10-09 작성한 Word 보고서의 본문이다. 기준 소스는 `2b1a831882dbf23855508c3f5478aadc973d8a23`이며 기존 1,488개 실험을 다룬다. 이후 추가한 6개 진단과 64Plane 결과는 [Host IF 원인 분석](08_host_if_bottleneck_ko.md)과 [Plane 확장·NAND 배치](09_plane_expansion_layout_ko.md)를 함께 읽는다.

## Google zNAND 문의에 대한 모델 분석과 답변

2026년 10월 9일   모델 기준 커밋 2b1a831

현재 주소 기반 모델로 4KiB와 64B 접근 패턴의 지연 및 처리량을 비교하고, 주소 배치와 페이지 재사용의 영향을 설명할 수 있다. 실제 UCIe 경로의 지연, 지원 burst 및 back-pressure, Host와 device의 관리 책임은 제품 설계 근거로 보완해야 한다.

전체 1,488개 조건의 관측 최고 처리량은 72.27GB/s다. 같은 A2 설정을 더 긴 요청열로 평가한 값은 69.28GB/s다. 두 값은 공유 8MiB 버퍼와 현재 모델 가정에서의 유한 요청열 결과이며, 실제 제품의 최대 성능을 뜻하지 않는다.

## 1 Google 문의에 대한 답변 범위

표 1 문의별 모델 결과의 적용 범위

| 문의 | 현재 결과로 제시할 내용 | 제품 확인이 필요한 내용 |
| --- | --- | --- |
| 1 읽기 지연 | A1 A2 B1 B2 B3 지연과 처리량<br>페이지 재사용 및 반환 대기 | UCIe 요청과 반환 경로<br>두 IO 모드의 경로 및 완료 기준 |
| 2 요청과 흐름 제어 | 64B와 4KiB 성능 비교<br>버퍼와 QD에 따른 수락 대기 | 주소 정렬과 지원 burst<br>전송 중 수신 정지와 재개 |
| 3 주소 배치 | 4KiB와 16KiB channel 분산<br>주소별 channel과 plane 연결 | 원본 그림의 블록 크기<br>실제 die와 bank 공유 제약 |
| 4 관리 책임 | 가정한 매핑과 조회 비용의 영향 | L2P와 queue 및 block 관리 주체<br>wear leveling과 bad block 및 repair |

### 자료를 사용할 때의 기준

- 숫자는 모델의 예측치로 제시하고, 실제 제품의 구현이나 보장값과 연결하는 근거를 함께 확인한다.

- Google의 Page는 4KiB 논리 영역이다. 모델의 NAND 물리 페이지는 16KiB이며 두 단위를 구분한다.

- Google의 요청 발행 기준에는 수락 전 대기가 포함된다. 수락 이후 지연만으로 end-to-end latency를 설명하지 않는다.

근거 [1] [2] [3] [4]. 출처와 재현 조건은 마지막 페이지에 정리했다.

## 2 모델 구조와 실험 조건

4개 독립 Host port가 4개 NAND channel과 총 32개 Plane을 공유한다. 각 port는 자신의 요청 수락 순서대로 전체 데이터를 반환한다. Port 간 전역 반환 순서는 강제하지 않는다. Die와 LUN의 추가 공유 자원 제약은 현재 모델에 포함하지 않았다.

표 2 현재 실험의 주요 가정

| 항목 | 설정 | 항목 | 설정 |
| --- | --- | --- | --- |
| Host port | 4개 독립 port | 반환 경로 | 512bit 1GHz per port |
| Host 이론 상한 | 64GB/s per port<br>합산 256GB/s | NAND 구조 | 4channel × 8plane |
| 논리 읽기 | 64B 또는 4KiB | 물리 페이지 | 16KiB per Plane |
| 조회 | 요청당 500ns<br>500MHz 2개 pipeline | Channel Data | 80.1125GB/s per channel |
| CA 점유 | Read당 100ns | 전송 후 처리 | turnaround 50ns<br>ECC 200ns |
| Controller buffer | 공유 8MiB<br>16KiB 페이지 512개분 | Page buffer | Plane당 1개 |
| Sensing | Short 2.00µs<br>Mid 2.08µs | Sensing | Long 12.16µs<br>최초 및 Group 20.69µs |
| 내부 작업 | 100µs 주기 15µs 점유<br>Plane별 시차 | Prefetch 기준 | 합성 정확도 100%<br>lead 10µs 후보 상한 128개 |

공유 버퍼는 수락 단계에서 예약한 공간을 포함한다. buffer peak를 도착한 payload만의 점유량으로 해석하지 않는다. 내부 작업의 15% 점유는 실제 GC의 복사와 erase 및 자원 경합을 재현한 값이 아니다.

### 접근 패턴의 구현

표 3 요청 크기와 주소 순서

| 패턴 | 요청 크기 | 현재 코드의 접근 순서 |
| --- | --- | --- |
| A1 | 4KiB | 1 → 2 → 3 → 4 → 5 → 6 |
| A2 | 4KiB | 1 → 3 → 2 → 4 → 6 → 5 |
| B1 | 64B | 1 → 2 → 3 → 4 → 5 → 6 |
| B2 | 64B | 1 → 3 → 2 → 4 → 6 → 5 |
| B3 | 64B | 1 → 3 → 1의 다음 64B → 2<br>이후 4 → 6 → 4의 다음 64B → 5 |

A2와 B2는 세 페이지 단위의 고정 순열이다. 균등 무작위 주소를 생성하는 실험과 구분한다. B3의 재방문 offset +64B는 모델 선택이며 Google 원문에서는 동일 offset 여부를 정하지 않았다. 요청열은 다음 영역으로 진행하며 작은 작업 영역을 무한 반복하지 않는다.

근거 [1] [2] [3] [6]. Cache 및 LRU는 도입하지 않았고, 연결된 모든 요청의 반환 완료 시 controller 항목을 해제한다.

## 3 문의 1 접근 패턴별 성능

아래 표는 모두 4port, QD 2,048 per port, 공유 8MiB, 32plane, port당 8,192개 요청, seed 7, port 간 주소 중첩 0% 조건이다. 요청 크기는 A 계열 4KiB, B 계열 64B다. 요청 제시 간격은 각각 64ns와 1ns이며, 수락이 늦어져도 제시 시각은 유지된다.

표 4 동일 조건에서의 유효 Host 처리량 단위 GB/s

| 패턴 | 읽기 | 4KiB 분산<br>PF OFF | 4KiB 분산<br>PF ON | 16KiB 분산<br>PF OFF | 16KiB 분산<br>PF ON |
| --- | --- | --- | --- | --- | --- |
| A1 | 4KiB | 65.879 | 67.563 | 68.235 | 68.290 |
| A2 | 4KiB | 65.783 | 68.357 | 67.717 | 69.282 |
| B1 | 64B | 1.716 | 1.731 | 1.877 | 1.884 |
| B2 | 64B | 1.671 | 1.674 | 0.790 | 0.797 |
| B3 | 64B | 0.885 | 0.869 | 1.775 | 1.824 |

PF는 Prefetch다. 가장 큰 QD나 한 배치를 모든 패턴의 최적값으로 간주하지 않는다. 예를 들어 B2는 이 조건에서 4KiB 분산이 유리하다.

표 5 Prefetch OFF와 16KiB 분산의 지연 단위 µs

| 패턴 | 수락 이후<br>평균 | 수락 이후<br>p99 | 수락 전<br>평균 대기 | 제시부터 반환<br>평균 |
| --- | --- | --- | --- | --- |
| A1 | 117.72 | 270.21 | 697.02 | 814.75 |
| A2 | 118.42 | 269.65 | 709.00 | 827.42 |
| B1 | 68.49 | 237.22 | 626.37 | 694.87 |
| B2 | 164.05 | 241.98 | 1,336.30 | 1,500.35 |
| B3 | 94.51 | 242.04 | 641.72 | 736.23 |

### 제시한 수치가 설명하는 것

이 표는 주어진 요청 부하와 하드웨어 가정에서의 처리량 및 대기 포함 지연을 비교한다. 독립 요청 하나의 무부하 지연을 측정한 표가 아니다. QD 1도 동일한 빠른 제시 시각을 사용하면 긴 수락 전 대기가 발생할 수 있다.

64B 요청도 NAND에서 16KiB 전체를 controller로 가져온다. 동일 물리 페이지의 요청 병합과 page buffer 재출력이 내부 트래픽을 바꾼다. 따라서 작은 요청의 비용은 반환 데이터 크기만으로 결정되지 않는다.

UCIe 패킷화와 링크 전송 및 credit 지연은 별도로 모델링하지 않았다. Google의 end-to-end 정의에 맞춰 실제 링크 구간을 보완하고, 첫 데이터 도착과 전체 데이터 반환 중 어떤 완료 시점을 사용할지 정해야 한다.

근거 [3] [4] [5]. 처리량은 첫 Host 요청 제시부터 마지막 반환까지의 유효 byte를 사용하며 Prefetch 사전 준비 시간은 제외한다.

## 4 A2 최고 처리량과 지연 분해

A2 최고 조건은 4port, 16KiB channel 분산, QD 2,048 per port, 공유 8MiB, Prefetch ON이다. Prefetch는 미래 요청을 아는 합성 정확도 100%, lead 10µs, 미사용 후보 상한 128개를 사용했다. Port별 주소 영역은 겹치지 않는다.

표 6 요청열 길이에 따른 A2 결과

| 요청 수<br>per port | 처리량<br>GB/s | 4KiB<br>MIOPS | 수락 이후<br>평균 µs | 수락 이후<br>p99 µs |
| --- | --- | --- | --- | --- |
| 4,096 | 72.27 | 17.64 | 102.96 | 233.87 |
| 8,192 | 69.28 | 16.91 | 114.34 | 229.16 |

4,096개 조건은 총 64MiB를 읽고 8,192개 조건은 총 128MiB를 읽는다. 사전 NAND 작업 시간을 포함한 처리량은 각각 71.50GB/s와 68.93GB/s다. 측정 길이 차이를 QD 변화나 성능 개선으로 해석하지 않는다.

표 7 72.27GB/s 조건의 평균 지연 분해

| 구간 | 평균 µs | 의미 |
| --- | --- | --- |
| 요청 제시 후 수락 대기 | 315.640 | Outstanding과 공유 버퍼 등 admission 제약 |
| 수락 후 조회 시작 대기 | 0.001 | Port별 lookup queue와 pipeline |
| 조회 처리 | 0.500 | 요청당 고정 lookup 지연 |
| 조회 후 데이터 준비 대기 | 32.341 | CA와 sensing 및 Data 전송과 ECC 대기 포함 |
| 데이터 준비 후 반환 시작 대기 | 70.050 | 선행 요청과 반환 경로 직렬화 대기 포함 |
| Host 데이터 전송 | 0.064 | 4KiB 64beat at 512bit 1GHz |
| 요청 제시부터 전체 반환 | 418.596 | 위 구간의 요청별 평균 합계 |

수락 이후 평균은 102.96µs이며, 수락 전 315.64µs를 포함하면 418.60µs다. 이 값에 실제 UCIe 구간을 포함해야 Google의 링크 기준 지연과 비교할 수 있다. 32.34µs의 데이터 준비 대기는 순수 sensing 시간과 같지 않고, 70.05µs의 반환 대기는 순수 Head-of-Line 시간과 같지 않다.

이 조건에서 후보 4,096개 중 3,543개는 버퍼 부족, 96개는 후보 예산으로 Prefetch 등록이 거절됐다. Prefetch로 발행된 작업은 457개, 이후 수요가 연결된 페이지는 424개다. 수요 연결은 요청 전에 데이터가 준비된 hit를 의미하지 않는다.

버퍼 peak 512개는 8MiB 상한에 도달했다. 8MiB를 넘는 버퍼 실험은 현재 1,488개 결과에 없으며, 버퍼 확대 후의 최대값은 추가 평가 대상이다. 근거 [3] [4].

## 5 문의 3 주소 배치와 병렬성

P1부터 P16까지는 각각 4KiB 논리 페이지다. 아래 표는 초기 정돈 배치에서 16KiB 물리 페이지를 채우는 방식이며, 제품의 확정 주소 매핑으로 제시하지 않는다. 모든 port가 네 channel을 사용할 수 있고 port와 channel을 1대1로 고정하지 않는다.

4KiB와 16KiB channel 분산의 초기 패킹

| Channel | 4KiB 분산에서 첫 16KiB 물리 페이지 | 16KiB 분산에서 첫 16KiB 물리 페이지 |
| --- | --- | --- |
| CH0 | P1 · P5 · P9 · P13 | P1 · P2 · P3 · P4 |
| CH1 | P2 · P6 · P10 · P14 | P5 · P6 · P7 · P8 |
| CH2 | P3 · P7 · P11 · P15 | P9 · P10 · P11 · P12 |
| CH3 | P4 · P8 · P12 · P16 | P13 · P14 · P15 · P16 |

표의 각 배치 셀이 해당 channel의 첫 16KiB 물리 페이지다. 예를 들어 4KiB 분산의 CH0는 P1 P5 P9 P13을 담고, 16KiB 분산의 CH0는 P1 P2 P3 P4를 담는다.

표 8 A2 초기 여섯 요청의 channel 선택

| 요청 순서 | 논리 페이지 | 상대 시작 주소 | 4KiB 분산 | 16KiB 분산 |
| --- | --- | --- | --- | --- |
| 1 | P1 | 0x0000 | CH0 | CH0 |
| 2 | P3 | 0x2000 | CH2 | CH0 |
| 3 | P2 | 0x1000 | CH1 | CH0 |
| 4 | P4 | 0x3000 | CH3 | CH0 |
| 5 | P6 | 0x5000 | CH1 | CH1 |
| 6 | P5 | 0x4000 | CH0 | CH1 |

16KiB 분산에서 첫 네 요청은 같은 물리 페이지를 사용한다. 동일 페이지 작업과 버퍼가 유효하면 NAND 읽기 한 번을 공유하고 Host에는 4KiB씩 네 번 반환한다. 내부 Read를 병합해도 각 Host 요청의 lookup과 credit 및 반환 순서는 독립적으로 유지한다.

Channel 내부 물리 페이지 슬롯은 Plane 0부터 7까지 순환한다. 슬롯 8부터 Plane 0의 다음 페이지로 진행한다. Plane 내부 주소는 E/O, SSL, Block, 감소하는 WL, Group 순서로 배정하고 Plane별 직전 sensing 주소를 기준으로 tR를 판정한다.

삼성 원본 그림의 색상 블록 크기와 실제 die 및 bank의 연결, Die별 동시 명령과 전력 제약은 별도 설계 근거가 필요하다. 근거 [1] [3] [6].

## 6 문의 2와 문의 4의 답변

### 문의 2 요청 크기와 흐름 제어

현재 모델은 64B와 4KiB 요청을 입력으로 받고, 요청 크기에 맞는 주소 정렬을 확인한다. 이것은 모델의 입력 조건이다. 실제 장치가 지원하는 주소 정렬, 64B부터 4KiB까지의 모든 64B 배수 burst, 경계 통과 여부를 확인한 결과는 아니다.

Outstanding이나 공유 버퍼가 부족하면 요청 수락을 늦추고 그 대기를 계측한다. 반환 경로는 크기에 따른 전송 시간을 사용하며, burst 중간의 RREADY deassert와 재개를 cycle 단위로 재현하지 않는다. 따라서 전송 도중 어느 cycle에서 정지할 수 있는지는 이 결과로 확정하지 않는다.

표 9 인터페이스 설계에서 확인할 항목

| 항목 | 답변에 필요한 제품 정보 |
| --- | --- |
| 주소와 요청 길이 | 64B 정렬 허용 여부 및 128B 192B 등 지원 길이<br>4KiB 경계와 최대 transaction 제한 |
| 수신 정지와 재개 | Beat 단위 또는 burst 경계 단위 정지<br>정지 전파 지연과 이미 발행된 데이터의 처리 |
| 중간 저장 공간 | Adapter FIFO 깊이와 credit 단위<br>Credit 회복과 overflow 방지 조건 |
| IO 모드 차이 | Command-based와 Memory-semantic의 요청 경로<br>완료 의미와 추가 명령 및 응답 비용 |

### 문의 4 관리 책임과 주소 변환

모델은 논리 주소를 channel과 plane 및 물리 페이지로 연결하고 lookup에 500ns를 부여한다. 이 추상화는 실제 L2P가 Host와 device 중 어디에 구현됐는지를 결정하지 않는다. Admission 시점에 매핑 결과를 버퍼 예약에 사용하는 가정도 실제 주소 정보의 가용 시점과 비교해야 한다.

표 10 관리 기능별로 필요한 답변 근거

| 관리 기능 | 현재 모델의 범위 | 제품 설계에서 정할 내용 |
| --- | --- | --- |
| Queue와 주소 | Port별 요청열과 정적 매핑 | Queue 소유자와 global 주소 배치 주체 |
| L2P | 초기 매핑 및 일부 사전 상태 | 논리 또는 물리 주소 입력 계약<br>변환과 remap 담당 주체 |
| Block과 wear leveling | 실행 중 write 및 erase 없음 | Block 할당과 이동 및 erase 책임 |
| Bad block와 repair | 결함 관리와 repair 동작 없음 | Bad block 관리와 TSV repair 지원 범위 |

Google 원문의 마지막 질문은 이미지에서 문장이 잘려 있다. Wear leveling과 bad block 및 repair의 제목과 보이는 문장 범위를 보존하고 잘린 세부 조건을 임의로 복원하지 않는다. 근거 [1] [2] [3].

## 7 Google 문의 답변 문안

The address-based model provides conditional estimates for the five access patterns. The figures below use four independent ports sharing four NAND channels and 32 planes, an 8 MiB controller buffer, and strict response ordering within each port. Device-specific interface capabilities and management responsibilities require implementation data.

### 1 Read latency and access patterns

We modeled A1 and A2 as 4 KiB reads, and B1, B2 and B3 as 64-byte reads. A2 and B2 use a repeating local 1-3-2 permutation rather than uniform random addresses. B3 revisits the first page at an offset of +64 bytes; the offset remains to be aligned with the requested workload.

The highest observed A2 throughput was 72.27 GB/s with 16 KiB channel striping, prefetch enabled, and an outstanding limit of 2,048 per port. A longer trace achieved 69.28 GB/s with the same configuration. In the peak-throughput case, mean latency from request acceptance to full return was 102.96 µs. Including admission waiting, mean latency from request presentation to full return was 418.60 µs. UCIe packet, link and credit delays are not modeled separately. Command-based and memory-semantic paths are not compared in this model.

### 2 Transaction shapes and flow control

The current model evaluates 64-byte and 4 KiB requests, with a full 16 KiB NAND page transferred to the controller. It captures admission delays caused by outstanding and buffer limits. Supported alignment, other burst lengths such as 128 or 192 bytes, boundary restrictions, and cycle-level receive stalls require device and adapter specifications. Mid-burst stop and resume behavior has not been evaluated.

### 3 Address mapping and interleaving

We compared 4 KiB and 16 KiB channel striping. The mapping illustration shows the assumed placement of logical pages across four channels. Any port can access all four channels. The preferred placement depends on the workload: in the matched long-trace comparison, B2 benefited from 4 KiB striping, while A2 achieved its higher throughput with 16 KiB striping. The block sizes and die or bank distribution in the original Samsung diagram require the actual mapping definition.

### 4 Host and device responsibilities

The model includes an address mapper and an assumed lookup delay; it does not establish the owner of L2P or queue and block management. Host versus device responsibilities for address translation, remapping, wear leveling, bad-block handling and repair should be stated from the implementation. The final question in the supplied image is incomplete.

All results are model estimates under the stated assumptions. Prefetch uses future trace information with 100% candidate accuracy, a 10 µs lead, and a 128-candidate unused budget; these figures do not establish a deployed predictor’s performance. Sources [1] to [6].

## 8 답변 보완과 근거 자료

### 모델 결과를 보완할 평가

| 우선순위 | 추가 확인 또는 실험 | 답변에 연결할 항목 |
| --- | --- | --- |
| 1 | 요청 제시 간격을 조절한 무부하와 부하 sweep<br>첫 데이터와 마지막 데이터 시점 계측 | 문의 1 지연의 시작과 끝<br>부하에 따른 대기 분리 |
| 1 | UCIe 요청 및 반환 경로 지연과 credit 계측<br>두 IO 모드 경로 정의 | 문의 1 실제 end-to-end 지연<br>문의 2 흐름 제어 |
| 2 | Google의 주소 분포와 B3 offset 합의<br>고정 순열과 실제 trace 비교 | 문의 1 패턴 정의와 페이지 재사용 |
| 2 | 버퍼 8 16 32 64MiB와 QD의 조합 평가<br>Prefetch OFF와 ON을 같은 조건으로 비교 | 문의 1과 3의 처리량 및 병목<br>현재 8MiB 이후 확장 가능성 |
| 2 | Die와 LUN 공유 제약 및 실제 주소 매핑 반영 | 문의 3 실제 병렬성 |

위 항목은 후속 평가 제안이다. 현재 결과에 포함된 버퍼 용량은 0.5MiB, 2MiB, 8MiB이며 8MiB를 초과한 결과는 없다. 32개 Plane의 독립 가정, 고정 port 순서의 수락 경쟁, 실제 GC와 동적 L2P의 생략이 결과에 미치는 영향도 함께 확인한다.

### 수치와 재현 기준

전체 CSV 1,488개 조건을 기준으로 최고값을 집계했다. 4,096개 요청 조건과 8,192개 조건을 구분하고, 패턴 비교 표에는 8,192개 요청 및 QD 2,048 per port를 공통 적용했다. 보고서의 요약 최고값만으로 전체 CSV의 최고값을 대신하지 않았다. 지연 단위는 µs, 대역폭은 decimal GB/s, 저장 단위는 KiB와 MiB다.

### 출처

[[1] Google 문의 원문](https://github.com/JBRARAPARK/HBF_zNAND_Research/blob/2b1a831882dbf23855508c3f5478aadc973d8a23/docs/01_questions_en.md)

[[2] 신규 모델 실행 안내와 가정](https://github.com/JBRARAPARK/HBF_zNAND_Research/blob/2b1a831882dbf23855508c3f5478aadc973d8a23/znand/README.md)

[[3] 주소 배치와 요청 및 이벤트 구현](https://github.com/JBRARAPARK/HBF_zNAND_Research/blob/2b1a831882dbf23855508c3f5478aadc973d8a23/znand/model.py)

[[4] 통합 원본 결과 1488개 조건](https://github.com/JBRARAPARK/HBF_zNAND_Research/blob/2b1a831882dbf23855508c3f5478aadc973d8a23/results/znand/all_results.csv)

[[5] 결과 보고서와 상위 Outstanding 분석](https://github.com/JBRARAPARK/HBF_zNAND_Research/blob/2b1a831882dbf23855508c3f5478aadc973d8a23/results/znand/full/RESULTS_KO.md)

[[6] Prefetch 배치와 L2P 튜닝 기준](https://github.com/JBRARAPARK/HBF_zNAND_Research/blob/2b1a831882dbf23855508c3f5478aadc973d8a23/docs/07_prefetch_tuning_ko.md)

[[7] 상위 Outstanding 원본 결과](https://github.com/JBRARAPARK/HBF_zNAND_Research/blob/2b1a831882dbf23855508c3f5478aadc973d8a23/results/znand/extended/sweep.csv)

모든 링크는 같은 커밋 2b1a831882dbf23855508c3f5478aadc973d8a23에 고정했다. 원문과 기존 모델 검토 기록보다 신규 znand 구현 및 통합 CSV를 현재 성능 결과의 기준으로 사용했다.
