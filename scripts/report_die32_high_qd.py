"""Validate extended observation and report the large-QD measurements."""
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from znand.partial_saturation import summarize_partial

OUT=ROOT/'results/znand/die32_high_qd'
PRIOR=ROOT/'results/znand/die32_performance'
read=lambda p:json.loads(p.read_text())
assert read(OUT/'validation.json')['status']=='passed'
rows=read(OUT/'summary.json');assert len(rows)==9
by={r['name']:r for r in rows}
old={r['name']:r for r in read(PRIOR/'summary.json')}
get=lambda p,q:(by|old)[f'{p}_region_q{q}']
extended={}
for q in (65536,262144):
    path=OUT/'extended'/f'B_region_q{q}'
    r=read(path/'result.json');t=read(path/'timeline.json')
    assert r['validation']['status']=='passed' and len(t)==168
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in r['source_sha256'].items())
    assert r['early']==summarize_partial(t[:88],200.,500.)
    assert r['late']==summarize_partial(t,2200.,500.)
    for row in t:
        assert row['outstanding_end']<=131072 and row['outstanding_mean']<=131072
        assert row['cumulative_accepted']-row['cumulative_completed']==row['outstanding_end']
        assert row['buffer_peak_mib']<=8
        for p in range(4):
            assert row[f'p{p}_cumulative_accepted']-row[f'p{p}_cumulative_completed']==row[f'p{p}_outstanding_end']
            assert row[f'p{p}_outstanding_max']<=q
    extended[q]=r
identical={}
for p,qs in [('A1',(4096,16384,65536)),('A2',(4096,16384,65536)),('B',(131072,262144))]:
    timelines=[read(OUT/'cases'/f'{p}_region_q{q}'/'timeline.json') for q in qs]
    assert all(t==timelines[0] for t in timelines)
    identical[p]=dict(qds=list(qs),full_timelines_identical=True)
for r in rows:
    cap=2048 if r['pattern'].startswith('A') else 131072
    for t in read(OUT/'cases'/r['name']/'timeline.json'):
        assert t['outstanding_end']<=cap and t['outstanding_mean']<=cap
validation=dict(status='passed',qd_only_new_cases=9,extended_runs=2,
    original_and_extended_windows_recomputed=True,extended_source_hashes_verified=True,
    payload_capacity_bound_checked_on_mean_and_bin_end=True,identical_timelines=identical)
(OUT/'extended_validation.json').write_text(json.dumps(validation,indent=2)+'\n')

