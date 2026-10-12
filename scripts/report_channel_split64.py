"""Report measured 4x16 versus 8x8 channel bandwidth comparisons."""
import measure_channel_split64 as measure
measure.audit()
rows=measure.read(measure.OUT/'summary.json')
lookup={(r['variant'],r['pattern']):r for r in rows}
lines=['# 총64Plane 유지: 4×16 → 8×8 Channel 분할과 대역폭 비교','',
'기존4 Channel × 16 Plane을8 Channel × 8 Plane으로 바꾸었다. 총 Plane 수는64개이며 DIE 계층은 추가하지 않았다. 채널당 Data 대역폭을 유지한 조건과 절반으로 낮춘 조건을 모두 측정했다. 기존4×16의 최신 검증 결과를 대조군으로 사용한다.','',
'6개 새 실행에서 A1/A2/B는 BW 유지와 절반 조건 모두256.00GB/s였다. 기존255.28~255.36GB/s 대비 약0.25~0.28% 높은 동급의 Host 처리량이다. 채널당BW를40.05625GB/s로 줄여 전체 raw BW를 기존과 동일하게 맞춰도 이번 부하에서는 성능이 유지됐다.','',
'## 측정 결과','',
'초기200µs를 제외한0.2–2.2ms 평균, 단위GB/s. Host 전체 상한은256GB/s다.','',
'| 구성 | 채널당 Data BW | 전체 raw Data BW | A1 | A2 | B |',
'|---|---:|---:|---:|---:|---:|']
old=[lookup['full_bw',p]['reference_gbps'] for p in measure.PATTERNS]
lines.append('| 기존4 Channel × 16 Plane | 80.1125 | 320.450 | '+' | '.join(f'{x:.3f}' for x in old)+' |')
for v,label in [('full_bw','8 Channel × 8 Plane, BW 유지'),('half_bw','8 Channel × 8 Plane, BW 절반')]:
 r=lookup[v,'A1']
 lines.append(f"| {label} | {r['io_gbps']:.5f} | {r['aggregate_raw_io_gbps']:.3f} | "+' | '.join(f"{lookup[v,p]['gbps']:.3f}" for p in measure.PATTERNS)+' |')
lines+=['','| 요청 | BW 유지: 기존 대비 | BW 절반: 기존 대비 | BW 유지 후반/전반 변화 | BW 절반 후반/전반 변화 |','|---|---:|---:|---:|---:|']
for p in measure.PATTERNS:
 a=lookup['full_bw',p];b=lookup['half_bw',p]
 lines.append(f"| {p} | {a['delta_pct']:+.3f}% | {b['delta_pct']:+.3f}% | {a['second_vs_first_pct']:+.3f}% | {b['second_vs_first_pct']:+.3f}% |")
bounds=[]
for channels,bw in ((4,80.1125),(8,80.1125),(8,40.05625)):
    duration=16384/(bw*1000)+.05
    bounds.append(dict(channels=channels,io_gbps=bw,turnaround_us=.05,data_duration_us=duration,
        aggregate_raw_gbps=channels*bw,ideal_data_path_payload_gbps=channels*16384/duration/1000))
measure.save(measure.OUT/'data_path_bounds.json',dict(formula='channels * 16384 / (16384 / (io_gbps * 1000) + 0.05) / 1000',
    scope='Data paths continuously supplied; excludes sensing, maintenance, CA contention, ECC and Host limits',cases=bounds))
