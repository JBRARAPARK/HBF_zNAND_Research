"""Report complete prefetch ON/OFF comparisons, retaining Host-only baselines."""
import csv
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .pf_qd_sweep import ROOT, QDS, audit, read, digest


def main():
    out=ROOT;audit(out)
    rows=read(out/'rows.json');cases={s['name']:s for s in read(out/'cases.json')}
    get=lambda p,stage,q,pf:next(r for r in rows if r['pattern']==p and r['stage']==stage and r['outstanding']==q and r['prefetch']==pf)
    n=lambda r,k:float(r.get(k) or 0)
    pct=lambda a,b,key:100*(n(a,key)/n(b,key)-1)
    long=lambda r:100*n(r,'count_tr_long')/n(r,'count_sensing_reads')
    pairs=[]
    for off in (r for r in rows if not r['prefetch']):
        on=get(off['pattern'],off['stage'],off['outstanding'],True)
        pairs.append(dict(pair=off['pair'],pattern=off['pattern'],stage=off['stage'],qd=off['outstanding'],
                          off_gbps=off['bandwidth_gbps'],on_gbps=on['bandwidth_gbps'],
                          on_inclusive_gbps=on['inclusive_prefetch_gbps'],
                          off_vs_on_pct=pct(off,on,'bandwidth_gbps'),
                          off_vs_on_inclusive_pct=100*(off['bandwidth_gbps']/on['inclusive_prefetch_gbps']-1),
                          off_p99_us=off['p99_offer_latency_us'],on_p99_us=on['p99_offer_latency_us'],
                          off_p99_change_pct=pct(off,on,'p99_offer_latency_us')))
    with (out/'paired.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,list(pairs[0]),lineterminator='\n');writer.writeheader();writer.writerows(pairs)
    high=[r for r in pairs if r['stage']=='qd' and r['qd']>=2048]
    wins=sum(r['off_vs_on_pct']>0 for r in high)
    profiles=out/'profiles';profiles.mkdir(exist_ok=True)
    chosen={}
    for p in ('A1','A2'):
        selected=max((r for r in rows if r['pattern']==p and r['stage']=='qd' and not r['prefetch']),
                     key=lambda r:(r['bandwidth_gbps'],-r['p99_offer_latency_us'],-r['outstanding']))
        chosen[p]=selected
        config=cases[selected['name']]['config']
        (profiles/f'{p}_host_only.json').write_text(json.dumps(config,indent=2)+'\n')
    fig,axes=plt.subplots(1,2,figsize=(11,4.5),sharey=True)
    for ax,p in zip(axes,('A1','A2')):
        for pf,color,label in ((False,'#176a6d','PF OFF: Host only'),(True,'#be7041','PF ON: synthetic 100% accuracy')):
            ax.plot(QDS,[get(p,'qd',q,pf)['bandwidth_gbps'] for q in QDS],'-o',color=color,label=label)
        ax.set_xscale('log',base=2);ax.set_xticks(QDS,[str(q) for q in QDS]);ax.tick_params(axis='x',labelrotation=30)
        ax.set_xlabel('Configured outstanding per port');ax.set_title(p);ax.grid(alpha=.25);ax.set_ylim(bottom=0)
    axes[0].set_ylabel('Useful Host GB/s');axes[1].legend(fontsize=8)
    fig.suptitle('Complete PF ON/OFF: 4 ports, 32 Planes, 32 MiB, 8192 requests per port')
    fig.tight_layout();fig.savefig(out/'pf_qd.png',dpi=160);plt.close(fig)

    lines=['# 높은 QD에서 Host 요청만으로 읽기 성능 평가','',
           '성능 평가의 기준선을 PF 자체를 끈 Host-only 실행으로 분리한다. `prefetch=false`는 합성 후보 생성과 선행 Read를 모두 끈다. 이전 92개 실험의 `pf_ahead_limit=0`은 PF가 Demand를 앞서는 추가 예외만 끈 상태였고, 그 실행의 `prefetch`는 계속 true였다.','',
           '이번 비교는 4port·공유 32MiB·seed 7·port 내부 in-order를 유지한다. A1은 4KiB stripe와 CA head_locality, A2는 16KiB stripe와 CA locality를 사용하며 연속 우회 한도는 모두 32회다. 각 ON/OFF 쌍은 `prefetch`만 다르다. PF ON은 합성 정확도 100%·offered 기준 lead 10μs·미사용 후보 예산 128개다.','',
           '**평가 원칙:** 높은 QD의 목표 성능은 Host-only로 먼저 확인하고, PF의 가치는 같은 조건의 추가 효과로 평가한다. 이 변경은 평가 기준과 실행 프로파일에 적용한다. QD를 읽어서 PF를 실시간 ON/OFF하는 기능은 이번에 추가하지 않았다.','',
           f'기본 32Plane·QD2,048 이상 {len(high)}개 ON/OFF 쌍 중 {wins}개에서 PF OFF가 빨랐다. 다만 기본 A1의 QD2,048, 긴 A1 요청열, 64Plane 등에서는 Host 측정 구간 기준으로 PF ON이 빠른 조건도 있다. 따라서 공통 QD 임계값만으로 항상 최고 성능을 고르는 규칙은 이 결과로 확정하지 않는다.','',
           '## QD별 같은 조건 비교','',
           '기본 요청열은 port당 8,192개다. OFF 변화율은 같은 QD의 PF ON 대비이며 양수면 Host-only가 빠르다.','',
           '| 패턴 | QD/port | PF OFF GB/s | PF ON GB/s | OFF 변화 | OFF p99 μs | ON p99 μs |',
           '|---|---:|---:|---:|---:|---:|---:|']
    for r in pairs:
        if r['stage']=='qd':lines.append(f"| {r['pattern']} | {r['qd']} | {r['off_gbps']:.3f} | {r['on_gbps']:.3f} | {r['off_vs_on_pct']:+.2f}% | {r['off_p99_us']:.2f} | {r['on_p99_us']:.2f} |")
    lines+=['','QD8,192는 이 기본 요청열의 port당 전체 요청 수와 같다. 유한 요청열의 시작·종료 영향이 있으며, 설정 QD를 실제 평균 동시 요청 수나 정상 상태 포화의 증거로 사용하지 않는다.','',
            '![PF and QD](pf_qd.png)','',
            '## Host-only 프로파일','',
            '기본 요청열의 PF OFF 조건 중 처리량이 가장 높은 설정을 보관한다. 처리량 동률은 p99, QD가 작은 순서로 고른다. 이전 PF ON 프로파일은 과거 결과 재현을 위해 유지한다.','',
            '| 패턴 | 관측 최고 Host-only QD | Host-only GB/s | 같은 QD의 PF ON GB/s | 설정 |',
            '|---|---:|---:|---:|---|']
    for p,r in chosen.items():
        on=get(p,'qd',r['outstanding'],True)
        lines.append(f"| {p} | {r['outstanding']} | {r['bandwidth_gbps']:.3f} | {on['bandwidth_gbps']:.3f} | [{p} Host-only](profiles/{p}_host_only.json) |")
    lines+=['','이 선택은 고정 버퍼·정책·배치·요청열 범위의 관측값이다. PF OFF의 버퍼·CA 정책까지 다시 최적화한 결과나 장치 전체의 최대 성능은 아니다. Host 반환 경로의 명목 상한 256GB/s에 반드시 도달한다는 의미도 아니다.','',
            '## 긴 요청열과 Plane 확장 확인','',
            '긴 요청열은 port당 16,384개·32Plane, 확장은 port당 8,192개·64Plane이다. 두 확인 모두 QD2,048/port이며 buffer는 32MiB다. ON/OFF는 같은 물리 주소열을 사용한다. Plane 수가 다른 결과끼리는 geometry에 따른 물리 주소 이력도 달라진다.','',
            '| 패턴 | 확인 | PF OFF GB/s | PF ON GB/s | OFF 변화 | OFF p99 μs | ON p99 μs |',
            '|---|---|---:|---:|---:|---:|---:|']
    for r in pairs:
        if r['stage']!='qd':lines.append(f"| {r['pattern']} | {'긴 요청열' if r['stage']=='long' else '64Plane'} | {r['off_gbps']:.3f} | {r['on_gbps']:.3f} | {r['off_vs_on_pct']:+.2f}% | {r['off_p99_us']:.2f} | {r['on_p99_us']:.2f} |")
    lines+=['','## PF 사전 작업 시간을 포함한 처리량','',
            '앞선 표의 GB/s는 첫 Host 요청 제시부터 마지막 반환까지다. PF ON은 그 전에 NAND 작업을 시작할 수 있다. 다음 표는 같은 QD2,048의 결과에서 첫 NAND 작업까지 포함한 처리량도 함께 표시한다. 작은 PF 이득을 평가할 때 두 측정 구간을 구분한다. 이는 계산 구간의 비교이며 PF의 모든 효과를 초기 준비 시간만으로 설명하는 인과 실험은 아니다.','',
            '| 패턴 | 조건 | PF OFF GB/s | PF ON Host 구간 GB/s | PF ON 사전 작업 포함 GB/s | 포함된 사전 작업 μs |',
            '|---|---|---:|---:|---:|---:|']
    for p in ('A1','A2'):
        for stage,label in (('qd','기본'),('long','긴 요청열'),('planes64','64Plane')):
            off=get(p,stage,2048,False);on=get(p,stage,2048,True)
            pre=on['host_bytes']/(on['inclusive_prefetch_gbps']*1000)-on['elapsed_us']
            lines.append(f"| {p} | {label} | {off['bandwidth_gbps']:.3f} | {on['bandwidth_gbps']:.3f} | {on['inclusive_prefetch_gbps']:.3f} | {pre:.2f} |")
    lines+=['','PF OFF는 Host 요청 이전 NAND Read가 없어 두 처리량이 같다. PF ON의 사전 작업 포함 처리량도 정상 상태 상한을 뜻하지 않는다. 실제 workload에서 준비 구간을 어디에 포함할지는 고객 측정 정의에 맞춰야 한다.','',
            '## 실제 수락량과 내부 처리 상태','',
            '평균 Outstanding은 요청별 `(반환 완료−수락)`을 합해 Host 측정 시간과 port 수로 나눈 값이다. 이는 수락 후 미완료 요청 수의 시간 평균이다. QD 설정은 상한이며 실제 평균과 구분한다. Peak는 네 port 중 관측 최대다. Ready 공간에는 순서 대기·현재 반환 중·미사용 PF가 포함된다.','',
            '| 패턴 | QD | PF | 평균 Outstanding/port | Peak | Long % | 평균 예약 대기 MiB | 평균 ready MiB | sensing 수 | PF 기원 sensing/재출력 수 |',
            '|---|---:|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        if r['stage']!='qd':continue
        lines.append(f"| {r['pattern']} | {r['outstanding']} | {'ON' if r['prefetch'] else 'OFF'} | {r['mean_outstanding_per_port']:.1f} | {r['peak_outstanding']} | {long(r):.2f} | {r['diag_buffer_mean_waiting_mib']:.3f} | {r['diag_buffer_mean_ready_mib']:.3f} | {int(n(r,'count_sensing_reads'))} | {int(n(r,'count_prefetch_started'))} |")
    lines+=['','`count_prefetch_started`는 PF로 생성된 작업의 CA 발행 수다. 발행 전에 Demand가 연결될 수 있으므로 실제 발행 시점에 speculative였던 Read 수와 같지 않다. Long 비율이나 이 계수만으로 처리량 차이의 인과 기여도를 분리하지 않는다.','',
            '## 다음 튜닝 기준','',
            '- 먼저 Host-only에서 buffer·수락 window·CA 정책·배치를 조정한다. 높은 QD에서 PF 이득이 필요하다면 부족한 Demand 가시성, 발행 가능 Plane 수, 수락 제한 중 무엇을 보완했는지 분리한다.',
            '- 동적 PF 제어를 검토할 때는 설정 QD 하나보다 실제 수락된 요청, Plane별 발행 가능한 서로 다른 물리 페이지, ready/예약 공간과 선두 대기를 관측한다. 많은 Host 요청이 같은 물리 페이지를 공유할 수 있다.',
            '- PF가 보완할 조건은 같은 자원에서 별도로 측정한다. QD 128도 포화 속도로 제시한 합성 trace이며 간헐적 실제 Host 부하를 대표하지 않는다.',
            '- 단일 seed·고정 A1/A2 패턴의 결과로 공통 QD cutoff를 확정하지 않는다. A2는 1→3→2의 지역 순열이며 균일 무작위 Read가 아니다.',
            '- PF ON은 미래 offered 요청을 아는 모델이다. QD/버퍼 때문에 수락이 늦어지면 실제 수락보다 훨씬 먼저 후보를 생성할 수 있다. 실제 predictor 성능과 구분한다.','',
            '## 재현과 검증','',
            '새로운 실행 18개와 동일 모델·동일 설정에서 재사용한 ON 대조군 10개, 총 28개 조건이다. 14개 ON/OFF 쌍에서 Prefetch Boolean 외 설정이 같은지, PF OFF의 모든 PF 계수가 0인지, 원본 CSV·JSON·입력·소스 해시와 재사용 대조군이 일치하는지 검증한다. Simulator 소스는 이전 커밋에서 변경하지 않았다.','',
            '```sh',
            'python3 -m znand.pf_qd_sweep --workers 6',
            'python3 -m znand.pf_qd_sweep --validate-only',
            'python3 -m znand.pf_qd_report',
            'python3 -m znand.run --config results/znand/pf_qd/profiles/A1_host_only.json --pattern A1 --per-port 8192 --out results/local/A1_host_only',
            '```','',
            '[전체 28개 CSV](sweep.csv), [ON/OFF 쌍 비교](paired.csv), [원본 JSON](rows.json), [실행 조건](cases.json), [실행 해시](manifest.json), [독립 검증](validation.json). `source=reused`와 `source_case`는 이전 scheduling_next 결과의 해당 행을 가리킨다.','',
            '호스트 응답 순서, 임시 버퍼링, Plane당 page buffer 1개, 16KiB NAND Data 전송은 유지한다. 실제 GC·동적 L2P·Die 공유 제약이나 NAND 부분 출력은 이번 비교에 추가하지 않았다.']
    (out/'RESULTS_KO.md').write_text('\n'.join(lines)+'\n')
    (out/'report_manifest.json').write_text(json.dumps(dict(
        source_sha256=digest('znand/pf_qd_report.py'),sweep_sha256=digest(out/'sweep.csv'),
        selected_host_only={p:r['name'] for p,r in chosen.items()},
        high_qd_off_faster=wins,
        high_qd_pairs=6),indent=2)+'\n')
    print(json.dumps({p:dict(qd=r['outstanding'],gbps=r['bandwidth_gbps']) for p,r in chosen.items()}))


if __name__=='__main__':main()
