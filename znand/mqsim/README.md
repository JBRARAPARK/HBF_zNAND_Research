# MQSim 사전 배치 추출

출처: https://github.com/CMU-SAFARI/MQSim

Revision: `51f0f2d3fed92d88ef4a0fa61a38024b07bf9d16`

`export.patch`는 page-level FTL의 사전 배치 할당이 끝난 시점에 LPA와 실제 물리 주소, valid bitmap을 CSV로 저장하는 계측이다. `MQSIM_SNAPSHOT_ONLY=1`에서는 CSV를 닫은 뒤 종료한다. GC·성능 알고리즘을 변경하지 않는다. Upstream 저작권·라이선스는 `UPSTREAM_LICENSE`를 따른다.

초기 native 실행에서 매핑 캐시 warmup이 종료되지 않아, 배치 추출 목적에 맞춰 `Ideal_Mapping_Table=true`로 설정했다. 일반 시뮬레이션은 요청 100개 처리 후 종료 정리 단계에서 비정상 종료되었으므로, 제공 결과는 해당 성능 출력을 사용하지 않는다. 검증된 snapshot 전용 모드가 종료 코드 0으로 추출한 CSV를 사용한다. MQSim 전체 실행 안정성이나 zNAND 호환성을 검증했다고 주장하지 않는다.

사전 조건화는 75% occupancy의 합성 streaming 입력이다. 유효 bitmap을 온전히 채우기 위해 512B sector 단위의 순차 주소를 사용한다. 추출된 45,711개 행 중 full-valid 16KiB 페이지 45,708개만 변환한다. 시뮬레이션 데이터 payload 자체는 복사하지 않는다.

`convert.py`는 원본 LPA를 보존하는 native import가 아니다. 유효 페이지의 LPA 순서를 dense slot에 대응하고 channel, die와 plane 결합 위치, block/page를 변환한다. snapshot의 `source_lpa`와 `conversion` 필드를 확인한다. 실제 NAND erase block과 zNAND Group/WL 구조가 같다는 의미는 아니다.

`ssdconfig.xml`, `workload.xml`, `precondition_raw.csv`, `export.log`, `snapshot.json`으로 입력·원본·변환 결과를 보존한다. snapshot에는 원본 SHA256이 있다. `reproduce.sh`는 새 checkout에서 추출을 재현하는 스크립트다.
