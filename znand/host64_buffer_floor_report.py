"""Summarize measured 200GB/s buffer crossings, without assuming monotonicity."""
import argparse
import json
from pathlib import Path

from .host64_buffer_floor import ROOT, TARGET, audit
from .pf_qd_sweep import digest, read


def summary(rows):
    groups = sorted({(r['pattern'], r['per_port']) for r in rows})
    capacities = sorted(set.intersection(*(
        {r['buffer_mib'] for r in rows if (r['pattern'], r['per_port']) == group}
        for group in groups)))
    all_pass = [m for m in capacities if all(r['bandwidth_gbps'] >= TARGET
                                            for r in rows if r['buffer_mib'] == m)]
    margin = [m for m in capacities if m == int(m) and all(r['bandwidth_gbps'] >= TARGET * 1.1
                                                         for r in rows if r['buffer_mib'] == m)]
    return dict(groups=groups, common_tested_mib=capacities,
                smallest_common_passing_mib=all_pass[0] if all_pass else None,
                smallest_tested_integer_mib_with_10pct_margin=margin[0] if margin else None,
                criterion='>=200 decimal GB/s whole cold-run average in every tested pattern/length group',
                limitation='Minimum among measured capacities, fixed seed/workloads/layout; not a global or hardware minimum.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT)
    args = parser.parse_args()
    out = args.out
    verified = audit(out)
    rows = read(out / 'rows.json')
    result = summary(rows)
    smallest = result['smallest_common_passing_mib']
    margin = result['smallest_tested_integer_mib_with_10pct_margin']
    get = lambda p, n, m: next((r for r in rows if
                               (r['pattern'], r['per_port'], r['buffer_mib']) == (p, n, m)), None)
    lines = ['# 개선 배치의 200GB/s Controller Buffer 하한 측정', '',
        f"**측정한 용량 중 A1/A2 × 8,192/32,768요청/port가 모두 전체 평균 200GB/s 이상을 유지한 최소 용량은 {smallest:g}MiB다.**" if smallest is not None else
        '**모든 패턴·길이가 통과한 공통 용량을 아직 관측하지 못했다.**', '',
        f"신규 실행 {verified['new_runs']}개와 정확히 같은 조건의 기존 16/32MiB 대조군 {verified['exact_reused_controls']}개를 사용했다. "
        '순간 최대치나 중간 완료 구간을 통과 판정에 사용하지 않는다. 첫 Host 요청 제시부터 마지막 반환까지의 유효 byte/시간이 기준이다.', '',
        '## 고정 조건', '',
        '| 항목 | 값 |', '|---|---|',
        '| 배치 | 기존 개선 배치 snapshot 그대로: 네 논리 영역별 Plane 그룹, 각 영역은 모든 channel 사용 |',
        '| Geometry / page buffer | 4channel × 16Plane = 총 64Plane, Plane당 16KiB page buffer 1개 |',
        '| Controller buffer | 공유 buffer_pages만 변경, 1개 = 16KiB, 1MiB = 64개 |',
        '| Host | 4port, 512bit·1GHz/port, 합산 256GB/s, port 내부 in-order |',
        '| QD / PF / 가용률 | 2,048/port / PF OFF / 85% |',
        '| tR | First 20.69 / Short 2.00 / Mid 2.08 / Long 12.16 / Group 20.69µs |',
        '| A1 | 4KiB 순차 읽기, stripe 4KiB, CA head_locality |',
        '| A2 | 4KiB의 1→3→2 지역 순열, stripe 16KiB, CA locality; uniform random 아님 |',
        '| 길이 / seed | 8,192 및 32,768요청/port / seed 7 |', '',
        'A1/A2 사이에는 stripe와 CA 정책 차이가 있다. 용량 효과는 같은 패턴·길이 안에서 비교한다. '
        '각 길이의 기존 snapshot을 그대로 사용하며 신규 배치 생성, QD 감소, tR 변경, PF 또는 cache 도입은 없다.', '',
        '## 전체 평균 처리량', '',
        '| 공유 버퍼 MiB | A1 8,192 GB/s | A2 8,192 GB/s | A1 32,768 GB/s | A2 32,768 GB/s | 네 조건 모두 ≥200 |',
        '|---:|---:|---:|---:|---:|---|']
    for mib in sorted({r['buffer_mib'] for r in rows}, reverse=True):
        group = [get(p, n, mib) for n in (8192, 32768) for p in ('A1', 'A2')]
        values = [f"{r['bandwidth_gbps']:.3f}" if r else '미측정' for r in group]
        verdict = ('미측정 포함' if any(r is None for r in group) else
                   '통과' if all(r['bandwidth_gbps'] >= TARGET for r in group) else '미달')
        lines.append(f"| {mib:g} | {' | '.join(values)} | {verdict} |")
    lines += ['', '![버퍼 용량별 전체 처리량](buffer_capacity.png)', '',
        '그래프의 선은 측정점을 연결한 시각적 안내이며, 미측정 용량의 예측값이 아니다. 원으로 강조한 점은 각 패턴·길이의 최소 통과 측정점이다.', '',
        '## 패턴·길이별 관측 경계', '',
        '| 패턴 | 요청/port | 바로 아래 측정 용량 MiB | 해당 GB/s | 최소 통과 측정 용량 MiB | 해당 GB/s |',
        '|---|---:|---:|---:|---:|---:|']
    for item in verified['minima']:
        lo = item['nearest_lower_tested_mib']
        hi = item['minimum_tested_passing_mib']
        lines.append(f"| {item['pattern']} | {item['per_port']:,} | " +
                     (f"{lo:g} | {item['nearest_lower_gbps']:.6f}" if lo is not None else '미측정 | —') + ' | ' +
                     (f"{hi:g} | {item['passing_gbps']:.6f}" if hi is not None else '미측정 | —') + ' |')
    lines += ['', '위 하한은 측정한 용량 집합에서의 최소 통과점이다. 인접 두 용량 사이의 모든 16KiB 슬롯 수를 전수 조사한 절대 최소값이 아니다. '
        '스케줄링 순서가 변할 수 있으므로 용량과 성능의 단조 증가를 가정하거나 선형 보간하지 않는다. 실제 비단조 구간은 validation.json의 nonmonotonic_steps에 기록한다.', '']
    if margin is not None:
        group = [r for r in rows if r['buffer_mib'] == margin]
        lines += [f"측정한 정수 MiB 중 네 조건 모두 200GB/s 대비 10% 이상 여유를 갖는 첫 용량은 **{margin:g}MiB**다. "
                  f"해당 용량의 최저 처리량은 {min(r['bandwidth_gbps'] for r in group):.3f}GB/s다. "
                  '이 여유는 이번 네 조건에서만 확인된 것이며, 실제 제품의 안전 여유를 검증했다는 뜻은 아니다.', '']
    lines += ['## 긴 요청열의 지연·점유·Long 변화', '',
        '| 버퍼 MiB | 패턴 | 전체 GB/s | 중간 GB/s | Long % | 평균 버퍼 MiB | Peak MiB | 평균 outstanding/port | 평균 수락 대기 µs | p99 offer µs |',
        '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for row in sorted((r for r in rows if r['per_port'] == 32768),
                      key=lambda r: (-r['buffer_mib'], r['pattern'])):
        long_pct = 100 * row.get('count_tr_long', 0) / row['count_sensing_reads']
        lines.append(f"| {row['buffer_mib']:g} | {row['pattern']} | {row['bandwidth_gbps']:.3f} | "
                     f"{row['middle_bandwidth_gbps']:.3f} | {long_pct:.4f} | {row['diag_buffer_mean_total_mib']:.3f} | "
                     f"{row['buffer_peak_pages']/64:.3f} | {row['mean_outstanding_per_port']:.1f} | "
                     f"{max(0., row['mean_admission_wait_us']):.3f} | {row['p99_offer_latency_us']:.3f} |")
    lines += ['', '버퍼 점유는 Host 요청 수락 시점부터의 예약 공간을 포함한다. 용량 축소는 대기·sensing·완료 데이터의 공간뿐 아니라 수락 가능한 물리 페이지 수를 제한한다. '
        '실제 수락량, 발행 가능한 Plane 작업, port 선두 대기 및 물리 페이지 재접근이 달라질 수 있다. '
        '원인 설명은 관측한 Long 비율·지연·점유와 함께 읽어야 하며, 성능 저하를 무조건 Long 증가로 단정하지 않는다.', '',
        '## 작은 버퍼의 Port별 진행 불균형', '',
        '| 버퍼 MiB | A2 Port 0 완료 µs | Port 1 | Port 2 | Port 3 |',
        '|---:|---:|---:|---:|---:|']
    for mib in sorted({16, 8, 7.5, 6, 4, 2, 1} | ({smallest} if smallest else set()), reverse=True):
        row = get('A2', 32768, mib)
        if row:
            lines.append(f"| {mib:g} | " + ' | '.join(f'{v:.3f}' for v in row['port_completion_us']) + ' |')
    boundary = [get(p, 32768, 7.5) for p in ('A1', 'A2')]
    if all(boundary):
        deadline = boundary[0]['host_bytes'] / (TARGET * 1000)
        lines += ['', f'32,768요청/port의 총 Host 데이터는 512MiB다. 전체 200GB/s를 넘으려면 마지막 반환이 {deadline:.3f}µs 이내에 끝나야 한다. '
            f"7.5MiB에서 A1 마지막 반환은 {boundary[0]['elapsed_us']:.3f}µs, A2는 {boundary[1]['elapsed_us']:.3f}µs다. "
            '같은 용량에서 통과 여부가 갈리는 이유를 마지막 Port의 완료 시간으로 확인할 수 있다.']
    lines += ['', '현재 admission은 매번 Port 0→1→2→3 순서로 수락을 시도하고, 공유 버퍼에 각 물리 페이지의 공간을 예약한다. '
        '일반 payload 공간의 port별 공평한 분배를 강제하지 않으며, 별도 진행성 보호 슬롯은 선두가 없는 port를 위한 것이다. '
        '작은 버퍼의 완료 시간 불균형은 이 수락 정책과 영역별 Plane 배치가 함께 작용했을 가능성을 보여준다. '
        '공정 수락 정책으로 바꾼 대조 실험은 이번에 하지 않았으므로 특정 정책만의 인과 효과로 확정하지 않는다. '
        '이번 하한은 현재 admission·스케줄러까지 포함한 값이며, NAND 자체가 요구하는 절대 SRAM 용량으로 해석하지 않는다.', '',
        '## 범위와 후속 튜닝', '',
        '- 이번 기준은 네 논리 영역의 균형 부하, A1/A2 4KiB 읽기, 정적 배치와 seed 7에 한정한다.',
        '- 한 영역 집중, 1~3 활성 port, 실제 동적 L2P·GC/WL, write 혼합, 64B 패턴, PF ON은 별도 조건이다.',
        '- 회사의 더 큰 요청 수 원본 조건은 아직 확보하지 않았으므로 해당 길이의 200GB/s 유지 여부를 확인한 결과로 취급하지 않는다.',
        '- 기본 32MiB 및 기존 16MiB 프로파일을 보존한다. 이번 용량별 profiles를 명시적으로 선택해 재현한다.',
        '- 다음 검증은 선택한 용량과 여유 용량을 고정한 뒤 다른 seed·부하 편향·실제 snapshot으로 비교한다.', '',
        '## 재현 및 검증', '', '```sh',
        'python3 -m znand.host64_buffer_floor --workers 4',
        '# 경계의 추가 용량은 --mib로 지정하며 기존 결과에 추가한다.',
        'python3 -m znand.host64_buffer_floor --validate-only',
        'python3 -m znand.host64_buffer_floor_report', '```', '',
        '그래프는 matplotlib가 있는 환경에서 `python3 -m znand.host64_buffer_floor_plot`으로 생성한다. 수치 실행·검증에는 matplotlib가 필요하지 않다.', '',
        'cases.json은 실행한 모든 용량·패턴·길이를 보존한다. 추가 경계 용량을 포함해 완전히 재현하려면 '
        '`--mib ' + ' '.join(f'{m:g}' for m in sorted({r['buffer_mib'] for r in rows})) + '`를 지정한다.', '',
        '모델/계측 코드와 snapshot 해시, 기준 결과의 정확한 재사용, buffer_pages 외 Config 일치, CSV/JSON 일치, '
        '요청량·반환 순서·버퍼/QD 한도·지연 분해·상태별 버퍼 점유 회계를 검증했다.', '',
        '[전체 CSV](sweep.csv) · [결과 JSON](rows.json) · [검증 및 개별 경계](validation.json) · '
        '[공통 경계 요약](summary.json) · [실행 조건](cases.json) · [용량별 프로파일](profiles/)']
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    (out / 'RESULTS_KO.md').write_text('\n'.join(lines) + '\n')
    (out / 'report_manifest.json').write_text(json.dumps(dict(
        source_sha256=digest(__file__), sweep_sha256=digest(out / 'sweep.csv'),
        report_sha256=digest(out / 'RESULTS_KO.md'), summary_sha256=digest(out / 'summary.json')),
        indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
