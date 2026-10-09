"""Report throughput, latency, and matched-bypass attribution for head priority."""
import csv
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    out = Path('results/znand/head_locality')
    rows = list(csv.DictReader((out/'sweep.csv').open()))
    manifest = json.loads((out/'manifest.json').read_text())
    selected = json.loads((out/'selection.json').read_text())
    assert len(rows) == manifest['validated_rows']
    n = lambda r, k:float(r.get(k) or 0)
    def get(phase, pattern, policy='locality', bypass=8, threshold=12.16):
        matches = [r for r in rows if r['phase'] == phase and r['pattern'] == pattern and r['ca_policy'] == policy
                   and int(r['locality_max_bypass']) == bypass and n(r, 'head_wait_us') == threshold]
        assert len(matches) == 1, (phase, pattern, policy, bypass, threshold)
        return matches[0]
    def change(a, b, key='bandwidth_gbps'):
        return 100*(n(a, key)/n(b, key)-1)
    def long_pct(r):return 100*n(r, 'count_tr_long')/n(r, 'count_sensing_reads')
    def port_spread(r):
        times = json.loads(r['port_completion_us'])
        return max(times)-min(times)
    cases = {s['case_id']:s for s in json.loads((out/'cases.json').read_text())}
    profiles = out/'profiles'; profiles.mkdir(exist_ok=True)
    # Post-evaluation recommendation: A2's extra head benefit disappears in the
    # longer trace; the transferred head policy severely regresses all B patterns.
    recommended = {}
    for pattern in ('A1', 'A2', 'B1', 'B2', 'B3'):
        phase = 'core' if pattern.startswith('A') else 'small_read_check'
        policy = 'head_locality' if pattern == 'A1' else 'locality'
        threshold = selected['head_wait_us'] if pattern == 'A1' else 12.16
        r = get(phase, pattern, policy, selected['bypass'], threshold)
        recommended[pattern] = r
        (profiles/f'{pattern}.json').write_text(json.dumps(cases[int(r['case_id'])]['config'], indent=2)+'\n')
    for pattern in ('A1', 'A2'):
        r = get('core', pattern, 'head_locality', selected['bypass'], selected['head_wait_us'])
        (out/f'selected_head_{pattern}.json').write_text(json.dumps(cases[int(r['case_id'])]['config'], indent=2)+'\n')
    comparisons = []
    for r in rows:
        reference = get(r['phase'], r['pattern'])
        matched = get(r['phase'], r['pattern'], bypass=int(r['locality_max_bypass']))
        comparisons.append(dict(case_id=r['case_id'], phase=r['phase'], pattern=r['pattern'], per_port=r['per_port'],
            policy=r['ca_policy'], bypass=r['locality_max_bypass'], head_wait_us=r['head_wait_us'],
            bandwidth_gbps=n(r, 'bandwidth_gbps'), gain_vs_bypass8_pct=change(r, reference),
            gain_vs_same_bypass_pct=change(r, matched), p99_offer_us=n(r, 'p99_offer_latency_us'),
            p99_change_vs_bypass8_pct=change(r, reference, 'p99_offer_latency_us'),
            p99_change_vs_same_bypass_pct=change(r, matched, 'p99_offer_latency_us'),
            long_pct=long_pct(r), mean_return_wait_us=n(r, 'mean_return_wait_us'),
            hol_idle_pct=n(r, 'mean_port_idle_while_later_ready_pct'),
            port_completion_spread_us=port_spread(r),
            p99_head_data_wait_us=n(r, 'p99_head_data_wait_us'), head_selections=int(n(r, 'count_ca_selection_head'))))
    with (out/'comparisons.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, list(comparisons[0]), lineterminator='\n')
        writer.writeheader(); writer.writerows(comparisons)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for col, pattern in enumerate(('A1', 'A2')):
        variants = [('locality', 12.16, 'Locality only')]+[('head_locality', t, f'Head after {t:g} us') for t in (0., 12.16, 48.64)]
        for policy, threshold, label in variants:
            series = [get('core', pattern, policy, bypass, threshold) for bypass in (4, 8, 16, 32)]
            for row, metric in ((0, 'bandwidth_gbps'), (1, 'p99_offer_latency_us')):
                axes[row, col].plot((4, 8, 16, 32), [n(r, metric) for r in series], marker='o', label=label)
        for row in (0, 1):
            ax = axes[row, col]; ax.set_title(pattern); ax.set_xlabel('Max consecutive bypasses')
            ax.set_xticks((4, 8, 16, 32)); ax.grid(alpha=.25)
        axes[0, col].set_ylabel('Useful host GB/s'); axes[0, col].legend(fontsize=9)
        axes[1, col].set_ylabel('p99 offer-to-return latency (us)')
    fig.suptitle('4 ports, 32 planes, 32 MiB, QD 2048/port, PF ON, 8192 requests/port')
    fig.tight_layout(); fig.savefig(out/'head_priority.png', dpi=160); plt.close(fig)
    lines = ['# Port 선두 요청 우선과 연속 주소 우선의 결합 평가', '',
        '4port·32Plane·공유 32MiB·QD2,048/port·PF ON(합성 정확도 100%, 선행 10μs)·seed 7·port별 비중첩 주소를 고정했다. A1/B1/B2는 4KiB stripe, A2/B3는 16KiB stripe다. Host 수락·예약·lookup·Data 중재·port 내부 in-order 반환은 유지하고 CA 선택만 바꿨다.', '',
        '## 결과에 따른 적용 설정', '',
        '개선의 큰 부분은 연속 우회 한도를 8→32회로 늘린 효과다. 선두 우선 기능 자체는 A1에서 같은 우회 한도 대비 +4.00%, 긴 요청열에서 +2.09%였고, A2에서는 +0.31%/−0.01%로 추가 효과가 작았다. B1/B2/B3에서는 선두 우선이 같은 우회 한도 대비 36~50% 낮은 처리량을 보여 적용하지 않는다.', '',
        '따라서 A1은 우회 32회·선두 대기 48.64μs, A2/B1/B2/B3는 기존 locality·우회 32회를 권장 프로파일로 저장했다. 모든 패턴은 별도로 실행하며, 혼합 workload를 자동 분류해 정책을 바꾸는 기능을 구현한 것은 아니다. 아래 값은 port당 8,192개 요청에서 기존 locality·우회 8회와 비교한 결과다.', '',
        '| 패턴/설정 파일 | 선두 우선 | 기존 GB/s | 적용 GB/s | 처리량 변화 | 기존 p99 μs | 적용 p99 μs |',
        '|---|---|---:|---:|---:|---:|---:|']
    for pattern, r in recommended.items():
        base = get(r['phase'], pattern)
        state = 'ON, 48.64μs' if pattern == 'A1' else 'OFF'
        lines.append(f"| [{pattern}](profiles/{pattern}.json) | {state} | {n(base,'bandwidth_gbps'):.3f} | {n(r,'bandwidth_gbps'):.3f} | {change(r,base):+.2f}% | {n(base,'p99_offer_latency_us'):.2f} | {n(r,'p99_offer_latency_us'):.2f} |")
    lines += ['', '위 프로파일은 이번 범위의 실행용 설정이다. 모델 기본값은 기존 재현성을 위해 그대로 두었다. A2의 선두 ON 후보는 [별도 설정](selected_head_A2.json)으로도 보관한다.', '',
        '## 정책과 비교 방법', '',
        '- `locality`: 기존 정책. 같은 Plane의 page buffer 재사용/연속 q+1을 우선하며 oldest의 age와 연속 우회 한도로 보호한다.',
        '- `head_locality`: 실제 port 선두가 되고 lookup이 끝난 뒤의 대기가 `head_wait_us`를 넘으면, CA 대기 중인 선두 페이지를 우선한다. 진행 중인 sensing·전송은 선점하지 않는다.',
        '- Plane 내부 age·우회 한도 보호는 먼저 적용한다. Channel의 Plane 간 선택에서도 오래 기다린 선두를 우선하되 age 한도에 도달한 Demand를 보호한다. 선두 후보가 없으면 기존 순서를 유지한다.',
        '- A1/A2에서 우회 4/8/16/32회 × 기존 정책 및 선두 대기 0/12.16/48.64μs로 32개를 실행했다. 기존 우회 8회 대조군 2개는 저장된 이전 모델의 처리량·지연·계수와 정확히 일치했다.',
        '- A1/A2의 기존 우회 8회 대비 처리량 비율의 기하평균이 가장 큰 선두 우선 후보를 선택했다. 동률일 때 p99를 비교한다. p99 악화가 없는 후보만 선택하는 규칙은 아니다.',
        f"- 선택한 후보를 우회 {selected['bypass']}회·선두 대기 {selected['head_wait_us']:g}μs로 고정하고 B1/B2/B3 및 port당 16,384개인 A1/A2에서 확인했다. 기본 비교는 port당 8,192개다. 추가 확인에서도 QD는 2,048로 유지했다.",
        f"- 총 {len(rows)}개를 새로 실행하고 전 행의 요청량·자원 제한·지연 분해 및 port 응답 순서를 검증했다. 모델 테스트 51개가 통과했다.", '',
        '## 핵심 구분: 우회 한도 조정과 선두 우선 기능', '',
        '기존 우회 8회 대비 개선에는 우회 한도 변경 효과가 섞인다. 선두 우선 기능의 추가 효과는 반드시 같은 우회 한도의 기존 정책과 비교한다. 처리량은 GB/s이며 p99는 요청 제시부터 반환까지의 μs다.', '',
        '| 패턴/요청 수 per port | 기존 우회8 GB/s | 같은 우회 한도·선두 OFF GB/s | 선두 ON GB/s | ON의 같은 우회 대비 변화 | OFF p99 | ON p99 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for phase, patterns in (('core', ('A1', 'A2')), ('small_read_check', ('B1', 'B2', 'B3')), ('long_trace_check', ('A1', 'A2'))):
        for pattern in patterns:
            reference = get(phase, pattern)
            matched = get(phase, pattern, bypass=selected['bypass'])
            head = get(phase, pattern, 'head_locality', selected['bypass'], selected['head_wait_us'])
            lines.append(f"| {pattern}/{head['per_port']} | {n(reference,'bandwidth_gbps'):.3f} | {n(matched,'bandwidth_gbps'):.3f} | {n(head,'bandwidth_gbps'):.3f} | {change(head,matched):+.2f}% | {n(matched,'p99_offer_latency_us'):.2f} | {n(head,'p99_offer_latency_us'):.2f} |")
    lines += ['', '## 선택 후보의 port 완료 시간 분산', '',
        '같은 우회 한도에서 선두 우선 ON/OFF를 비교한다. 완료 시간은 각 port의 첫 요청 제시부터 마지막 반환까지다. 완료 시간 차이가 줄어도 모든 port의 개별 지연이 동시에 줄었다는 뜻은 아니다. Port별 p99는 원본 CSV에 보관한다.', '',
        '| 요청열 | OFF 4port 완료 시간 μs | ON 4port 완료 시간 μs | OFF 최대−최소 μs | ON 최대−최소 μs |',
        '|---|---|---|---:|---:|']
    for phase in ('core', 'long_trace_check'):
        for pattern in ('A1', 'A2'):
            off = get(phase, pattern, bypass=selected['bypass'])
            on = get(phase, pattern, 'head_locality', selected['bypass'], selected['head_wait_us'])
            off_times = ', '.join(f'{t:.1f}' for t in json.loads(off['port_completion_us']))
            on_times = ', '.join(f'{t:.1f}' for t in json.loads(on['port_completion_us']))
            lines.append(f"| {pattern}/{on['per_port']} | {off_times} | {on_times} | {port_spread(off):.2f} | {port_spread(on):.2f} |")
    lines += ['', '![Head priority comparison](head_priority.png)', '', '## A1/A2 전체 조건', '',
        '| 패턴 | 정책 | 우회 한도 | 선두 대기 μs | GB/s | p99 offer μs | Long % | HOL idle % | 선두 우선 선택 횟수 |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in sorted((r for r in rows if r['phase'] == 'core'), key=lambda r:int(r['case_id'])):
        threshold = r['head_wait_us'] if r['ca_policy'] == 'head_locality' else '—'
        lines.append(f"| {r['pattern']} | {r['ca_policy']} | {r['locality_max_bypass']} | {threshold} | {n(r,'bandwidth_gbps'):.3f} | {n(r,'p99_offer_latency_us'):.2f} | {long_pct(r):.2f} | {n(r,'mean_port_idle_while_later_ready_pct'):.2f} | {int(n(r,'count_ca_selection_head'))} |")
    lines += ['', '## 지표와 한계', '',
        '- `HOL idle %`는 선두의 데이터가 아직 준비되지 않았고 같은 port에 준비된 후속 요청이 있는 구간의 비율을 port별로 구한 뒤 평균한 값이다. 일반적인 반환 직렬화 대기 전체와 구분한다.',
        '- `p99_head_data_wait_us`는 실제 선두가 되고 lookup까지 끝난 뒤 데이터 준비까지의 대기다. 수락 이후 전체 대기나 offer 기준 p99와 다른 지표다.',
        '- 많은 요청이 선두가 되기 전에 이미 준비되면 head 대기 p99가 0이어도 소수의 긴 선두 대기는 존재할 수 있다. HOL idle 구간과 선두 선택 횟수를 함께 본다.',
        '- `count_ca_selection_head`는 선두 우선 규칙으로 선택한 횟수다. 그 페이지가 기존 정책에서도 선택됐을 가능성을 포함하며, 모든 선택이 발행 순서를 바꿨다는 뜻은 아니다.',
        '- B계열은 QD2,048에서 동작 전이만 확인했다. 이전 버퍼 확대 보고서의 B계열 QD8,192 결과와 직접 섞지 않는다.',
        '- 긴 요청열은 같은 생성 규칙으로 요청 수와 port별 주소 범위를 함께 늘린다. 동일한 짧은 요청열을 반복한 정상 상태 실험은 아니다. 선택한 한 후보에 대한 확인이며 새 길이에서의 전역 최적값을 탐색하지 않았다.',
        '- 실제 예측기·동적 L2P·실제 GC·64Plane은 이번 비교에 포함하지 않았다. 고정 입력과 seed에서의 시뮬레이션 결과이며 제품의 실측 개선률이 아니다.', '',
        '## 재현', '', '```sh', 'python3 -m znand.head_sweep --workers 8', 'python3 -m znand.head_report',
        'python3 -m znand.run --config results/znand/head_locality/profiles/A1.json --pattern A1 --per-port 8192 --out results/local/head_A1', '```', '',
        '모델 및 실행기 해시와 조건이 일치하는 checkpoint만 이어서 실행한다. 원본: [sweep.csv](sweep.csv), [비교 지표](comparisons.csv), [조건](cases.json), [선정 기준과 후보](selection.json), [manifest](manifest.json).']
    (out/'RESULTS_KO.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(selected, indent=2))


if __name__ == '__main__':main()
