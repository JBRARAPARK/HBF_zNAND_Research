"""Generate the staged scheduling comparison from frozen selections and rows."""
import csv
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from .validate_results import validate


def main():
    out=Path('results/znand/scheduling_next')
    rows=json.loads((out/'rows.json').read_text())
    manifest=json.loads((out/'manifest.json').read_text())
    assert manifest['complete_through']=='checks' and len(rows)==manifest['validated_rows']==86
    interaction=json.loads((out/'interaction/rows.json').read_text())
    assert len(interaction)==4
    data_long=json.loads((out/'data_long/rows.json').read_text())
    assert len(data_long)==4 and sum(r['source']=='new' for r in data_long)==2
    aggregate=[]
    for dataset,items in [('primary',rows),('interaction',interaction),('data_long',[r for r in data_long if r['source']=='new'])]:
        for r in items:aggregate.append(dict(r,source_dataset=dataset,source_case_id=r['case_id'],case_id=len(aggregate)))
    fields=sorted({k for r in aggregate for k in r})
    with (out/'all_results.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fields,lineterminator='\n');writer.writeheader()
        writer.writerows({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in aggregate)
    assert validate(out/'all_results.csv')==92
    byname={r['name']:r for r in rows}
    selections={s:json.loads((out/f'selection_{s}.json').read_text()) for s in ('A','B','C')}
    stages={}
    for p in ('A1','A2'):
        stages[p]=[byname[f'A_{p}_b32_q2048']]+[byname[selections[s]['audit'][p]['selected']] for s in ('A','B','C')]
    n=lambda r,k:float(r.get(k) or 0)
    gain=lambda cur,base:100*(n(cur,'bandwidth_gbps')/n(base,'bandwidth_gbps')-1)
    long=lambda r:100*n(r,'count_tr_long')/n(r,'count_sensing_reads')
    def settings(r):
        return f"{int(r['buffer_pages']/64)}MiB / QD{r['outstanding']} / PF{r['pf_ahead_limit']} / CA {r['ca_policy']} / Data {r['data_policy']}"
    pairs=[]
    for name in dict.fromkeys(r['pair'] for r in sorted(rows,key=lambda r:r['case_id']) if r['stage']=='checks'):
        base=next(r for r in rows if r['pair']==name and r['variant']=='baseline')
        cur=next(r for r in rows if r['pair']==name and r['variant']=='candidate')
        bw_ratio=n(cur,'bandwidth_gbps')/n(base,'bandwidth_gbps')
        p99_ratio=n(cur,'p99_offer_latency_us')/n(base,'p99_offer_latency_us')
        pairs.append(dict(pair=name,pattern=cur['pattern'],baseline_gbps=base['bandwidth_gbps'],
                          candidate_gbps=cur['bandwidth_gbps'],gain_pct=100*(bw_ratio-1),
                          baseline_p99_us=base['p99_offer_latency_us'],candidate_p99_us=cur['p99_offer_latency_us'],
                          p99_change_pct=100*(p99_ratio-1),within_check_band=bw_ratio>=.98 and p99_ratio<=1.05,
                          ports=cur['ports'],planes_per_channel=cur['planes'],per_port=cur['per_port'],
                          seed=cur['seed'],remap_fraction=cur['remap_fraction']))
    with (out/'paired_checks.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,list(pairs[0]),lineterminator='\n');writer.writeheader();writer.writerows(pairs)
    fig,axes=plt.subplots(1,2,figsize=(11,4.4))
    for ax,p in zip(axes,('A1','A2')):
        matrix=[[next(r['bandwidth_gbps'] for r in rows if r['name']==f'A_{p}_b{m}_q{q}') for q in (1024,2048,4096)] for m in (32,40,48)]
        ax.imshow(matrix,cmap='Blues',vmin=80,vmax=max(max(x) for x in matrix)*1.08)
        for i,line in enumerate(matrix):
            for j,value in enumerate(line):ax.text(j,i,f'{value:.2f}',ha='center',va='center',color='black' if value<125 else 'white')
        selected=stages[p][1]
        i=(32,40,48).index(selected['buffer_pages']//64);j=(1024,2048,4096).index(selected['outstanding'])
        ax.add_patch(Rectangle((j-.48,i-.48),.96,.96,fill=False,edgecolor='#f28c28',linewidth=3))
        ax.set_xticks(range(3),('1024','2048','4096'));ax.set_yticks(range(3),('32','40','48'))
        ax.set_xlabel('Outstanding per port');ax.set_ylabel('Shared buffer (MiB)');ax.set_title(p+' useful Host GB/s')
    fig.suptitle('Stage A: current CA policies; orange = selected within p99 guard')
    fig.tight_layout();fig.savefig(out/'resource_sweep.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4.5))
    for ax,p in zip(axes,('A1','A2')):
        values=[r['bandwidth_gbps'] for r in stages[p]]
        bars=ax.bar(('Original','Buffer / QD','PF choice','CA / Data'),values,color=('#9aa3b1','#638cbc','#419b91','#286166'))
        ax.bar_label(bars,fmt='%.3f',padding=3);ax.set_ylim(0,max(values)*1.16)
        ax.set_title(p);ax.set_ylabel('Useful Host GB/s');ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    fig.suptitle('Sequential selection: 4 ports / 32 Planes / 8192 requests per port\nBars show 100% synthetic PF accuracy; PF choice used three accuracy levels',fontsize=12)
    fig.tight_layout();fig.savefig(out/'scheduling_stages.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,9),sharey=True)
    for ax,key,title in zip(axes,('gain_pct','p99_change_pct'),('Throughput change (%)','Offer-to-return p99 change (%)')):
        values=[r[key] for r in pairs];colors=['#398e7d' if (v>=0 if key=='gain_pct' else v<=0) else '#c36655' for v in values]
        bars=ax.barh(range(len(pairs)),values,color=colors)
        ax.bar_label(bars,fmt='%+.1f',padding=3,fontsize=8);ax.axvline(0,color='#555',linewidth=.8)
        lo=min(0,min(values));hi=max(0,max(values));span=max(10,hi-lo)
        ax.set_xlim(lo-span*.18,hi+span*.2);ax.set_title(title);ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
    axes[0].set_yticks(range(len(pairs)),[p['pair'] for p in pairs]);axes[0].invert_yaxis()
    fig.suptitle('Frozen candidate vs original profile under identical check conditions')
    fig.tight_layout();fig.savefig(out/'paired_checks.png',dpi=160);plt.close(fig)

    lines=['# 버퍼와 QD 재평가 및 PF와 Data 스케줄링 실험','',
           '현재 연속 주소 우선 정책에서 자원 설정을 다시 고른 뒤, 제한적인 연속 PF 우선과 NAND Data 선두 우선을 순서대로 비교했다. 18개 자원 비교, 18개 PF 비교, 8개 CA/Data 조합, 42개 추가 확인을 합쳐 기본 86개 조건이다. A1의 PF 우선 OFF 교차 확인 4개와 긴 요청열의 Data ON 2개를 추가해 총 92개를 새로 실행했다. 긴 요청열 Data OFF 대조군 2개는 기본 86개에서 재사용했다. 기본 실험은 4port·32Plane·port당 8,192개 요청·seed 7·비중첩 주소이며 A1은 4KiB stripe, A2는 16KiB stripe다.','',
           '**적용 결정: 기존 실행용 프로파일을 유지한다.** 제한적 연속 PF 우선과 NAND Data 선두 우선은 실험 옵션으로 보관하고 기본 OFF를 유지한다. 기본 조건의 작은 이득이 seed·주소 재배치 조건에서 유지되지 않았고, 버퍼·QD 증대도 기존 최고값을 넘지 못했다.','',
           '## 기본 조건의 결과','',
           '| 패턴 | 이전 설정 GB/s | 선택 후보 GB/s | 변화 | 이전 p99 μs | 후보 p99 μs | 후보 설정 |',
           '|---|---:|---:|---:|---:|---:|---|']
    for p,ss in stages.items():
        base,cur=ss[0],ss[-1]
        lines.append(f"| {p} | {base['bandwidth_gbps']:.3f} | {cur['bandwidth_gbps']:.3f} | {gain(cur,base):+.2f}% | {base['p99_offer_latency_us']:.2f} | {cur['p99_offer_latency_us']:.2f} | {settings(cur)} |")
    failed=[r['pair'] for r in pairs if not r['within_check_band']]
    lines+=['',f"추가 확인 {len(pairs)}개 쌍 중 처리량 −2% 또는 p99 +5% 기준을 벗어난 경우는 {len(failed)}개다."+
            (' 해당 조건: '+', '.join(failed)+'.' if failed else ''),
            '후보는 기본 workload에서 선택한 오프라인 설정이다. 추가 확인 결과에 맞춰 후보를 재튜닝하지 않았으며, 혼합 부하를 자동 분류하거나 정책을 전환하는 기능은 없다. 전역 최적값이나 제품 실측 성능으로 해석하지 않는다.','',
            '![Stages](scheduling_stages.png)','',
            '## 단계별 선택 기준','',
            '- A: 이전 32MiB·QD2,048 설정 대비 offer p99가 5% 이내인 조건 중 처리량 최대. 동률은 p99·버퍼·QD가 작은 순서다.',
            '- B: 정확도 100/75/50% 각각의 PF 제한 우선 OFF와 비교한다. 모든 처리량 비율이 0.98 이상이고 p99 비율이 1.05 이하인 예산 중 처리량 비율 기하평균을 최대화한다. OFF도 후보에 포함한다.',
            '- C: B에서 선택한 설정을 고정하고 CA 선두 OFF/ON × Data 선두 OFF/ON을 비교한다. 해당 B 기준선 대비 p99가 5% 이내인 조건 중 처리량 최대를 선택한다.',
            '- 확인: 후보를 먼저 고정한 뒤 요청 길이·maintenance seed·L2P 재배치·port 수·B계열·64Plane에서 이전 프로파일과 같은 조건으로 비교한다.','',
            '5%/2%는 이번 선택·검토 기준이며 제품 SLA가 아니다. 각 단계는 이전 단계의 선택 위에서 수행한 순차 탐색으로, 버퍼·PF·CA·Data의 모든 조합을 전수 탐색하지 않았다.','',
            '## A 버퍼와 Outstanding','',
            '| 패턴 | MiB | QD/port | GB/s | p99 μs | Long % | 평균 예약 대기 MiB | 평균 진행 중 MiB | 평균 ready MiB |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in sorted((r for r in rows if r['stage']=='A'),key=lambda r:r['case_id']):
        inflight=sum(n(r,'diag_buffer_mean_'+s+'_mib') for s in ('ca','sensing','sensed','transfer','ecc'))
        lines.append(f"| {r['pattern']} | {r['buffer_pages']//64} | {r['outstanding']} | {r['bandwidth_gbps']:.3f} | {r['p99_offer_latency_us']:.2f} | {long(r):.2f} | {n(r,'diag_buffer_mean_waiting_mib'):.3f} | {inflight:.3f} | {n(r,'diag_buffer_mean_ready_mib'):.3f} |")
    lines+=['','평균 공간은 첫 Host 요청 제시부터 마지막 반환까지 페이지 상태의 정확한 시간 적분이다. 예약 대기는 아직 CA를 발행하지 않은 waiting 작업, 진행 중은 CA/sensing/Data 대기·전송/ECC다. Ready는 순서 대기뿐 아니라 현재 반환 중인 데이터와 미사용 PF도 포함한다.','',
            '![Resources](resource_sweep.png)','',
            '## B 제한적인 연속 PF 우선','',
            '같은 Plane에 발행 가능한 Demand가 있고, 그 Demand 등급에 page buffer hit 또는 같은 Group의 q+1 후보가 없을 때만 이미 발행 가능한 q+1 PF를 최대 1/2회 먼저 허용한다. Plane별 예산이며 실제 CA 발행 때만 센다. Demand 발행 등 다른 선택이 발생하면 초기화한다. 기존 age·연속 우회 보호와 48.64μs 이상 기다린 같은 Plane의 선두 Demand를 먼저 보호한다. 실제 예측 정답 여부는 스케줄러 입력이 아니다.','',
            '| 패턴 | 합성 정확도 | PF 우선 한도 | GB/s | p99 μs | Long % | PF 우선 발행 횟수 |',
            '|---|---:|---:|---:|---:|---:|---:|']
    for r in sorted((r for r in rows if r['stage']=='B'),key=lambda r:r['case_id']):
        lines.append(f"| {r['pattern']} | {r['accuracy']*100:g}% | {r['pf_ahead_limit']} | {r['bandwidth_gbps']:.3f} | {r['p99_offer_latency_us']:.2f} | {long(r):.2f} | {int(n(r,'count_ca_selection_pf_ahead'))} |")
    lines+=['','## C CA와 NAND Data 선두 우선','',
            'CA 선두 ON의 임계시간은 48.64μs다. Data 선두 ON은 lookup을 마친 현재 port 선두의 페이지가 sensed 상태이면 같은 channel의 준비된 데이터 중 우선한다. 전송 준비 후 1,000μs 이상 기다린 Demand를 먼저 보호한다. 이미 진행 중인 Data 전송은 선점하지 않고, Host의 port 내부 in-order는 유지한다.','',
            '| 패턴 | CA 선두 | Data 선두 | GB/s | p99 μs | Long % | CA 선두 선택 | Data 선두 선택 |',
            '|---|---|---|---:|---:|---:|---:|---:|']
    for r in sorted((r for r in rows if r['stage']=='C'),key=lambda r:r['case_id']):
        lines.append(f"| {r['pattern']} | {'ON' if r['ca_policy']=='head_locality' else 'OFF'} | {'ON' if r['data_policy']=='head' else 'OFF'} | {r['bandwidth_gbps']:.3f} | {r['p99_offer_latency_us']:.2f} | {long(r):.2f} | {int(n(r,'count_ca_selection_head'))} | {int(n(r,'count_data_selection_head'))} |")
    lines+=['','선두 선택 횟수는 해당 규칙으로 선택한 횟수다. 기존 순서에서도 같은 페이지가 선택됐을 수 있으므로 실제 순서 변경 횟수와 같지 않다.','',
            '### A1의 PF 우선 OFF 교차 확인','',
            'A1의 B 단계 선택이 정확도 100%에서는 기존 설정보다 느려, PF 우선 OFF에서도 CA/Data 네 조합을 추가 확인했다. 이 추가 결과로 앞서 고정한 C 후보나 42개 확인 조건을 변경하지 않았다.','',
            '| CA 선두 | Data 선두 | GB/s | p99 μs | Long % |',
            '|---|---|---:|---:|---:|']
    for r in interaction:
        lines.append(f"| {'ON' if r['ca_policy']=='head_locality' else 'OFF'} | {'ON' if r['data_policy']=='head' else 'OFF'} | {r['bandwidth_gbps']:.3f} | {r['p99_offer_latency_us']:.2f} | {long(r):.2f} |")
    lines+=['','[교차 확인 원본](interaction/sweep.csv), [조건](interaction/cases.json), [검증·해시](interaction/manifest.json). Data 우선 OFF인 두 대조군은 이전 모델의 같은 우회 한도 결과와 일치한다.','',
            '### A1 긴 요청열에서 Data 우선 재확인','',
            '짧은 A1·PF 우회1·CA 선두 ON 비교에서 Data 선두를 켜면 중간 완료 구간의 처리량은 증가했지만 전체 완료시간은 늘었다. 이 차이를 확인하기 위해 port당 16,384개 요청에서 PF 우선 OFF/1회 각각의 Data ON을 추가 실행했다. 중간 완료 구간은 전체 완료 요청 중 가운데 절반으로 계산하며 정상 상태 처리량을 보장하는 지표는 아니다.','',
            '| PF 우선 한도 | Data 선두 | 전체 GB/s | 중간 완료 구간 GB/s | p99 μs | 실행 출처 |',
            '|---:|---|---:|---:|---:|---|']
    for r in data_long:
        lines.append(f"| {r['pf_ahead_limit']} | {'ON' if r['data_policy']=='head' else 'OFF'} | {r['bandwidth_gbps']:.3f} | {r['middle_bandwidth_gbps']:.3f} | {r['p99_offer_latency_us']:.2f} | {'기본 실험 재사용' if r['source']=='reused_primary' else '추가 실행'} |")
    lines+=['','긴 요청열에서도 Data 선두 우선은 PF 우선 OFF/1회 모두 전체 처리량을 낮추고 p99를 늘렸다. 중간 완료 구간은 소폭 개선됐지만 이 측정만으로 기본 정책을 교체하지 않는다.','',
            '[긴 요청열 Data 비교](data_long/sweep.csv), [조건](data_long/cases.json), [검증·해시](data_long/manifest.json). 후보와 기본 42개 확인 조건은 이 추가 비교에서도 변경하지 않았다.','',
            '## Long 발생 시점의 후보 상태','',
            '| 패턴 | 단계 | Long CA 선택 | 다음 페이지 미수락 | 다음 PF가 등급에서 밀림 | Lookup 미완료 | 선두 규칙이 연속 후보 우회 |',
            '|---|---|---:|---:|---:|---:|---:|']
    for p,ss in stages.items():
        for label,r in zip(('이전','자원 선택','PF 선택','최종 후보'),ss):
            lines.append(f"| {p} | {label} | {int(n(r,'diag_long_ca_choices'))} | {int(n(r,'diag_long_next_not_accepted'))} | {int(n(r,'diag_long_next_pf_lower_priority'))} | {int(n(r,'diag_long_next_lookup_pending'))} | {int(n(r,'diag_long_next_eligible_overridden_head'))} |")
    lines+=['','위 표는 일부 상태만 표시한다. 나머지는 이미 준비·소비된 다음 페이지나 요청 범위 밖 등의 경우다. 후보 선택 후에 전체 trace를 조회하는 오프라인 진단이며 스케줄러가 미래 정보를 사용하는 기능이 아니다. 상태별 건수는 즉시 관측 분류이고 독립적인 인과 기여율은 아니다. Host 측정 종료 때 CA가 진행 중이면 Long CA 선택 수가 완료된 tR 분류보다 최대 channel 수만큼 많을 수 있다.','',
            '### 다음 연속 페이지가 미수락 상태일 때','',
            '다음 표는 원래 프로파일에서 같은 시점에 관측된 제약을 분류한다. QD와 buffer가 동시에 가득 찬 경우는 별도 열로 둔다. 아직 Host가 제시하지 않은 요청도 있으므로, 미수락 상태를 전부 admission 변경으로 해결할 수 있다고 해석하지 않는다.','',
            '| 패턴 | 미수락 / Long 선택 | Buffer full | QD full | QD + Buffer full | 아직 미제시 | 미제시 + QD full | 기타 |',
            '|---|---:|---:|---:|---:|---:|---:|---:|']
    for p,ss in stages.items():
        r=ss[0];counts=[int(n(r,'diag_next_barrier_'+k)) for k in ('buffer_full','qd_full','qd_full_and_buffer_full','not_offered','not_offered_and_qd_full','earlier_requests_or_guard')]
        lines.append(f"| {p} | {int(n(r,'diag_long_next_not_accepted'))}/{int(n(r,'diag_long_ca_choices'))} | "+' | '.join(map(str,counts))+' |')
    lines+=['',
            '## 고정한 후보의 추가 확인','',
            '| 조건 | 이전 GB/s | 후보 GB/s | 변화 | 이전 p99 μs | 후보 p99 μs | p99 변화 | 검토 범위 내 |',
            '|---|---:|---:|---:|---:|---:|---:|---|']
    for r in pairs:
        lines.append(f"| {r['pair']} | {r['baseline_gbps']:.3f} | {r['candidate_gbps']:.3f} | {r['gain_pct']:+.2f}% | {r['baseline_p99_us']:.2f} | {r['candidate_p99_us']:.2f} | {r['p99_change_pct']:+.2f}% | {'예' if r['within_check_band'] else '아니오'} |")
    lines+=['','![Checks](paired_checks.png)','',
            '- `long`: port당 16,384개 요청. 생성 규칙상 port별 주소 범위도 함께 늘어난다.',
            '- `seed17/29`: maintenance 위상을 바꾼다. 고정 A1/A2 요청 순서를 무작위 Read로 바꾸는 실험은 아니다.',
            '- `remap0.25/0.75`: 기존 합성 L2P 재배치 비율이다. 실제 SSD의 GC·wear leveling을 실행한 결과는 아니다.',
            '- `ports1/2/3`: 활성 port만 변경하고 port당 요청 수를 유지한다. 각 쌍은 동일한 요청열이며 서로 다른 port 수끼리는 총 요청량이 다르다.',
            '- `planes64`: channel당 16Plane. 동일한 논리 요청열을 확장 geometry에 다시 매핑하며, 32Plane과 동일한 물리 주소 이력을 고정한 실험은 아니다.',
            '- `B*_transfer`: B1/B2는 A1, B3는 A2에서 선택한 버퍼/QD·PF·Data 설정을 옮겨 본다. B계열의 CA는 기존 locality를 유지한다. B계열 자체를 최적화한 결과는 아니다.','',
            '## 결과 해석과 다음 실험','',
            '1. **32Plane에서는 32MiB·QD2,048/port를 유지한다.** 예약 대기 약 14MiB와 ready 약 13MiB가 평균 점유의 대부분이다. Ready에는 반환 중·미사용 PF도 포함되므로 전체를 순서 대기 손실로 계산하지 않는다. 버퍼가 크다는 사실보다 어느 요청에 공간을 묶어 두는지가 다음 가설이다.',
            '2. **Long 횟수만 최적화하지 않는다.** 연속 PF를 먼저 읽거나 Data 선두를 우선하면 일부 Long을 줄여도 Demand 준비·Plane 해제·버퍼 수락·마지막 port 완료 순서가 달라져 총 처리량이 낮아질 수 있다. 전체 GB/s와 p99를 우선하고 중간 완료 구간 처리량은 보조 지표로 사용한다.',
            '3. **우선 검토할 구현은 요청 정보와 payload 예약의 분리다.** 요청 메타데이터를 더 보더라도 모든 요청에 즉시 16KiB를 예약하지 않는 방식을 비교한다. Port 선두 진행에 필요한 공간을 보장하고, 수락→발행 window와 물리 buffer를 별도로 제한해야 한다. 공유 페이지와 in-order 조건에서 교착 없는 진행성을 먼저 검증한다. 이번 실험에는 이 변경을 구현하지 않았다.',
            '4. **64Plane은 자원 확장 효과를 별도로 평가한다.** 32Plane의 정책 변경과 구분하고, 64Plane에서 buffer×QD를 다시 탐색해야 한다. 이 모델은 Plane을 독립 자원으로 다루므로 실제 Die 공유 제약을 반영하면 결과가 달라질 수 있다.','',
            '| 기존 정책의 Plane 확장 | 32Plane GB/s | 64Plane GB/s | 변화 | 32Plane Long % | 64Plane Long % |',
            '|---|---:|---:|---:|---:|---:|']
    for p,ss in stages.items():
        base=ss[0];cur=byname[f'check_{p}_planes64_baseline']
        lines.append(f"| {p} | {base['bandwidth_gbps']:.3f} | {cur['bandwidth_gbps']:.3f} | {gain(cur,base):+.2f}% | {long(base):.2f} | {long(cur):.2f} |")
    lines+=['','이 표는 동일 논리 요청열을 다른 geometry에 매핑한 결과다. Buffer·QD·정책은 같지만 물리 주소 이력은 같지 않으며, 64Plane의 최적 설정이나 제품 성능 상한을 확정하지 않는다.','',
            '## 설정과 재현','',
            '[A1 후보](profiles/candidate_A1.json), [A2 후보](profiles/candidate_A2.json), [A1 이전 설정](profiles/baseline_A1.json), [A2 이전 설정](profiles/baseline_A2.json)을 구분해 제공한다. 모델 기본값은 `pf_ahead_limit=0`, `data_policy=ready`이며 새 기능은 명시한 설정에서만 켜진다.','',
            '```sh',
            'python3 -m unittest test_znand test_znand_expansion test_znand_locality test_znand_head test_znand_scheduling -q',
            'python3 -m znand.scheduling_sweep --workers 6',
            'python3 -m znand.scheduling_interaction',
            'python3 -m znand.scheduling_data_long',
            'python3 -m znand.scheduling_report',
            'python3 -m znand.validate_scheduling',
            'python3 -m znand.run --config results/znand/scheduling_next/profiles/candidate_A1.json --pattern A1 --per-port 8192 --out results/local/scheduling_candidate_A1',
            '```','',
            '동일한 모델·계측·실행기 해시와 조건에서만 checkpoint를 이어서 사용한다. 과거 head_locality 결과는 보존하며 변경된 모델로 재실행할 때는 별도 출력 폴더를 지정한다.','',
            '원본: [92개 통합 CSV](all_results.csv), [기본 86개 CSV](sweep.csv), [조건](cases.json), [전체 계측 JSON](rows.json), [추가 확인 쌍](paired_checks.csv), [A 선택](selection_A.json), [B 선택](selection_B.json), [C 선택](selection_C.json), [manifest](manifest.json), [63개 테스트 기록](code_validation.json), [통합 검증](validation.json). 통합 CSV의 `source_dataset`과 `source_case_id`로 각 원본 행을 찾을 수 있다.','',
            '`manifest.source_commit`은 실행 작업트리의 기준 커밋이며, 실제 실행한 모델·계측·실행기는 `hashes`로 고정한다. 이전 모델 기본 동작 비교와 버퍼 상태 시간 적분의 단일 Read 분석값 검증을 포함해 63개 테스트가 통과했다.','',
            '모델의 실제 predictor·동적 L2P·실제 GC·Die 공유 제약·상세 UCIe 프로토콜은 이번 변경에 포함하지 않았다. PF 정확도는 합성 입력이며 정확도와 실제 선행 완료 coverage는 다르다. 64B 저장 분산과 소비 후 controller cache는 기존 합의대로 도입하지 않았다.']
    (out/'RESULTS_KO.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(rows=len(aggregate),pairs=len(pairs),outside_check_band=failed),ensure_ascii=False))


if __name__=='__main__':main()
