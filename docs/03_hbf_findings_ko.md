# HBF 조사 결과

조사일: 2026-10-08. 아래 확인사항은 OCP HBF v0.7.0(2026-08-03)에 관한 것이며 삼성 zNAND의 구현 보장이 아닙니다. 사양 본문과 주소 매핑 그림을 확인했습니다. 수치 실측은 수행하지 않았습니다.

## 1. 지연과 접근 패턴

패턴별 End-to-End 수치는 미제시입니다. Command-based/Memory-semantic 지연 비교도 확정할 수 없습니다.

bank당 4KiB cache 2개를 정의합니다. B-3 재접근은 잔존 여부와 ordering에 좌우됩니다. Regular/Batch Read의 스케줄링이 다르며, 동일 bank의 sense 순서를 보장합니다.

근거: [§5.3, pp.56–57](https://www.opencompute.org/documents/ocp-hbf-architecture-specification-v0-7-0-final-pdf#page=56).

## 2. 주소·길이·흐름 제어

읽기는 64B 정렬, 64B~4KiB의 64B 배수이며, 4KiB 경계를 넘으면 안 됩니다. Burst 지원은 제품별 BCS capability 확인이 필요합니다. 링크는 상대 FIFO 여유를 전달합니다. 실제 정지 전파시간은 구현 확인이 필요합니다.

근거: [§4.1, p.15](https://www.opencompute.org/documents/ocp-hbf-architecture-specification-v0-7-0-final-pdf#page=15), [§5.2, pp.39–40](https://www.opencompute.org/documents/ocp-hbf-architecture-specification-v0-7-0-final-pdf#page=39), [§5.9.2.1, p.70](https://www.opencompute.org/documents/ocp-hbf-architecture-specification-v0-7-0-final-pdf#page=70).

### AXI 계층 해석

Arm AXI 규격의 VALID/READY는 각 beat의 전달 조건입니다. 수신 측이 RREADY를 낮추면 burst 중간에도 수신을 지연시킬 수 있고, 아직 수락되지 않은 데이터와 RVALID는 송신 측에서 유지해야 합니다. 이미 handshake가 끝난 beat를 취소하는 기능은 아닙니다.

원격 링크, 중간 adapter와 FIFO를 포함한 시스템에서 정지 신호가 전파되는 시간과 이미 발행된 데이터의 처리까지 이 규칙 하나로 결정되지는 않습니다. 따라서 제품에 물을 것은 AXI의 가능 여부뿐 아니라 버퍼 깊이·credit 단위·정지 전파 지연입니다.

근거: [Arm IHI 0022H, §A3.2, pp.41–43](https://developer.arm.com/-/media/Arm%20Developer%20Community/PDF/IHI0022H_amba_axi_protocol_spec.pdf#page=41).

## 3. 주소 매핑

주소는 global→UCIe local→die/bank로 구분합니다. Figure 4의 번호는 단일 die/bank에 배치된 4KiB 단위입니다. UCIe 채널과 AXI 포트는 별개입니다. 4KiB 인터리빙 예시도 있습니다. 삼성 그림의 색상은 확정할 수 없습니다.

근거: [§4.6, Figures 3–5, pp.22–24](https://www.opencompute.org/documents/ocp-hbf-architecture-specification-v0-7-0-final-pdf#page=22).

## 4. 관리 책임

호스트는 global 배치·write 순서·refresh를 관리합니다. Base die는 내부 매핑·NAND 스케줄링·ECC·bad block·TSV repair를 담당합니다. Wear leveling은 제품별 자동/호스트 방식입니다. GC·유효데이터 자동이동은 없고, zone remap 후 호스트 재기록이 필요합니다.

근거: [§4.4–4.6, pp.19–23](https://www.opencompute.org/documents/ocp-hbf-architecture-specification-v0-7-0-final-pdf#page=19), [§5.2.4.6, p.48](https://www.opencompute.org/documents/ocp-hbf-architecture-specification-v0-7-0-final-pdf#page=48), [§5.4.1, p.58](https://www.opencompute.org/documents/ocp-hbf-architecture-specification-v0-7-0-final-pdf#page=58), [§11.4–11.5, pp.117–118](https://www.opencompute.org/documents/ocp-hbf-architecture-specification-v0-7-0-final-pdf#page=117).

## 별도로 확인한 혼합 동작과 표기 차이

混合 read/write 규칙도 있습니다. 미완성 write의 도착한 부분은 반환하고, 미도착 부분의 read에는 0xA 오류를 반환합니다. [§5.4.3, p.59](https://www.opencompute.org/documents/ocp-hbf-architecture-specification-v0-7-0-final-pdf#page=59).

Batch hint는 Table 8에서 ARUSER[2], §5.3.2.2에서 bit 0으로 표기돼 확인이 필요합니다. [Table 8, p.41](https://www.opencompute.org/documents/ocp-hbf-architecture-specification-v0-7-0-final-pdf#page=41), [§5.3.2.2, p.57](https://www.opencompute.org/documents/ocp-hbf-architecture-specification-v0-7-0-final-pdf#page=57).

## Port별 AXI ID 해석

Arm AXI에서는 같은 ID의 응답 순서를 유지하면서 다른 ID의 응답은 순서를 달리할 수 있습니다. 이 프로젝트에서는 사용자가 지정한 독립 port를 포함해 `(port, ID)`를 순서 그룹으로 해석합니다. 내부에서 port들을 합치는 bridge가 있다면 ID 변환과 경로 식별은 별도로 확인해야 합니다.

근거: [Arm IHI 0022H, Chapter A6](https://developer.arm.com/-/media/Arm%20Developer%20Community/PDF/IHI0022H_amba_axi_protocol_spec.pdf).

모델에서의 실제 적용과 미완료 항목은 [모델 비교](04_model_alignment_ko.md), 제품 확인사항은 [추가 질문](05_followup_questions_ko.md)을 참고합니다.
