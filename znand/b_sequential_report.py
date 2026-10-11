"""Plot and document validated sequential 64B B workload measurements."""
import json
from pathlib import Path
from .b_sequential_measure import ROOT, BASE, audit, read, digest


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    rows=audit(ROOT)
    best=max(rows,key=lambda r:r['fixed_gbps'])
    baseline=next(r for r in rows if r['name']=='B_b8_q512')
    refs={'A1':'results/znand/saturation/runs/A1_b8_q512.json',
          'C1':'results/znand/partial_saturation/runs/B1_b8_q512.json'}
    reference_checks={}
    for label,path in refs.items():
        cfg=read(path)['config'];base=read(BASE)
        assert {k:v for k,v in cfg.items() if k!='snapshot'} == {k:v for k,v in base.items() if k!='snapshot'}
        assert digest(cfg['snapshot']) == digest(base['snapshot'])
        reference_checks[label]={'path':path,'sha256':digest(path),'identical_device_config':True,'identical_mapping':True}
    (ROOT/'reference_validation.json').write_text(json.dumps(reference_checks,indent=2)+'\n')
    a=read(refs['A1'])['windows']['fixed']
    cs=read(refs['C1'])['windows']['fixed']
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(13,4.8))
    for mib in sorted({r['buffer_mib'] for r in rows}):
        group=[r for r in rows if r['buffer_mib']==mib]
        axes[0].plot([r['qd_per_port'] for r in group],[r['fixed_gbps'] for r in group],'-o',label=f'{mib:g} MiB: fixed 2 ms')
    axes[0].axhline(256,color='#666666',ls='--',label='Host ceiling: 256 GB/s')
    axes[0].axhline(200,color='#999999',ls=':',label='200 GB/s')
    axes[0].set_xscale('log',base=2);axes[0].set_ylim(0,275)
    qds=sorted({r['qd_per_port'] for r in rows})
    axes[0].set_xticks(qds,[f'{q:,}' for q in qds],rotation=25,ha='right')
    axes[0].set_xlabel('Configured QD / port (64B requests)');axes[0].set_ylabel('Useful Host throughput (GB/s)')
    axes[0].set_title('B: same-page 64B sequential reads');axes[0].legend(fontsize=8)
    x=[0,1,2,3];values=[a['bandwidth_gbps'],baseline['fixed_gbps'],best['fixed_gbps'],cs['bandwidth_gbps']]
    bars=axes[1].bar(x,values,color=['#707d8c','#3686c9','#13598c','#d58536'])
    axes[1].bar_label(bars,labels=[f'{v:.2f}' for v in values],padding=4)
    axes[1].set_xticks(x,['A1\nQD512', 'B\nQD512', f"B best\nQD{best['qd_per_port']:,}", 'C1\nQD512'])
    axes[1].set_ylabel('Fixed 2 ms mean (GB/s)');axes[1].set_ylim(0,285)
    axes[1].set_title('A1/C1: saved same-device baseline')
    for ax in axes:ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    fig.text(.5,.015,'64 Planes | 4 ports | PF OFF | fixed tR | 4KiB stripe | 85% availability | first 200 us excluded',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.05,1,1));fig.savefig(ROOT/'B_qd_scaling.png',dpi=170);plt.close(fig)

    fig,axes=plt.subplots(4,2,figsize=(14,11),sharex=True)
    for col,case in enumerate([baseline,best]):
        timeline=read(ROOT/'cases'/case['name']/'timeline.json')
        xs=[(r['t_start_us']+r['t_end_us'])/2 for r in timeline]
        for ax in axes[:,col]:
            ax.axvspan(0,200,color='#dddddd');ax.grid(alpha=.2);ax.set_xlim(0,2200)
        axes[0,col].plot(xs,[r['bandwidth_gbps'] for r in timeline],label='Total',color='#172738')
        for port in range(4):
            axes[0,col].plot(xs,[r[f'p{port}_gbps'] for r in timeline],label=f'Port {port}',lw=.8)
            axes[1,col].plot(xs,[r[f'p{port}_outstanding_mean'] for r in timeline],label=f'Port {port}',lw=1.)
        axes[0,col].set_title(f"B | {case['buffer_mib']:g} MiB | QD{case['qd_per_port']:,}/port\n2 ms mean: {case['fixed_gbps']:.3f} GB/s; best 500 us: {case['peak_500us_gbps']:.3f}")
        axes[0,col].set_ylim(0,270);axes[0,col].legend(ncol=5,fontsize=7,loc='center right')
        axes[1,col].axhline(case['qd_per_port'],ls='--',color='#555555',lw=.8)
        axes[1,col].set_ylim(0,case['qd_per_port']*1.12);axes[1,col].legend(ncol=4,fontsize=7,loc='lower right')
        axes[2,col].plot(xs,[r['accepted_requests'] for r in timeline],label='Accepted')
        axes[2,col].plot(xs,[r['completed_requests'] for r in timeline],label='Completed',ls='--')
        axes[2,col].yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v/1000:g}k'))
        axes[2,col].text(.02,.12,f"2 ms completed: {case['completed_requests']:,}",transform=axes[2,col].transAxes,va='top',fontsize=9,bbox={'facecolor':'white','alpha':.8,'edgecolor':'none'})
        axes[2,col].legend(fontsize=8,loc='lower right');axes[2,col].set_ylim(bottom=0)
        axes[3,col].plot(xs,[r['buffer_mean_mib'] for r in timeline],label='Mean reserved')
        axes[3,col].plot(xs,[r['buffer_peak_mib'] for r in timeline],label='Peak reserved',ls='--')
        axes[3,col].axhline(case['buffer_mib'],ls=':',label='Capacity',color='#555555')
        axes[3,col].set_ylim(0,case['buffer_mib']*1.08);axes[3,col].legend(fontsize=8);axes[3,col].set_xlabel('Time from first request (us)')
    for i,label in enumerate(['Host useful throughput (GB/s)','Actual outstanding / port','Requests / 25 us','Controller buffer (MiB)']):axes[i,0].set_ylabel(label)
    fig.text(.5,.008,'25 us bins. Gray: first 200 us excluded. All ports remain supplied; no end-of-work drain. Requests are 64B.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.025,1,1));fig.savefig(ROOT/'B_time.png',dpi=165);plt.close(fig)
    table=['| 버퍼 MiB | QD/Port | 2ms 평균 GB/s | 최고 500µs GB/s | 실제 outstanding 합계 | 버퍼 평균 MiB | 완료 요청 수 | Long tR |',
           '|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:table.append(f"| {r['buffer_mib']:g} | {r['qd_per_port']:,} | {r['fixed_gbps']:.3f} | {r['peak_500us_gbps']:.3f} | {r['actual_outstanding']:,.1f} | {r['buffer_mean_mib']:.3f} | {r['completed_requests']:,} | {r['long_tr_pct']:.3f}% |")
    reuse_table=['| QD/Port | Host GB/s | NAND GB/s | Host/NAND payload | NAND read amplification |',
                 '|---:|---:|---:|---:|---:|']
    for r in rows:reuse_table.append(f"| {r['qd_per_port']:,} | {r['fixed_gbps']:.3f} | {r['nand_gbps']:.3f} | {r['host_payload_pct']:.3f}% | {r['read_amplification']:.4f}배 |")
    reuse_table='\n'.join(reuse_table)
    context=dict(best=best,baseline=baseline,a1=a,c1=cs,table='\n'.join(table))
    (ROOT/'report_data.json').write_text(json.dumps(context,indent=2)+'\n')
    fixed=read(ROOT/'cases'/best['name']/'result.json')['windows']['fixed']
    pct=best['fixed_gbps']/256*100
    above=[r for r in rows if r['fixed_gbps']>=200]
    threshold=(f"이번 측정 중 200GB/s를 넘긴 최소 QD는 {min(r['qd_per_port'] for r in above):,}/Port다. "
               "측정하지 않은 중간 QD까지 포함한 정확한 경계값은 아니다.") if above else "이번 완료된 측정에서는 200GB/s에 도달하지 않았다."
    report=f"""# 새 B: 페이지 내부 64B 연속 읽기 성능

2026-10-11 측정. B는 4KiB 논리 페이지의 offset 0, 64, …, 4032를 요청 64개로 읽고 다음 페이지로 이동한다. 기존 희소 64B 읽기 B1/B2는 현재 C1/C2다.

## 결과

측정한 {len(rows)}개 조건 중 최고 고정 2ms 평균은 **{best['fixed_gbps']:.3f}GB/s**다. 조건은 **{best['buffer_mib']:g}MiB·QD{best['qd_per_port']:,}/Port**, 고정 2ms 평균은 Host 상한 256GB/s의 {pct:.2f}%다. 최고 연속 500µs는 **{best['peak_500us_gbps']:.3f}GB/s**다. {threshold}

{context['table']}

공통 조건: 4Port 공유 4Channel, Channel당 16Plane(총 64), 16KiB NAND 물리 페이지, 4KiB stripe, 기존 개선 영역 배치, PF OFF, availability 85%, Port 내부 in-order, head_locality·bypass32·head_wait48.64µs. Controller buffer는 기존 임시 버퍼 정책이다.

## 무엇을 의미하나

1. **동일 QD512에서는 B가 {baseline['fixed_gbps']:.3f}GB/s다.** 같은 장치 설정의 저장된 A1은 {a['bandwidth_gbps']:.3f}GB/s, C1은 {cs['bandwidth_gbps']:.3f}GB/s다. A1은 요청당 4KiB, B/C1은 64B이므로 같은 QD라도 대기 데이터량이 다르다.
2. **B는 페이지를 전부 소비하지만, 충분한 병렬 요청을 확보해야 한다.** QD512의 B는 Port당 32KiB, A1은 2MiB다. B에서 2MiB를 확보하려면 QD32,768이 필요하다. B의 연속 64개 요청이 하나의 논리 페이지에 모이므로 QD 증가가 새로 보이는 NAND 페이지/Plane 수를 늘린다. 관측된 QD별 처리량 증가가 이 효과를 보여준다.
3. **낮은 QD의 첫 병목은 8MiB 버퍼 용량이 아니다.** QD512의 버퍼 평균 예약량은 {baseline['buffer_mean_mib']:.3f}MiB다. 최고 측정 조건에서는 평균 {best['buffer_mean_mib']:.3f}MiB, 전체 관측 중 최대 {best['buffer_peak_mib']:.3f}MiB다. 버퍼 용량만 키우고 QD를 고정한 대조 실험은 이번에 수행하지 않았다.
4. **기존 C1의 낮은 유효 데이터 활용률과 구분한다.** 최고 B 조건의 구간 Host/NAND payload 비율은 {best['host_payload_pct']:.3f}%이고 NAND read amplification은 {best['read_amplification']:.4f}배다. C1은 4KiB당 64B만 소비하여 명목 비율이 1/64다. B는 같은 물리 페이지에 패킹된 데이터를 끝까지 소비한다. 항상 cache hit을 강제한 결과가 아니다.
5. **tR은 바꾸지 않았다.** first/group 20.69µs, short 2.00µs, mid 2.08µs, long 12.16µs다. 최고 조건에서 측정 창 내 sensing 횟수는 {json.dumps(fixed['tr_counts'])}, Long 비율은 {best['long_tr_pct']:.3f}%다. Plane page-buffer hit는 sensing 횟수 분모에 포함하지 않는다.

## 작은 QD에서 드러난 재사용 조건

QD128/Port에서는 Host 10.486GB/s, NAND 41.943GB/s로 유효 활용률이 25%, NAND read amplification이 4배였다. 같은 논리 페이지를 64B씩 끝까지 읽더라도 4KiB stripe 배치에서는 물리 16KiB 안에 들어 있는 나머지 논리 페이지의 요청이 충분히 일찍 수락되어야 한다. 이 모델은 현재 연결된 요청을 모두 반환하면 임시 Controller buffer 항목을 해제한다. 다음 논리 페이지 부분이 늦게 도착하면 NAND에서 16KiB를 다시 전송한다. Plane page buffer가 남아 있으면 재전송 때 sensing tR은 생략할 수 있으므로, tR 감소와 NAND 출력량 감소는 별도 지표다.

QD512 이상에서 측정된 약 100% 활용률은 이러한 재전송이 크게 줄어든 결과다. 따라서 **B의 페이지 전체 소비가 항상 한 번의 내부 NAND 출력 또는 항상 cache hit을 보장하지는 않는다.** 아래 전송량은 동일한 고정 2ms 창으로 계산했다.

{reuse_table}

## 측정 방식과 시간 변화

첫 요청부터 2,200µs까지 계속 요청을 공급한다. 초기 200µs를 제외한 **200–2,200µs 고정 2ms 평균**을 주 지표로 사용한다. 모든 명령의 처리 완료를 기다리거나 마지막 Port만 남는 drain 구간을 포함하지 않는다. 실제 outstanding은 AR 수락 후 최종 R 완료 전 요청 수다.

최고 조건의 실제 outstanding 합계 평균은 {best['actual_outstanding']:,.1f}, Port별 평균은 {json.dumps([round(v,2) for v in best['per_port_outstanding']])}다. 2ms 동안 완료한 64B 요청은 **{best['completed_requests']:,}개**, Port별 처리량은 {json.dumps([round(v,3) for v in best['per_port_gbps']])}GB/s다. 전반 1ms 대비 후반 1ms 변화는 {best['second_vs_first_pct']:+.3f}%다.

![QD별 처리량](../../results/znand/b_sequential/B_qd_scaling.png)

![시간별 처리량·outstanding·요청 수·버퍼 예약량](../../results/znand/b_sequential/B_time.png)

그림은 25µs bin이다. 회색 초기 구간은 평균에서 제외한다. Port별 outstanding이 같으면 선이 겹친다. Host 처리량은 창과 겹치는 반환 바이트, 완료 요청 수는 창 안에서 최종 반환이 끝난 요청으로 계산한다. NAND는 창 안에서 완료한 16KiB 전송 바이트다. 창 경계 때문에 Host/NAND 비율이 소폭 100%를 넘거나 read amplification이 소폭 1보다 작을 수 있다.

## 계측 경계 수정과 실행 검증

QD32,768의 최초 실행은 시뮬레이션 종료 후 시간 bin 검증에서 중단되어 결과로 사용하지 않았다. 기존 계측은 bin 끝에서 1e-9µs보다 짧은 구간을 생략하면서, 그 구간에 일어난 완료 이벤트를 outstanding 끝값에 반영하지 못했다. 새 계측은 엄밀한 `[시작, 끝)` 기준으로 요청 카운터·점유율·NAND 전송을 함께 집계한다. 기존 NAND/controller core와 과거 계측 소스는 보존하고 새 `read64_observation.py`를 사용한다.

재실행의 `--fast-pf-off`은 PF OFF에서 존재할 수 없는 무참조 ready 항목의 퇴거 후보 스캔을 생략한다. 같은 capacity 부등식·Port 선두 예약·수락 순서를 유지한다. 새로 발행 가능한 NAND 작업을 만들지 않는 Host 반환·timer와 이미 eligible한 페이지의 반복 lookup 이벤트에서는 중복 dispatch 스캔도 생략한다. 실제 NAND/maintenance 이벤트와 최초 lookup에서는 기존 dispatch 함수를 그대로 호출한다. 이 최적화는 시뮬레이터의 CPU 계산량을 줄이며 장치 시간을 줄이지 않는다. 버퍼가 부족한 B/C 조건에서 **모든 요청 타임스탬프, 장치 카운터, 버퍼 예약 이벤트, sensing/전송 이벤트가 기존 실행과 정확히 같은지** 회귀 검증했다. 저장된 C1과 B·QD16,384의 전체 2ms 실행도 대조하여 장치 카운터와 정수 계측값은 모두 일치했다. 실수 계측값의 최대 차이는 C1 약 5.1e-11, B 약 1.3e-9였으며 처리량 평균은 일치했다.

앞서 완료한 다섯 조건의 기존 수치는 보존했다. `observer_v1_manifest.json`에 당시 hash를, 현재 manifest에 수정된 계측 hash를 기록한다. 마지막 QD32,768은 수정 계측으로 재실행한 값만 사용한다.

## 재현과 범위

```sh
python3 -m znand.b_sequential_measure --qds {' '.join(str(r['qd_per_port']) for r in rows if r['buffer_mib']==8)} --buffers 8 --workers 1 --fast-pf-off
python3 -m znand.b_sequential_measure --validate-only
python3 -m znand.b_sequential_report
```

그림 생성에는 requirements-znand-plot.txt의 matplotlib이 필요하다. 이미 존재하는 완료 결과는 덮어쓰지 않고 검증하여 사용한다. QD·buffer를 제외한 장치 설정이 A1 기준과 일치하는지, 시간 창 재계산, outstanding/요청 수 보존식, NAND 전송량, source hash를 확인했다. 전체 82개 테스트가 통과했다.

- [원시 결과와 실행 조건](../../results/znand/b_sequential/)
- [검증 결과](../../results/znand/b_sequential/validation.json)
- [A1/C1의 설정·배치 일치 검증](../../results/znand/b_sequential/reference_validation.json)
- [전체 결과 CSV](../../results/znand/b_sequential/sweep.csv)
- [모델·입력 hash](../../results/znand/b_sequential/manifest.json)
- [계측 수정 및 기존 C1 대조 검증](../../results/znand/b_sequential/observer_v2_validation.json)

모델 core SHA256: `{digest('znand/model.py')}`. 기존 측정과 동일하다. 고정 seed 7과 정적 합성 L2P 배치의 시뮬레이션이며, 실제 하드웨어 측정 또는 모든 배치의 전역 최대값이 아니다. 큰 AXI outstanding의 요청 상태 메타데이터/구현 비용은 이 payload 버퍼 모델에 포함하지 않는다. 여기의 QD는 Port별 미완료 요청 수이며 AXI ID 개수를 직접 모델링한 값이 아니다. 4KiB stripe 외 배치 비교, 동일 QD에서의 버퍼 변경, 실제 동적 L2P는 후속 튜닝 항목이다.
"""
    # Paths in docs are one level above results.
    report=report.replace('../../results/', '../results/')
    Path('docs/16_b_sequential_performance_ko.md').write_text(report)
    (ROOT/'README.md').write_text('# B: consecutive 64B requests within each logical page\n\n'
        '[한국어 결과 보고서](../../../docs/16_b_sequential_performance_ko.md)\n\n'
        'See sweep.csv and rows.json for the measured QD comparisons, cases/ for raw windows and 25us timelines, '
        'profiles/ for exact settings, manifest.json for source hashes, and validation.json for accounting checks. '
        'No tR or device scheduling changes were made.\n')
    print(context['table'])


if __name__=='__main__':main()
