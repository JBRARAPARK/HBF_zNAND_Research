# 출처와 검토 범위

## 공개 1차 자료

| 자료 | 검토 범위 | 사용 목적 |
|---|---|---|
| [OCP HBF High-Level Base Die Specification v0.7.0](https://www.opencompute.org/documents/ocp-hbf-architecture-specification-v0-7-0-final-pdf) | 2026-08-03, 130쪽. §4.1–4.6, §5.2–5.4, §5.9.2, §11.4–11.5 및 관련 그림 | HBF의 기능·관리 책임·제품별 확인사항 |
| [Arm AMBA AXI and ACE Protocol Specification, IHI 0022H](https://developer.arm.com/-/media/Arm%20Developer%20Community/PDF/IHI0022H_amba_axi_protocol_spec.pdf) | §A3.2, Chapter A6 | VALID/READY와 AXI ID 순서 규칙 |
| [OCP Storage 프로젝트](https://www.opencompute.org/projects/storage/) | 2026-10-08 확인 | 공식 사양 등록 확인 |

사양 근거는 [HBF 조사 결과](../docs/03_hbf_findings_ko.md)의 절·페이지 링크에 연결했습니다. 제품 실측·삼성 공식 회신·비공개 사양을 확보한 것으로 해석하지 않습니다. 외부 PDF 사본은 저장소에 재배포하지 않고 공식 링크를 사용합니다.

## 관련 모델의 고정 버전

Repository: [JBRARAPARK/NAND_Prefetch_Model](https://github.com/JBRARAPARK/NAND_Prefetch_Model)

검토 커밋: `645649621a94c96de5a4d614267ab80387f06c0c`

| 파일 | 용도 |
|---|---|
| `README.md`, `CONTINUATION.txt` | 모델 발전 과정과 기존 결과의 적용 범위 |
| `axi_burst_sim.py` | Page·burst·기본 NAND 처리와 지표 |
| `multiport_sim.py` | 4개 port별 admission·조회·FIFO 반환 |
| `deep_prefetch_sim.py` | 합성 예측과 speculative 자원 처리 |
| `results/prefetch_decision_64/RESULTS_KO.md` | 판단 위치와 기존 64GB/s 실험 |
| `docs/execution_model/BOUNDARY_AND_AR_RLAST_KO.md` | AR→RLAST와 처리량의 구분 |
| `docs/deep_prefetch_review/STATUS_KO.md` | 2026-10-06 검토, 완료·미완료 범위 |

기존 문서의 테스트·실험 수치는 과거 기록입니다. 이번 연구 저장소 작성 중 모델 테스트나 전체 sweep을 다시 실행하지 않았습니다.

## 사용자가 제공한 이미지

| 이미지 | 파일명 | 전사에 사용한 범위 |
|---|---|---|
| 1 | `KakaoTalk_Photo_2026-10-07-23-43-35 001.jpeg` | 영문 1번 후반~4번 일부 |
| 2 | `KakaoTalk_Photo_2026-10-07-23-43-36 002.jpeg` | 영문 제목·서문~3번 제목 |
| 3 | `KakaoTalk_Photo_2026-10-07-23-43-36 003.jpeg` | 이미지 1과 겹치는 구간 교차 확인 |
| 4 | `KakaoTalk_Photo_2026-10-07-23-43-37 004.jpeg` | 이미지 2와 겹치는 구간 교차 확인 |
| 5 | `KakaoTalk_Photo_2026-10-07-23-43-57 001.jpeg` | 한국어 메모의 본문·마지막 부분 |
| 6 | `KakaoTalk_Photo_2026-10-07-23-43-57 002.jpeg` | 한국어 메모의 시작·중복 본문 |

원본 사진의 휴대폰 UI·워터마크는 문서 내용에 포함하지 않았습니다. 원본 사진 파일은 업로드하지 않고 전사와 출처 파일명을 보존했습니다.

## 추가 사용자 확인

2026-10-08: 4개의 port가 독립 주체이며, 이를 기준으로 AXI ID를 분리하여 처리할 수 있다는 조건을 반영했습니다. 이 조건은 공개 HBF 사양을 인용한 것이 아니라 이번 설계에 대한 사용자 설명입니다.

## 판단 수준

- **전사:** 이미지에 보이는 문장.
- **사양 확인:** 공개 1차 자료에서 확인한 동작·범위.
- **코드 확인:** 위 커밋에서 읽은 구현.
- **해석:** 질문의 목적과 모델에 대한 의미를 분석한 내용.
- **제안:** 향후 구현·실험·제품 확인사항.

검색 과정에서 접한 2차 기사나 별도 연구의 가정을 제품 사양 대신 사용하지 않았습니다.
