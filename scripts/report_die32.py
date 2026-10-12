"""Generate the current DIE-layout measurement report from validated results."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/znand/die32_performance'
read=lambda p:json.loads(p.read_text())
validation=read(OUT/'validation.json')
assert validation['status']=='passed' and validation['completed_cases']==18
rows=read(OUT/'summary.json')
by={r['name']:r for r in rows}
best={p:sorted((r for r in rows if r['pattern']==p),key=lambda r:(-round(r['gbps'],6),r['qd']))[0] for p in ('A1','A2','B','C1','C2')}
fmt=lambda v:f'{v:,.3f}'
overview='\n'.join(f"| {p} | {r['qd']:,} | {fmt(r['gbps'])} | {fmt(r['peak_500us_gbps'])} |" for p,r in best.items())
atable='\n'.join(f"| {q:,} | {fmt(by[f'A1_region_q{q}']['gbps'])} | {fmt(by[f'A2_region_q{q}']['gbps'])} |" for q in (128,256,512,1024,2048))
btable='\n'.join(f"| {q:,} | {fmt(by[f'B_region_q{q}']['gbps'])} |" for q in (512,8192,16384,32768))
placement='\n'.join(f"| {p} | {fmt(by[f'{p}_native_q512']['gbps'])} | {fmt(by[f'{p}_region_q512']['gbps'])} |" for p in ('A1','A2'))
occupancy='\n'.join(f"| {q:,} | "+' / '.join(f'{x:.1f}' for x in by[f'A1_region_q{q}']['per_port_outstanding'])+' |' for q in (256,512,1024,2048))
a=best['A1'];detail=read(OUT/'cases'/a['name']/'result.json')
ca=detail['config'];approx=32*16384*.85/(ca['ca_us']+(ca['short_us']+ca['mid_us'])/2+16384/(ca['io_gbps']*1000)+ca['turnaround_us'])/1000
util=sum(detail['fixed_channel_data_busy_pct'])/8
text=f'''# 새32Plane DIE 구조의 지속 처리량 측정

2026-10-12. **4 DIE × DIE당2 Channel × Channel당4 Plane**과 독립 CA·Data 경로를 사용한18개 조건을 측정했다. 최고 고정2ms 평균은 A1 **{fmt(best['A1']['gbps'])}GB/s**, A2 **{fmt(best['A2']['gbps'])}GB/s**, B **{fmt(best['B']['gbps'])}GB/s**다. 이는 측정한 조건 중 최고값이며 하드웨어 실측이나 모든 설정의 전역 최대값은 아니다.

## 측정 조건

- 4 Host Port, 독립 NAND Channel8개, Plane32개, 공유 데이터 버퍼8MiB.
- PF OFF, CA FIFO, 기존 고정 Port 수락 순서. 순환 수락으로 정책을 바꾸지 않았다.
- 가용률85%, tR Short2.00/Mid2.08/Long12.16/First·Group20.69µs 유지.
- Host 상한은 Port당64GB/s, 합계256GB/s. NAND Data는 채널당80.1125GB/s와 turnaround0.05µs.
- 2.2ms 지속 공급 중 초기200µs를 제외한 **200–2,200µs 고정2ms 평균**. 끝의 drain은 제외한다.
- A1은4KiB 순차, A2는4KiB 국소1-3-2 순열, B는 페이지 전체를 덮는64B 연속 요청. C1/C2는 각4KiB에서64B만 요청하는 희소 읽기.
- A1/B/C는4KiB stripe, A2는16KiB stripe. Port마다 독립적인256MiB 논리 영역을 사용한다.
- 영역별 배치는 각 영역에 **모든8개 Channel에서 Plane1개씩**을 배정한다. Channel과 페이지 내 offset, 페이지 패킹을 보존하며 전체 주소 영역에서 검증했다.

## 관측 최고값

아래 최고값은 모두 영역별 배치다. 최고500µs는 보조 수치이며 결론은 고정2ms 평균을 기준으로 한다. 소수점6자리에서 같은 최고 처리량이 여러 QD에서 나오면 더 작은 측정 QD를 먼저 표시한다.

| 패턴 | 최고값의 QD/Port | 고정2ms GB/s | 최고500µs GB/s |
|---|---:|---:|---:|
{overview}

## A1/A2: 배치와 QD

같은 QD512, 같은 FIFO와 자원에서 배치만 바꾼 대조다.

| 패턴 | 기본 배치 GB/s | 영역별 배치 GB/s |
|---|---:|---:|
{placement}

영역별 배치의 QD sweep은 다음과 같다.

| QD/Port | A1 GB/s | A2 GB/s |
|---|---:|---:|
{atable}

QD256/Port부터 약186GB/s 수준이며 QD512로 늘려도 성능 향상이 거의 없다. 큰 QD는 기존 고정 수락 방식에서 버퍼 편중을 일으킨다. A1의 실제 outstanding은 다음과 같다.

| 설정 QD/Port | 실제 outstanding 평균: Port0 / 1 / 2 / 3 |
|---|---|
{occupancy}

현재8MiB·고정 수락·영역별 배치에서 A의 실용적인 기준점은 **QD256/Port**다. 측정하지 않은 중간 QD까지 포함한 정확한 최소 포화값이라는 뜻은 아니다. 이번에 순환 수락의 효과를 다시 측정한 것은 아니며, 과거64Plane에서 확인한 순환 수락 수치를 이 표에 섞지 않았다.

## B: 같은 페이지를 전부 사용하는64B 요청

| QD/Port | 고정2ms GB/s |
|---|---:|
{btable}

요청 크기가 작으므로 A와 요청 수 기준 QD를 직접 비교하지 않는다. A QD256×4KiB와 B QD16,384×64B는 각각 Port당1MiB의 요청 payload 상한이다. 이 값이 실제 Controller buffer 점유나 요청 상태 메타데이터 비용과 같다는 뜻은 아니다. B도 충분한 QD에서는 A와 비슷한 약186GB/s 수준이다.

## 약186GB/s에서 포화되는 이유

A1의 관측 최고 조건에서 Long sensing 비율은 **{a['long_pct']:.3f}%**, 실제 유지보수 비율은 **{a['actual_unavailable_pct']:.3f}%**, 여덟 Data 경로의 평균 점유율은 **{util:.2f}%**다. Port별 처리량은 {', '.join(fmt(x) for x in a['per_port_gbps'])}GB/s다. 따라서 Host의256GB/s 상한이나 채널 Data 전송 상한을 채운 상태는 아니다.

현재 모델에서는 한 Plane이 CA→sensing→Data 전송을 마친 뒤 다음 읽기를 시작한다. Short/Mid가 반씩 발생하고 추가 대기가 없다고 근사하면 다음과 같다.

```text
Plane당 읽기 주기 ≈ 0.1 + 2.04 + 16KiB / 80.1125GB/s + 0.05
                  ≈ 2.3945µs
32Plane 공급량    ≈ 32 × 16KiB × 0.85 / 2.3945µs
                  ≈ {approx:.2f}GB/s
```

관측값은 이 근사치와 가깝다. **현재 조건의 병목은32개 Plane의 읽기 공급량으로 해석된다.** 이 계산은 First/Group, maintenance 위상·지연, 채널 대기, 유한 측정창 등을 생략한 설명용 근사이며 엄밀한 상한 증명은 아니다. tR·가용률·page buffer 동작 등을 바꾸면 결과가 달라진다. 과거64Plane의 약255GB/s는 다른 자원 구성의 결과다.

C1/C2는 현재도16KiB 전체를 NAND에서 출력하지만 Host가256B만 사용하므로 명목 유효 비율이1/64다. 각각 **{fmt(best['C1']['gbps'])}/{fmt(best['C2']['gbps'])}GB/s**이며, B를 포함한 모든64B 읽기의 상한으로 해석하지 않는다.

## 검증과 재현

모델 core를 바꾸지 않고 측정 harness만 추가했다. 소스·snapshot hash, 전체 주소 영역의 매핑, 고정 시간창 평균 재계산, Port별 요청 수 보존, QD·버퍼 상한과 in-order 반환을 확인했다. B/C의 CPU 최적화 observer는 새8채널 구조의 짧은 버퍼 압박 조건에서 참조 실행과 요청 타임스탬프·카운터·버퍼·NAND 이벤트·시간별 결과가 정확히 같은지 별도로 확인했다.

```sh
python3 -B scripts/measure_die32.py --phase all --workers 1
python3 -B scripts/measure_die32.py --phase validate
python3 -B scripts/validate_die32_observer.py
python3 -B scripts/report_die32.py
```

측정기는 저장된 결과를 건너뛰고 무결성을 검증한다. 실제 실행 당시 driver와 manifest는 `execution_provenance/`에 보존했다. 실행 후 driver는 문서 커밋으로 HEAD만 바뀐 경우에도 같은 소스·입력을 재사용할 수 있도록 manifest 비교만 보완했으며, 시뮬레이션·계측 로직은 동일하다. 새 실험을 재실행할 때는 별도 checkout에서 출력 디렉터리를 비운 상태로 실행한다. 저장된 manifest의 `source_commit`은 소스 기준 커밋이며 실제 측정 소스와 신규 harness는 `source_hashes`로 고정한다. 코드가 달라졌다면 해당 hash의 소스를 사용해야 한다.

- [요약 CSV](../results/znand/die32_performance/summary.csv)
- [실행별 result·25µs timeline](../results/znand/die32_performance/cases/)
- [소스·입력 manifest](../results/znand/die32_performance/manifest.json)
- [18개 조건 검증](../results/znand/die32_performance/validation.json)
- [최적화 observer 대조 검증](../results/znand/die32_performance/observer_validation.json)

정적 합성 배치, 지속 읽기, 고정 seed7 조건의 시뮬레이션이다. 동적 FTL, 실제 프로토콜·전력 제약이나 큰 QD의 메타데이터 구현 비용까지 제품 수준에서 검증한 자료는 아니다.
'''
(ROOT/'docs/19_die32_performance_ko.md').write_text(text)
print('Generated docs/19_die32_performance_ko.md')
