"""Report paired controller-buffer measurements without changing model timing."""
import json
from .host64_buffer import ROOT, audit
from .pf_qd_sweep import digest, read


def main():
    out = ROOT
    audit(out)
    rows = read(out / 'rows.json')
    get = lambda p, n, layout, mib: next(r for r in rows if
        (r['pattern'], r['per_port'], r['layout'], r['buffer_mib']) == (p, n, layout, mib))
    labels = {'baseline': '기존 배치', 'region_layout': '개선 배치'}
    excluded = {'name', 'case_id', 'variant', 'source', 'runtime_seconds', 'buffer_pages', 'buffer_mib'}
    metric_comparisons = []
    for n in (8192, 32768):
        for p in ('A1', 'A2'):
            for layout in labels:
                a, b = get(p, n, layout, 32), get(p, n, layout, 16)
                differences = [k for k in sorted(a.keys() | b.keys()) if k not in excluded and a.get(k) != b.get(k)]
                metric_comparisons.append(dict(pair=a['pair'], layout=layout,
                    execution_metric_differences=differences,
                    all_execution_metrics_identical=not differences))
    region_same = all(c['all_execution_metrics_identical'] for c in metric_comparisons if c['layout'] == 'region_layout')
    heading = ('**현재 개선 배치에서는 controller buffer를 32MiB에서 16MiB로 줄여도 성능이 동일했다.** '
               if region_same else '**Controller buffer 32MiB와 16MiB를 동일 조건에서 비교했다.** ')
    lines = ['# 64Plane Controller Buffer 16MiB 비교', '',
        heading + 'A1/A2와 8,192/32,768요청/port를 평가했다. 기존 배치도 별도로 비교해 배치에 따른 용량 민감도를 구분한다.', '',
        '## 비교 조건', '',
        '16MiB 조건 8개를 새로 실행하고, 같은 모델과 설정으로 검증된 32MiB 결과 8개를 대조군으로 재사용했다. 과거 32Plane·다른 정책의 16MiB 결과는 이번 비교에 섞지 않았다.', '',
        '| 항목 | 32MiB 대조군 | 16MiB 실험 |', '|---|---|---|',
        '| Controller buffer | 16KiB 공간 2,048개 | 16KiB 공간 1,024개 |',
        '| NAND | 4channel × 16Plane = 총 64Plane | 동일 |',
        '| NAND page buffer | Plane당 16KiB 1개, 총 1MiB | 동일 |',
        '| Host / outstanding | 4port, 2,048/port | 동일 |',
        '| tR μs | First 20.69 / Short 2.00 / Mid 2.08 / Long 12.16 / Group 20.69 | 동일 |',
        '| Prefetch / 가용률 | OFF / 85% | 동일 |',
        '| 요청 | A1/A2, 4KiB, 8,192 또는 32,768개/port, seed 7 | 동일 |',
        '| 주소 배치 / CA 및 Data 정책 | 이전 64Plane 측정 프로파일 | 동일 |', '',
        '**각 비교 쌍에서 바뀐 Config 항목은 `buffer_pages` 하나뿐이다.** L2P snapshot, QD, tR, port 내부 in-order, CA/Data 속도와 지연을 유지했다. A1과 A2 사이에는 기존 stripe 및 CA 정책 차이가 있으므로 같은 패턴 안에서 용량 효과를 비교한다.', '',
        '## 처리량과 Long 비율', '',
        '| 요청/port | 패턴 | 배치 | 32MiB GB/s | 16MiB GB/s | 변화 | Long 비율 32→16MiB |',
        '|---:|---|---|---:|---:|---:|---:|']
    for n in (8192, 32768):
        for layout in labels:
            for p in ('A1', 'A2'):
                a, b = get(p, n, layout, 32), get(p, n, layout, 16)
                pct = lambda r: 100 * r.get('count_tr_long', 0) / r['count_sensing_reads']
                lines.append(f"| {n:,} | {p} | {labels[layout]} | {a['bandwidth_gbps']:.6f} | {b['bandwidth_gbps']:.6f} | {(b['bandwidth_gbps']/a['bandwidth_gbps']-1)*100:+.3f}% | {pct(a):.4f}% → {pct(b):.4f}% |")
    lines += ['', '처리량은 첫 요청 제시부터 마지막 반환까지의 전체 평균이다. Long 비율은 전체 NAND sensing 횟수 대비 Long sensing 횟수이며, Host 요청 수 또는 실행 시간 대비 비율이 아니다.', '',
        '## 버퍼 점유와 지연', '',
        '다음은 32,768요청/port의 긴 조건이다. Peak와 평균 점유는 수락 시 예약한 페이지 공간을 포함한다.', '',
        '| 패턴 | 배치 | 용량 MiB | Peak MiB | 평균 점유 MiB | 평균 outstanding/port | p99 offer μs | 중간 구간 GB/s |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for layout in labels:
        for p in ('A1', 'A2'):
            for mib in (32, 16):
                r = get(p, 32768, layout, mib)
                lines.append(f"| {p} | {labels[layout]} | {mib} | {r['buffer_peak_pages']/64:.3f} | {r['diag_buffer_mean_total_mib']:.3f} | {r['mean_outstanding_per_port']:.1f} | {r['p99_offer_latency_us']:.3f} | {r['middle_bandwidth_gbps']:.3f} |")
    lines += ['', '## 용량 변경이 동작에 미치는 영향', '',
        'Controller buffer는 단순한 최종 응답 보관 공간이 아니다. Host 요청 수락 시 해당 16KiB 물리 페이지의 공간을 예약하며, 공간이 부족하면 수락을 늦춘다. 같은 페이지를 읽는 요청들은 예약 공간을 공유한다. 이 때문에 용량을 줄이면 보이는 요청 집합과 NAND 발행 순서, Long 비율까지 달라질 수 있다.', '']
    if region_same:
        lines += ['개선 배치 네 쌍에서는 처리량·지연·Long 횟수·자원 계측 등 실행 지표가 모두 정확히 일치했다. 기존 32MiB 실행의 peak가 약 10~12MiB였고, 이번 16MiB 실행에서도 예약 공간과 진행성 보호 여유가 충분해 용량 제한이 동작을 바꾸지 않았다.', '',
                  '**이 개선 배치와 평가 workload에 대해서는 16MiB로 줄일 근거가 확보됐다.** 이번 측정만으로 16MiB를 모든 workload의 최소 용량으로 확정하지 않는다. 기존 배치, 부하 편향, 실제 L2P, 더 긴 요청열, PF ON 조건은 각각의 용량 민감도를 따라야 한다. 회사에서 실행했다는 더 큰 요청 수의 원본 조건은 아직 확보되지 않았으므로 해당 길이의 16MiB 성능을 검증한 결과로 취급하지 않는다.', '']
    for p in ('A1', 'A2'):
        a, b = get(p, 32768, 'baseline', 32), get(p, 32768, 'baseline', 16)
        lines.append(f"기존 배치에서 {p} 처리량은 32→16MiB에서 {a['bandwidth_gbps']:.3f}→{b['bandwidth_gbps']:.3f}GB/s ({(b['bandwidth_gbps']/a['bandwidth_gbps']-1)*100:+.2f}%)다. Long 횟수는 {a.get('count_tr_long',0):,}→{b.get('count_tr_long',0):,}회, 평균 수락 대기는 {a['mean_admission_wait_us']:.3f}→{b['mean_admission_wait_us']:.3f}μs다.")
        lines.append('')
    lines += ['이 값들은 용량 변경 후 함께 관측된 결과다. 버퍼가 작을수록 항상 빨라지거나 느려진다는 일반 규칙으로 해석하지 않는다. 스케줄링 정책은 동일하며, 용량 제한으로 달라진 요청 수락과 실행 순서의 영향을 포함한다.', '',
        '## 재현과 검증', '', '```sh',
        'python3 -m znand.host64_buffer --workers 4',
        'python3 -m znand.host64_buffer --validate-only',
        'python3 -m znand.host64_buffer_report',
        'python3 -m znand.run --config results/znand/planes64_buffer16/profiles/A2_64Plane_n32768_region_layout_b16.json --pattern A2 --per-port 32768 --out results/local/A2_64Plane_16MiB',
        '```', '',
        '모델·계측 소스 해시, 대조군의 원본 지표 일치, snapshot 해시, 버퍼만 다른 8개 비교 쌍, CSV/JSON 일치와 회계 검증을 통과했다. 신규 실행은 port별 in-order와 자원 한도를 검사했다. 기존 기본 프로파일을 덮어쓰지 않고 16MiB 실행 프로파일을 별도로 제공한다.', '',
        '[전체 CSV](sweep.csv), [결과 JSON](rows.json), [실행 조건](cases.json), [프로파일](profiles/), [검증](validation.json), [지표별 동일성 비교](metric_comparison.json), [실행 소스 해시](manifest.json), [32MiB 원본 결과](../planes64/RESULTS_KO.md).']
    (out / 'metric_comparison.json').write_text(json.dumps(metric_comparisons, indent=2) + '\n')
    (out / 'RESULTS_KO.md').write_text('\n'.join(lines) + '\n')
    (out / 'report_manifest.json').write_text(json.dumps(dict(
        source_sha256=digest('znand/host64_buffer_report.py'), sweep_sha256=digest(out / 'sweep.csv'),
        report_sha256=digest(out / 'RESULTS_KO.md'), comparison_sha256=digest(out / 'metric_comparison.json')), indent=2) + '\n')
    print('16/32MiB paired report generated; all region execution metrics identical:', region_same)


if __name__ == '__main__':
    main()
