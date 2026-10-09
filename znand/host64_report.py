"""Report the fresh, fixed-tR 64Plane measurements."""
import json
from .host64_measure import ROOT, REFERENCE, LENGTHS, TIMINGS, audit
from .pf_qd_sweep import digest, read


def mean_tr(row):
    return sum(row.get('count_tr_' + key.removesuffix('_us'), 0) * value
               for key, value in TIMINGS.items()) / row['count_sensing_reads']


def main():
    out = ROOT
    audit(out)
    rows = read(out / 'rows.json')
    previous = read(REFERENCE / 'rows.json')
    get = lambda p, n, v: next(r for r in rows if r['pattern'] == p and r['per_port'] == n and r['variant'] == v)
    old = lambda p, v: next(r for r in previous if r['pattern'] == p and r['planes'] == 8 and r['variant'] == v)
    labels = {'baseline': '기존 배치', 'region_layout': '영역별 Plane 배치'}
    a1 = get('A1', 32768, 'region_layout')
    a2 = get('A2', 32768, 'region_layout')
    lines = [
        '# 64Plane 고정 tR 성능 측정', '',
        f"**4channel × 16Plane = 총 64Plane으로 8개 조건을 새로 시뮬레이션했다.** PF OFF·기존 tR·32MiB buffer·QD2,048/port에서 32,768요청/port의 영역 배치 A1/A2 전체 처리량은 **{a1['bandwidth_gbps']:.3f}/{a2['bandwidth_gbps']:.3f}GB/s**, 중간 완료 구간은 **{a1['middle_bandwidth_gbps']:.3f}/{a2['middle_bandwidth_gbps']:.3f}GB/s**다.", '',
        '이번 비교는 기존 배치와 주소 영역별 Plane 배치를 각각 8,192 및 32,768요청/port로 측정했다. 과거 결과를 복사하지 않고 모두 실행했으며, 짧은 조건 네 개는 이전 64Plane 결과의 지표와 정확히 일치했다. 32Plane 비교값만 이전 검증 결과를 인용한다.', '',
        '## 실행 조건', '',
        '| 항목 | 값 |', '|---|---|',
        '| Geometry | 4channel × 16Plane/channel = 총 64Plane |',
        '| Host | 4port, 512bit·1GHz/port, 합산 명목 256GB/s |',
        '| Port 연결 | 각 port가 주소에 따라 모든 channel 접근 |',
        '| 반환 | 각 port 내부 strict in-order |',
        '| 요청 / NAND 페이지 | 4KiB / 16KiB |',
        '| Controller buffer | 공유 32MiB, 16KiB 공간 2,048개 |',
        '| Outstanding | 2,048/port, 설정 합계 최대 8,192 |',
        '| Prefetch | OFF |',
        '| 가용률 | 85%, 100μs maintenance 주기, Plane별 위상 분산 |',
        '| CA / Data / turnaround | 0.1μs / 80.1125GB/s per channel / 0.05μs |',
        '| Lookup / ECC | 0.5μs / 0.2μs |',
        '| A1 | 연속 4KiB 요청, stripe 4KiB, CA head_locality |',
        '| A2 | 1→3→2 지역 순열, stripe 16KiB, CA locality |',
        '| Seed / 시작 상태 | 7 / 빈 controller buffer와 초기 NAND 이력 |', '',
        '**tR는 First 20.69 / Short 2.00 / Mid 2.08 / Long 12.16 / Group 20.69μs로 고정했다.** 이번 8개 조건에는 모든 tR=2μs 또는 가용률 100%의 가상 진단이 없다. 모델 소스와 스케줄러를 수정하지 않고 64Plane 실행 프로파일과 측정 실행기를 추가했다.', '',
        '모델의 `planes`는 채널당 수다. 설정은 `channels=4, planes=16`이며 `planes=64`가 아니다. CA/Data는 계속 네 channel에서 공유한다. Die/LUN 공유 제약을 추가한 실제 장치 성능 예측과는 구분한다.', '',
        '## 전체 측정 결과', '',
        '| 패턴 | 요청/port | 배치 | 전체 GB/s | Host 명목 대비 | 중간 완료 GB/s | p99 offer μs | 평균 tR μs | Long 횟수 |',
        '|---|---:|---|---:|---:|---:|---:|---:|---:|',
    ]
    for length in LENGTHS:
        for pattern in ('A1', 'A2'):
            for variant in labels:
                r = get(pattern, length, variant)
                lines.append(f"| {pattern} | {length:,} | {labels[variant]} | {r['bandwidth_gbps']:.3f} | {100*r['bandwidth_gbps']/256:.2f}% | {r['middle_bandwidth_gbps']:.3f} | {r['p99_offer_latency_us']:.3f} | {mean_tr(r):.6f} | {r.get('count_tr_long',0):,} |")
    lines += ['', '전체 처리량은 첫 요청 제시부터 마지막 응답 완료까지의 Host 유효 byte/시간이다. 중간 완료 구간은 완료 요청의 가운데 절반으로, 장시간 정상 상태를 자동으로 의미하지 않는다. p99 offer는 수락 전 대기까지 포함한다. 단위 GB/s는 decimal, MiB는 binary다.', '',
              '## 같은 요청 수에서 32Plane과 비교', '',
              '아래는 모두 8,192요청/port다. 기존 배치끼리의 비교는 실행 Config에서 Plane 수만 8→16/channel로 바뀐다. 영역 배치끼리는 Plane 수에 맞춰 각 영역에 배정한 Plane 수도 2→4/channel로 늘어나므로 snapshot이 함께 바뀐다.', '',
              '| 패턴 | 배치 | 32Plane GB/s | 64Plane GB/s | 변화 |',
              '|---|---|---:|---:|---:|']
    for pattern in ('A1', 'A2'):
        for variant in labels:
            b, r = old(pattern, variant), get(pattern, 8192, variant)
            lines.append(f"| {pattern} | {labels[variant]} | {b['bandwidth_gbps']:.3f} | {r['bandwidth_gbps']:.3f} | {(r['bandwidth_gbps']/b['bandwidth_gbps']-1)*100:+.2f}% |")
    lines += ['', 'Plane 확장 효과와 배치 효과를 한 증가율에 섞지 않는다. 64Plane의 배치 효과는 같은 요청 수에서 위 전체 표의 기존 배치와 영역 배치를 비교한다.', '',
              '## 요청 길이를 늘렸을 때', '',
              '8,192→32,768요청/port는 총 Host 데이터 128→512MiB다. 요청 길이에 맞춰 합성 snapshot도 다시 생성했다. 기존의 작은 snapshot에 요청 길이만 늘려 누락된 주소를 읽는 방식은 사용하지 않았다. Workload 생성기는 길이에 따라 port별 논리 주소 영역의 span도 늘리므로 길이 간 차이를 초기 지연 희석 효과만으로 단정하지 않는다.', '',
              '| 패턴 | 영역 배치 128MiB GB/s | 영역 배치 512MiB GB/s | 변화 | 512MiB 모델 내 소요 시간 μs |',
              '|---|---:|---:|---:|---:|']
    for p in ('A1', 'A2'):
        b, r = get(p, 8192, 'region_layout'), get(p, 32768, 'region_layout')
        lines.append(f"| {p} | {b['bandwidth_gbps']:.3f} | {r['bandwidth_gbps']:.3f} | {(r['bandwidth_gbps']/b['bandwidth_gbps']-1)*100:+.2f}% | {r['elapsed_us']:.3f} |")
    limits = read(REFERENCE / 'bounds.json')
    cold = 4 * 32768 * 4096 / (32768 * 4096 / 64000 + limits['minimum_first_ready_us']) / 1000
    lines += ['', f'최초 준비 지연 21.744512μs만 포함하고 이후 Host 반환이 계속 포화된다고 가정하면, 이번 512MiB cold 실행의 상한도 약 **{cold:.3f}GB/s**다. 유한 실행 전체 평균의 목표를 256GB/s와 동일하게 두지 않는다. 길이를 늘린 이번 한 조건이 모든 주소 분포·seed의 지속 성능을 보장하지는 않는다.', '',
              '## 남은 손실과 자원 사용', '',
              '| 패턴 | 32,768요청 배치 | 평균 Data busy | 평균 buffer MiB | buffer peak MiB | 평균 outstanding/port | 실제 내부 점유 |',
              '|---|---|---:|---:|---:|---:|---:|']
    for p in ('A1', 'A2'):
        for v in labels:
            r = get(p, 32768, v)
            busy = sum(r['channel_data_busy_us']) / (4*r['elapsed_us']) * 100
            lines.append(f"| {p} | {labels[v]} | {busy:.3f}% | {r['diag_buffer_mean_total_mib']:.3f} | {r['buffer_peak_pages']/64:.3f} | {r['mean_outstanding_per_port']:.1f} | {r['actual_unavailable_fraction']*100:.3f}% |")
    lines += ['', 'Data busy는 channel별 전송 예약 시간 합계를 전체 Host 측정 시간으로 나눈 기존 계측값이다. 시작·종료 공백을 포함하며 중간 구간 활용률과 구분한다. Buffer는 payload뿐 아니라 수락 시 예약한 공간도 포함한다. 실제 내부 점유는 실행 구간에서 측정하며 결과에 15%를 추가로 감산하지 않는다.', '',
              '기존 배치는 buffer peak가 32MiB 용량에 도달하지만, 영역 배치는 약 12MiB에서 끝난다. 평균 예약량도 약 29.6→10.6MiB로 줄었다. **이번 영역 배치의 다음 개선을 buffer 증설부터 시작할 근거는 약하다.** 32MiB를 줄여도 같은 성능이 유지되는지는 별도 용량 비교가 필요하며, 평균 outstanding이 약 668~674라고 해서 QD를 그 값으로 줄일 수 있다는 뜻도 아니다.', '',
              'NAND Data 경로는 페이지별 turnaround 50ns까지 포함하면 합산 상한이 약 257.496GB/s로 Host 256GB/s에 매우 가깝다. 따라서 64Plane에서는 Long 감소와 함께 Data 전송 공백·port 선두 대기·초기 및 종료 구간이 남은 차이를 좌우한다. 평균 tR 감소는 고정된 tR 종류의 발생 비율이 달라진 결과다.', '',
              '영역 배치는 각 channel 안의 PL0~3, PL4~7, PL8~11, PL12~15에 네 논리 영역을 분산한다. 각 영역은 네 channel을 모두 사용한다. 주소에 따른 정적 L2P이며 port와 channel의 고정 연결이 아니다. A2 trace 끝의 다음 영역 접근 세 개를 유지했고, 공유 물리 페이지는 하나의 위치에만 대응시켰다.', '',
              '## 다음 튜닝 기준', '',
              '- 이후 성능 비교는 총 64Plane, 기존 tR, PF OFF를 기준으로 실행한다. 기존 32Plane 자료는 geometry 비교 기준으로 보관한다.',
              '- 영역 배치의 균형 부하 이득과 실제 동적 L2P의 효과를 구분한다. 다음 확장 대상은 부하 편향, 다른 seed, 1~4 활성 port, 실제 매핑 snapshot이다.',
              '- 이번 실행은 A1/A2의 4KiB 읽기다. B1/B2/B3의 64B 패턴이나 write 혼합 성능까지 확장 해석하지 않는다.',
              '- QD 및 buffer를 다시 조정할 때는 같은 64Plane·배치·요청 길이에서 한 변수씩 비교하고, Data 공백과 port별 지연을 함께 확인한다.', '',
              '## 재현과 검증', '',
              '```sh',
              'python3 -m znand.host64_measure --workers 4',
              'python3 -m znand.host64_measure --validate-only',
              'python3 -m znand.host64_report',
              'python3 -m znand.run --config results/znand/planes64/profiles/A2_64Plane_n32768_region_layout.json --pattern A2 --per-port 32768 --out results/local/A2_64Plane_long',
              '```', '',
              '같은 출력 폴더의 재실행은 검증된 완료 조건을 유지한다. 전체를 다시 측정하려면 `--out results/local/planes64_fresh`처럼 새 폴더를 지정한다. 개별 프로파일의 snapshot은 표시된 요청 길이에 맞는 유한 매핑이므로 길이와 함께 선택한다.', '',
              '8개 결과의 요청량·지연 분해·buffer/QD 한도·PF OFF·port별 in-order를 확인했다. 모든 tR 입력값과 모델 해시, 결과 CSV/JSON 일치, 네 배치 쌍의 snapshot 외 설정 일치, snapshot 1:1 대응·channel·offset 보존을 검증했다. 짧은 네 실행은 이전 64Plane의 모든 공통 성능·계측 지표와 일치한다.', '',
              '[전체 CSV](sweep.csv), [결과 JSON](rows.json), [실행 조건](cases.json), [프로파일](profiles/), [배치 검증](snapshot_validation.json), [종합 검증](validation.json), [실행 소스 해시](manifest.json), [이전 상한 분석](../host_ceiling/RESULTS_KO.md).']
    (out / 'RESULTS_KO.md').write_text('\n'.join(lines) + '\n')
    (out / 'report_manifest.json').write_text(json.dumps(dict(
        source_sha256=digest('znand/host64_report.py'), sweep_sha256=digest(out / 'sweep.csv'),
        report_sha256=digest(out / 'RESULTS_KO.md')), indent=2) + '\n')
    print('64Plane report generated.')


if __name__ == '__main__':
    main()
