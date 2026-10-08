# Questions for Samsung — 이미지 전사

이미지 1~4의 중복을 제거하고 문단·목록만 정리했습니다. 휴대폰 UI와 워터마크는 제외했습니다. 영어 표현의 기술적 모호함은 임의로 수정하지 않았습니다. 마지막 문장은 이미지에서 잘려 있습니다.

---

## Questions for Samsung:

zNAND-O UCIe Architecture & Interface

From Google team, on Oct 6, 2026 (PST)

Please review the following questions in advance and provide your responses during our upcoming meeting on October 7 (PST). Verbal answers during the discussion are completely fine. A written response document is optional, but please ensure your team is prepared to cover and answer all questions listed below.

## 1. End-to-End Read Latency Breakdown & Access Patterns

Definition of End-to-End Latency: Measured from when a read request is issued on the UCIe request channel until the corresponding read data returns via the data return channel.

Please break down the latency across the UCIe interface, zNAND controller, and NAND stack.

Please provide the expected latency (and any internal page switching/swapping overhead) for the following access patterns:

**4KB Burst Length:**

- Variant A-1 (Linear Access): Page 1 (4KB) → Page 2 (4KB) → Page 3 (4KB) → ...
- Variant A-2 (Inter-Page Random Access): Page 1 (4KB) → Page 3 (4KB) → Page 2 (4KB) → ...

**64B Burst Length (Partial Reads):**

- Variant B-1 (Linear Access): Page 1 (64B) → Page 2 (64B) → Page 3 (64B) → ...
- Variant B-2 (Inter-Page Random Access): Page 1 (64B) → Page 3 (64B) → Page 2 (64B) → ...
- Variant B-3 (Intra-Page / Jumping Access): Page 1 (64B) → Page 3 (64B) → Page 1 (64B) → Page 2 (64B) → ...

**Mode Comparison:** Does read latency differ between Command-based IO Mode and Memory-semantic IO Mode across these access patterns?

## 2. Supported NAND Transaction Shapes & Flow Control

**Address Alignment & Burst Length:**

- Are addresses required to be 4KB-aligned, or are 64B-aligned addresses supported natively?
- What burst sizes/lengths are supported (e.g., 64B, 128B, 192B, ..., up to 4KB)? Are there performance penalties or restrictions when issuing sub-4KB bursts?

**Back-Pressure Support & Handshake Protocol:**

- Does the zNAND-O / UCIe interface support read channel back-pressure on any cycle (any time in the middle) during a transaction (e.g., in the middle of a 4KB transfer via two-way handshake / ready deassertion), or strictly at transaction/burst boundaries?

## 3. Bank Architecture, Address Interleaving & Mapping

**Address Interleaving Granularity:**

- In the provided address interleaving diagram, what is the exact data size (in bytes/KB) represented by each colored block (green, blue, yellow, red) in Samsung’s previous slide “Memory Semantic IO: Overview”?
- Does each numbered block represent a 4KB page from a single die, or is data striped across multiple dies?
- If interleaving is not currently defined at a 4KB granularity, could you provide an address interleaving diagram assuming a 4KB interleaving granularity to help us align channel addressing for peak bandwidth across all 4 channels?

## 4. Memory Management & Host Responsibilities

**Host vs. Device Responsibilities:**

- Previous documentation notes that “queue management, global address management, and block management are handled by the host.” Could you please elaborate on what this entails?

**Logical-to-Physical (L2P) Conversion:**

- Does the zNAND controller perform internal Logical-to-Physical (L2P) address translation, or is the host required to supply raw physical die addresses?

**Wear Leveling, Bad Block & Repair Management:**

- Does zNAND internally handle **[이후 문장은 이미지에서 잘림 / remaining text not visible]**

---

## 전사 범위

- 5번 이후 영문 질문은 제공된 이미지에서 확인되지 않습니다.
- 영문 질문의 `4KB` 표기는 원문 그대로 보존했습니다. 모델 설정에서 4,096byte를 뜻할 때는 `4KiB`로 명시합니다.
- `Intra-Page` 명칭과 여러 페이지를 방문하는 예시가 함께 쓰여 있습니다. 재방문 시 같은 offset인지 다른 offset인지는 원문에 없습니다.
- 한국어 이미지 메모는 이 영문 질의의 연속 원문으로 취급하지 않습니다.
