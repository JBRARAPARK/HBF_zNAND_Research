"""Explain B-pattern dips with maintenance controls and a concrete in-order stall."""
import json
from pathlib import Path

from .partial_dip_diagnosis import ROOT
from .pf_qd_sweep import digest, read


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    results = {(p,c):read(ROOT/(p+'_'+c+'.json')) for p in ('B1','B2') for c in ('100','off','200')}
    assert read(ROOT/'validation.json')['status'] == 'passed'
    manifest = read(ROOT/'manifest.json')
    assert all(digest(k)==v for k,v in manifest['hashes'].items())
    fig, axes = plt.subplots(2,2,figsize=(13,7.5),sharex=True,sharey=True)
    for column, pattern in enumerate(('B1','B2')):
        for row, controls in enumerate((('100','off'),('100','200'))):
            ax=axes[row,column]
            for control in controls:
                data=[r for r in results[pattern,control]['bins'] if r['t_start_us']>=200]
                label={'100':'85% availability, 100 us period','off':'Maintenance OFF (diagnostic)','200':'85% availability, 200 us period'}[control]
                color={'100':'#222222','off':'#d95f02','200':'#1b9e77'}[control]
                ax.plot([(r['t_start_us']+r['t_end_us'])/2 for r in data], [r['bandwidth_gbps'] for r in data], label=label,color=color,lw=1.4)
            ax.set_title(pattern+(' | Remove maintenance' if row==0 else ' | Change maintenance period'))
            ax.set_xlim(200,1200)
            ax.set_ylim(2.4,5.1)
            ax.set_ylabel('Host useful throughput (GB/s)')
            ax.grid(alpha=.2)
            ax.spines[['top','right']].set_visible(False)
            ax.legend(fontsize=8,loc='lower right')
        axes[1,column].set_xlabel('Time from first request (us), 25 us bins')
    fig.suptitle('Periodic Plane maintenance delays the port head; in-order return exposes the delay',fontsize=13)
    fig.text(.5,.012,'4 ports, 64 Planes, 8 MiB, QD512/port, PF OFF. Same tR and in-order policy in all controls.\n'
             'Maintenance OFF is a causal diagnostic only. Original 85% baseline remains unchanged.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.06,1,.95))
    outputs=[]
    for suffix in ('png','pdf'):
        path=ROOT/('maintenance_control.'+suffix);fig.savefig(path,dpi=160,bbox_inches='tight');outputs.append(path)
    plt.close(fig)
    b=results['B1','100'];example=b['examples'][0]
    lines=['# B1/B2 시간 그래프의 주기적 하락 원인','',
           '작성일: 2026-10-11. 직전 64B 지속 부하 실험의 파형 원인을 확인하는 진단이며 기준 모델의 변경이 아니다.','',
           '**주된 원인은 주기적 Plane maintenance 지연과 port 내부 in-order 반환이 결합한 Head-of-Line 대기다.** 내부 NAND Data 전송은 계속되지만, 늦은 선두 요청 때문에 이미 준비된 후속 응답을 반환하지 못한다.','',
           '## 대조 실험','',
           '4port·64Plane·8MiB·QD512/port·개선 영역 배치·PF OFF·기존 tR·기존 in-order를 고정했다. 다음 세 조건을 B1/B2 각각 실행했다.','',
           '- 기준: 가용률 85%, 100µs 주기, Plane당 명목 15µs off.',
           '- 원인 제거 대조: 가용률 100%, maintenance OFF. 성능 기준선에 채택한 변경이 아니다.',
           '- 주기 대조: 가용률 85% 유지, 200µs 주기, Plane당 명목 30µs off.','',
           '첫 요청부터 1.2ms까지 관측하고 초기 200µs를 제외한 **200–1,200µs의 고정 1ms**를 비교한다. 아래 평균은 이전 보고서의 고정 2ms 평균과 관측 길이가 다르다. 원래 85%/100µs 두 실행의 모든 25µs 계측 값은 이전 2.2ms 실행의 첫 1.2ms 구간과 일치했다.','',
           '| 패턴 | maintenance 조건 | Host 평균 GB/s | 25µs 최솟값 | 25µs 최댓값 | 25µs 표준편차 | NAND 평균 GB/s |',
           '|---|---|---:|---:|---:|---:|---:|']
    for (p,c),r in results.items():
        w=r['fixed'];lines.append(f"| {p} | {c+'µs / 85%' if c!='off' else 'OFF / 100%'} | {w['bandwidth_gbps']:.4f} | {w['bin_min_gbps']:.4f} | {w['bin_max_gbps']:.4f} | {w['bin_std_gbps']:.4f} | {w['nand_mean_gbps']:.3f} |")
    lines+=['',
            'Maintenance를 끄면 큰 주기적 낙폭이 거의 사라진다. 평균은 약 4GB/s로 비슷하지만 짧은 구간의 반환 분포가 크게 안정된다. 85%를 유지하면서 주기를 바꾸면 기존 100µs 위치에 모였던 낙폭의 모양도 달라진다. 따라서 기존의 규칙적 파형을 NAND 고유의 100µs 동작이나 실제 GC 주기로 해석하지 않는다.','',
            '![Maintenance 대조](maintenance_control.png)','',
            '## 실제 선두 요청의 정지 사례','',
            f"B1 기준의 Port {example['port']}, 물리 주소 `(channel, plane, page)={tuple(example['key'])}`에서 다음 동작을 관측했다. 시간은 첫 Host 요청을 0으로 둔다.",'',
            f"- {example['start_us']:.3f}µs: 해당 요청이 port FIFO의 선두가 되지만 데이터가 준비되지 않아 반환이 멈춘다.",
            f"- 해당 Plane의 maintenance 구간: {example['maintenance_intervals_us'][0][0]:.3f}–{example['maintenance_intervals_us'][0][1]:.3f}µs.",
            f"- 선두 대기와 직접 겹친 maintenance 시간: {example['direct_head_plane_maintenance_overlap_us']:.3f}µs.",
            f"- 대기 구간 중간 시점에는 뒤쪽 요청 **{example['ready_followers_at_midpoint']}개가 이미 반환 가능한 데이터로 준비**돼 있지만 port 내부 in-order 조건 때문에 기다린다.",
            f"- {example['end_us']:.3f}µs: 선두 데이터가 준비되어 반환을 시작한다. 선두로 인한 전체 반환 중단은 **{example['duration_us']:.3f}µs**다.",'',
            '| 페이지 동작 | 시작 시각 µs | 세부 |','|---|---:|---|']
    for event in example['page_events']:
        detail = event.get('tr_kind','')
        if 'duration' in event:detail+=f" duration={event['duration']:.6f}µs"
        lines.append(f"| {event['event']} | {event['time_us']:.6f} | {detail} |")
    lines+=['',
            '이 요청의 sensing은 **Mid tR=2.08µs**다. Long tR 증가로 이 정지 구간을 설명하지 않는다. 긴 부분은 Plane maintenance 대기이며, 이후 CA·sensing·NAND Data 대기/전송·ECC를 거쳐 준비된다. 다른 Plane의 미래 요청들은 그동안 진행할 수 있으므로 내부 NAND 총 처리량은 약 257GB/s를 유지한다.','',
            '동작 흐름은 `선두 페이지 지연 → 후속 ready 응답 누적 → port 반환 정지 → 선두 준비 → 누적 응답 반환`이다. 준비된 데이터가 한꺼번에 반환되는 구간에서는 25µs Host 처리량이 약 4GB/s의 장기 공급량보다 높아질 수 있다. 버퍼에 먼저 준비된 데이터를 방출하는 것이며 장기 공급 상한과 모순되지 않는다.','',
            '## B에서 왜 더 뚜렷한가','',
            '현재 Host 인터페이스에서 64B 반환은 1ns, 4KiB 반환은 64ns다. B 패턴은 준비된 작은 응답을 빠르게 반환한 뒤 다음 선두의 준비를 기다리는 동작이 드러난다. 준비가 밀리면 긴 공백이 생기고, 해소되면 쌓인 응답을 빠르게 반환한다. A/B의 크기 차이는 이 파형을 이해하는 요인이며, 이번 대조에서 직접 확인한 주된 원인은 maintenance에 따른 준비 시점 불균형과 in-order 선두 정지다.','',
            '25µs bin은 이 반환의 몰림과 공백을 보여 준다. 시간 폭을 100µs나 500µs로 넓히면 골과 봉우리가 평균에 함께 들어가 더 평평해 보이지만, 선두 정지 자체가 해결되는 것은 아니다. B1/B2 원래 패턴은 페이지를 한 번씩 방문하는 부분 읽기이며 이 낙폭을 cache miss나 PF 실패로 해석하지 않는다. PF는 OFF다.','',
            '## 현재 유지보수 모델의 의미와 후속 검토','',
            '가용률 85%는 실제 GC 작업열을 재생한 값이 아니라 Plane별 주기적 off로 구현된다. Plane별 초기 위상은 seed에 따라 다르며 모든 Plane이 동시에 15µs 멈추는 구조는 아니다. Plane이 busy이면 off 시작이 지연되고 대기 maintenance가 누적될 수 있다. 하지만 같은 100µs 주기를 반복하므로 이런 규칙적 낙폭이 만들어질 수 있다.','',
            '사용자가 정한 port 내부 in-order와 기준 85%는 유지한다. 후속 튜닝은 (1) 이미 수락한 선두와 가까운 미래 요청의 준비 우선순위, (2) 유지보수 시점의 분산 또는 실제 GC/프로그램/소거 trace를 이용한 비효율 모델링, (3) 반환 가능 데이터량·선두 정지 시간의 동시 계측으로 분리한다. 평균 가용률만 같은 모델끼리도 짧은 구간 파형은 달라질 수 있다. 실제 hardware GC가 이 주기로 발생한다고 주장하지 않는다.','',
            '## 검증과 재현','',
            '- 6개 실행의 설정 차이는 `availability` 또는 `maintenance_period_us` 하나뿐이다. 기준 두 실행은 차이가 없다.',
            '- 두 기준 실행은 이전 결과의 전체 48개 bin과 모든 계측 항목이 일치했다. 관측용 trace만 추가했으며 이벤트나 실행 정책을 추가하지 않았다.',
            '- NAND model.py, 기존 A/B harness, tR와 in-order는 그대로다. `validation.json`과 `manifest.json`에 설정 차이와 hash를 보존한다.',
            '- `B1_100.json` 등 6개 JSON에 고정 구간 요약·원시 bin·실제 maintenance 구간·선두 정지 사례와 페이지 동작 기록을 저장한다. CSV는 bin 데이터다.','',
            '```sh','python3 -m znand.partial_dip_diagnosis','python3 -m znand.partial_dip_report','```','']
    report=ROOT/'RESULTS_KO.md';report.write_text('\n'.join(lines));outputs.append(report)
    (ROOT/'report_manifest.json').write_text(json.dumps(dict(source_sha256=digest(__file__),
        input_sha256={str(ROOT/(p+'_'+c+'.json')):digest(ROOT/(p+'_'+c+'.json')) for p,c in results},
        outputs={str(p):digest(p) for p in outputs}),indent=2)+'\n')
    print(report)


if __name__=='__main__':
    main()