lines+=['','## 해석','',
'**총 Plane 수가 같다고 처리량이 수학적으로 동일해지는 것은 아니다.** 채널 수가 바뀌면 공유하는 CA·Data 경로의 수와 Plane 간 경쟁이 바뀐다. 채널당80.1125GB/s를 그대로 유지하면 전체 raw Data BW는320.45→640.90GB/s로 늘어난다. 다만 Host 상한256GB/s에 이미 가까운 부하에서는 그 증가가 Host 처리량에 거의 드러나지 않을 수 있다.','',
'**전체 raw Data BW를 기존과 같게 맞추는 값은 채널당40.05625GB/s**다.8×40.05625 = 4×80.1125 = 320.45GB/s다. 이 값으로 실행 가능한 별도 프로파일과 실제 측정 결과를 제공한다. BW를 절반으로 줄인다고 정확히 같은 완료 시각이나 처리량을 보장하는 것은 아니다. CA 시간과 turnaround는 그대로이므로, 페이지당 Data 전송 시간과 Plane을 점유하는 시간이 달라진다.','',
'기존4채널의 Data 전환 시간0.05µs를 포함한 이상적인 Data 경로 합계 상한은257.496GB/s다.8채널·BW 절반에서는285.544GB/s다. 계산은 `채널수 × 16384 / (16384 / (채널당BW × 1000) + 0.05) / 1000`이며, Data가 계속 준비되어 있다는 가정의 경로 상한이다. sensing·유지보수·Host 제한까지 포함한 전체 장치 성능 상한과 구분한다. 따라서 총 raw BW를 동일하게 맞춰도 약255GB/s와256GB/s의 결과가 정확히 같을 필요는 없다.',
'',
'이 비교는 현재 Host 상한·부하·배치·QD·관측 구간에 한정한다. 표의 처리량은 시뮬레이션 결과이며 전체 raw Data BW 또는 제품 사양과 동일한 값이 아니다.','',
'## 통제한 조건과 배치 차이','',
'- 총64Plane,4 Host Port, 공유8MiB, PF OFF, CA FIFO, round-robin 수락, 기존 tR·가용률85%·seed7 유지.',
'- A1/A2는4KiB 읽기·QD512/Port, B는 페이지 전체를 소비하는64B 연속 읽기·QD32,768/Port 유지.',
'- 영역별 배치 규칙을 유지: 각 Port의 주소 영역은 모든 Channel을 쓰며 다른 영역과 Plane을 공유하지 않는다.4×16에서는 영역당 채널별4Plane,8×8에서는 영역당 채널별2Plane이어서 영역당 총16Plane은 같다.',
'- 채널 수에 맞춰 native packing과 snapshot을 재생성했다. 특히4KiB stripe에서는 같은16KiB 물리 페이지에 묶이는 논리 주소 조합이 바뀔 수 있다. 따라서 동일한 물리 주소열을 고정한 순수 버스 개수 실험이라고 주장하지 않는다.',
'- 유지보수의85%·100µs 주기·seed는 같으나 채널/Plane 인덱스가 바뀌면 위상도 재배정된다. 작은 수치 차이에 이 영향도 포함된다.',
'- BW 유지↔절반 두8×8 조건 사이에는 `io_gbps`만 바꾼다. 주소 배치와 유지보수 인덱스도 동일하다.','',
'## Port별 처리량과 공급','',
'| 조건 | 요청 | Port별 GB/s | Port별 실제 outstanding 평균 | NAND Data GB/s |','|---|---|---|---|---:|']
for r in rows:
 lines.append(f"| {r['variant']} | {r['pattern']} | "+' / '.join(f'{v:.2f}' for v in r['per_port_gbps'])+' | '+' / '.join(f'{v:,.1f}' for v in r['per_port_outstanding'])+f" | {r['fixed_nand_gbps']:.3f} |")
lines+=['','## 검증과 실행','',
'- 전체100개 테스트 통과.8×8의64Plane 주소 packing, snapshot 형상 일치,8개 독립 Data 경로, BW 절반의 전송 시간, 작은 버퍼 진행성 및64B 최적화 실행의 동일성을 검증했다.',
'- 변경 전4×16 모델 소스와6개 짧은 부하를 비교하여 모든 결과 지표·요청 시각이 그대로임을 확인했다.2ms 대조군 수치는 직전 복원 실험을 재사용하며 새로 측정한 값처럼 표시하지 않는다.',
'- 두 stripe의 전체 주소 영역에서 snapshot 일대일 대응,16KiB 페이지 내4개 offset, 영역당16Plane, 모든8Channel 사용을 확인했다.',
'- 6개 새 실행에서 소스·설정·snapshot·과거 결과 해시,2ms 집계, Port별 수락−완료=outstanding, QD 상한과8MiB 용량을 검증했다.',
'- [원본 결과](../results/znand/channel_split64/summary.json), [검증](../results/znand/channel_split64/validation.json), [기존 모델 회귀 대조](../results/znand/channel_split64/legacy_regression.json), [배치 검증](../results/znand/channel_split64/snapshot_validation.json).','',
'```sh',
'python3 -B scripts/measure_channel_split64.py',
'python3 -B scripts/measure_channel_split64.py --validate',
'python3 -B scripts/report_channel_split64.py','```','',
'[채널당 BW 유지 프로파일](../configs/channel_split64/full_bw/)과 [채널당 BW 절반 프로파일](../configs/channel_split64/half_bw/)을 제공한다. 기존4×16 복원 프로파일과 결과도 대조용으로 보존한다.','']
(measure.ROOT/'docs/23_channel_split64_ko.md').write_text('\n'.join(lines))
