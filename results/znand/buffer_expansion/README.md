# Controller buffer 확대 평가

4port에서 기존 8MiB와 16·24·32MiB를 비교한다. 각 용량에서 A1/A2/B1/B2/B3, 4KiB/16KiB 분산, Prefetch OFF/ON, Outstanding 2,048/4,096/8,192를 비교하며 port당 8,192개 요청을 사용한다.

`STATUS.json`은 저장 상태다. `sweep.csv`는 기존 8MiB 60개와 완료된 신규 조건을 포함한다. 전체 완료 전에는 최고값을 최종 결론으로 사용하지 않는다.

이번 실험은 모델 커밋 `2b1a831`의 32Plane 동작을 고정했다. 동기화한 최신 모델과 섞이지 않도록 `znand/reference_model_2b1a831.py`에 원본을 그대로 보존했다. 일반 모델의 64Plane 지원은 `znand/model.py`에 유지한다.

재실행·중단 후 이어서 실행:

```sh
python3 -m znand.buffer_sweep
python3 -m znand.buffer_report
```

보고서에는 matplotlib이 필요하다. 유효한 기존 checkpoint 조건은 다시 계산하지 않는다. 결과는 유한 합성 workload의 시뮬레이션이며 실제 제품 측정값이 아니다.