atable='\n'.join(f"| {q:,} | {get('A1',q)['gbps']:.3f} | {get('A2',q)['gbps']:.3f} |" for q in (256,2048,4096,16384,65536))
btable='\n'.join(f"| {q:,} | {get('B',q)['gbps']:.3f} | "+(f"{extended[q]['late']['fixed']['bandwidth_gbps']:.3f}" if q in extended else '미측정')+' |' for q in (16384,32768,65536,131072,262144))
porttable='\n'.join(f"| {p} | {q:,} | "+' / '.join(f'{v:.1f}' for v in get(p,q)['per_port_outstanding'])+' |' for p,q in [('A1',65536),('A2',65536),('B',65536),('B',262144)])
latetable='\n'.join(f"| {q:,} | {r['late']['first_half']['bandwidth_gbps']:.3f} | {r['late']['second_half']['bandwidth_gbps']:.3f} | {r['late']['second_vs_first_pct']:.3f}% |" for q,r in extended.items())
text=f'''# QD 대폭 확대: 8MiB 버퍼에서 실제 수락량과 처리량

2026-10-12. 새32Plane 구조에서 **A1/A2의 QD를65,536/Port, B를262,144/Port까지** 높였다. 기존 포화 기준 A QD256, B QD16,384 대비 각각256배·16배다. **QD 상한만 크게 올려도 실제 요청 수는 버퍼에 제한되고, 기존 고정 수락 방식에서는 Port 편중으로 처리량이 낮아졌다.**

4 DIE×2 Channel×4 Plane, 영역별 배치, 공유 버퍼8MiB, CA FIFO, 고정 Port 수락, PF OFF, 기존 tR·가용률85%를 유지했다. 기존 기준 설정에서 바꾼 Config 항목은 `outstanding` 하나뿐이다. B 두 조건은 시간에 따른 감소를 확인하기 위해 관측 기간만 추가로 늘렸다.

## A1/A2 결과

단위는GB/s. 이전과 동일하게 초기200µs를 제외한0.2–2.2ms 고정2ms 평균이다.

| QD/Port | A1 | A2 |
|---|---:|---:|
{atable}

QD4,096/16,384/65,536의 각 패턴별 전체 시간대 계측은 정확히 같았다. 큰 설정값까지 요청이 수락되지 않기 때문에 상한을 더 높여도 실행이 달라지지 않았다. QD256·2,048은 [앞선 측정](19_die32_performance_ko.md)을 재사용했으며 신규 실행은 큰 QD의6개 조건이다.

## B 결과와 시간에 따른 변화

| QD/Port | 0.2–2.2ms 평균 GB/s | 2.2–4.2ms 평균 GB/s |
|---|---:|---:|
{btable}

QD16,384/32,768은 기존 결과다. QD65,536/131,072/262,144는 새로 측정했고, 65,536과262,144는4.2ms까지 연장했다. 연장 실행의 처음2.2ms 계측이 원래 실행과 일치하는지 확인했다. QD131,072와262,144의 원래2.2ms 시간대 계측은 정확히 같았다.

**큰 QD의0.2–2.2ms 평균은 안정된 장기 처리량으로 해석하면 안 된다.** B QD65,536은 그 구간 전반1ms 대비 후반1ms가18.78%, QD131,072/262,144는50.41% 낮아졌다. 추가 구간의 변화는 다음과 같다.

| QD/Port | 2.2–3.2ms GB/s | 3.2–4.2ms GB/s | 후반 변화 |
|---|---:|---:|---:|
{latetable}

이는 정해진 관측창의 값이며 무한 시간의 수렴값을 증명한 것은 아니다.

## 왜 설정한 만큼 요청이 쌓이지 않는가

실제 수락된 미완료 요청 수의0.2–2.2ms 평균은 다음과 같다.

| 패턴 | 설정 QD/Port | 실제 outstanding: Port0 / 1 / 2 / 3 |
|---|---:|---|
{porttable}

이 부하는 서로 다른 주소를 읽고 Controller buffer는 물리16KiB 작업별로 예약된다. 따라서8MiB는512개 물리 페이지 작업을 담는다. 각 요청을 한 번씩 읽는 현재 A/B 부하에서 전체 Port 합계의 payload 기준 수락량 상한은 다음과 같다.

- A: 512페이지×페이지당4개의4KiB 요청 = **전체 최대2,048개**.
- B: 512페이지×페이지당256개의64B 요청 = **전체 최대131,072개**.

이는 Port당 상한이 아니라 **네 Port 합계**다. 부분적으로 채워진 페이지, Port 선두 예약과 반환 대기 때문에 실제 요청 수는 더 작다. 동일 주소를 중복 요청하는 다른 부하나 다른 버퍼 관리 방식에 그대로 적용하는 일반식은 아니다. 요청 상태 메타데이터의 구현 비용은 모델에 포함되지 않는다.

QD는 이보다 많은 요청을 강제로 넣는 기능이 아니라, Port별 수락을 허용하는 상한이다. 고정 수락은 매번 Port0부터 확인하므로 큰 상한에서 앞쪽 Port가 버퍼를 더 많이 차지하고 다른 Port의 공급이 줄었다. 높은 QD에서 Long sensing은0%이므로 배치의 주소 연속성이 나빠져 생긴 낙폭은 아니다.

**현재 정책에서는 A QD256/Port, B QD16,384/Port의 약185.82GB/s가 여전히 유효한 기준점이다.** 높은 QD 자체가 항상 느리다는 일반론은 아니며, 이번에는 버퍼 크기나 수락 공정성을 바꾸지 않았다.

## 재현·검증

```sh
python3 -B scripts/measure_die32_high_qd.py --phase all --workers 1
python3 -B scripts/measure_die32_high_qd.py --phase validate
# 다음 두 연장 실행은 결과가 이미 있으면 보존하고 종료한다.
python3 -B scripts/measure_die32_high_qd_tail.py --qd 65536
python3 -B scripts/measure_die32_high_qd_tail.py --qd 262144
python3 -B scripts/report_die32_high_qd.py
```

신규9개 조건과 연장2개 실행을 저장했다. 이전 측정 함수와 모델 core는 변경하지 않았다. 소스·참조 결과·snapshot hash, Config 변경 항목, 시간창 재계산, Port별 수락−완료 보존식, QD·버퍼 상한, in-order 반환과 연장 실행의 앞 구간 동일성을 확인했다.

- [요약 CSV](../results/znand/die32_high_qd/summary.csv)
- [원시 결과·timeline](../results/znand/die32_high_qd/cases/)
- [4.2ms 연장 결과](../results/znand/die32_high_qd/extended/)
- [manifest](../results/znand/die32_high_qd/manifest.json)
- [기본 검증](../results/znand/die32_high_qd/validation.json)
- [연장·동일성·수락량 검증](../results/znand/die32_high_qd/extended_validation.json)

고정 seed7, 정적 합성 배치의 모델 결과이며 실제 하드웨어 측정은 아니다.
'''
(ROOT/'docs/20_die32_high_qd_ko.md').write_text(text)
print('Validated 9 cases and 2 extended runs; generated high-QD report')
