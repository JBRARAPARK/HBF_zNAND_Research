"""Summarize matched locality scheduling experiments."""
from pathlib import Path
import csv,json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    out=Path('results/znand/locality')
    manifest=json.loads((out/'manifest.json').read_text())
    rows=list(csv.DictReader((out/'sweep.csv').open()))
    assert len(rows)==manifest['cases']
    base=list(csv.DictReader(Path('results/znand/buffer_expansion/sweep.csv').open()))
    def n(r,k):return float(r.get(k) or 0)
    def longpct(r):return 100*n(r,'count_tr_long')/n(r,'count_sensing_reads')
    def avgtr(r):return sum(n(r,'count_tr_'+k)*n(r,k+'_us') for k in ('first','short','mid','long','group'))/n(r,'count_sensing_reads')
    pairs=[]
    for r in rows:
        if r['ca_policy']!='locality':continue
        b=next(x for x in base if all(x[k]==r[k] for k in ('pattern','buffer_mib','stripe','prefetch','outstanding')))
        pairs.append(dict(case_id=r['case_id'],phase=r['phase'],pattern=r['pattern'],buffer_mib=r['buffer_mib'],stripe=r['stripe'],prefetch=r['prefetch'],outstanding=r['outstanding'],
            fifo_gbps=n(b,'bandwidth_gbps'),locality_gbps=n(r,'bandwidth_gbps'),gain_pct=(n(r,'bandwidth_gbps')/n(b,'bandwidth_gbps')-1)*100,
            fifo_long_pct=longpct(b),locality_long_pct=longpct(r),fifo_average_tr_us=avgtr(b),locality_average_tr_us=avgtr(r),
            fifo_p99_accepted_us=n(b,'p99_latency_us'),locality_p99_accepted_us=n(r,'p99_latency_us'),
            fifo_mean_offer_us=n(b,'mean_offer_latency_us'),locality_mean_offer_us=n(r,'mean_offer_latency_us'),
            locality_selections=int(n(r,'count_ca_selection_locality')),age_selections=int(n(r,'count_ca_selection_age')),limit_selections=int(n(r,'count_ca_selection_bypass_limit'))))
    with (out/'matched_comparison.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,list(pairs[0]),lineterminator='\n');w.writeheader();w.writerows(pairs)
    fixed=[r for r in pairs if r['stripe']=='16384' and r['prefetch']=='True' and r['outstanding']=='2048']
    a2=sorted([r for r in fixed if r['pattern']=='A2'],key=lambda r:int(r['buffer_mib']))
    fig,axs=plt.subplots(1,2,figsize=(11,4))
    for policy in ('fifo','locality'):
        axs[0].plot([int(r['buffer_mib']) for r in a2],[r[policy+'_gbps'] for r in a2],marker='o',label=policy)
        axs[1].plot([int(r['buffer_mib']) for r in a2],[r[policy+'_long_pct'] for r in a2],marker='o',label=policy)
    for ax in axs:ax.set_xlabel('Shared buffer (MiB)');ax.set_xticks((8,16,24,32));ax.grid(alpha=.3);ax.legend()
    axs[0].set_ylabel('Useful host GB/s');axs[1].set_ylabel('Long sensing (%)')
    fig.suptitle('A2, 4 ports, 32 planes, QD 2048/port, 16KiB stripe, PF ON');fig.tight_layout();fig.savefig(out/'locality_a2.png',dpi=160);plt.close(fig)
    lines=['# 연속 물리 주소 우선 NAND 명령 발행 평가','',
        f"기존 FIFO 순서와 locality 정책을 같은 요청열로 비교했다. 신규 {len(rows)}개 실행 중 FIFO 재현 대조군은 4개, locality는 {len(pairs)}개다. 모든 조건은 4port·32Plane·port당 8,192개 요청·seed 7·주소 중첩 0%다. 저장된 FIFO 결과와의 비교에서 주소·버퍼·Outstanding·Prefetch·모든 지연 및 대역폭 설정을 유지했다.",'',
        '## 구현 정책','',
        '- Controller의 CA 명령 선택만 변경했다. Host 요청 주소·시각, 조회, 버퍼 수명, NAND Data 중재, port 내부 strict in-order 반환은 유지했다.',
        '- 이미 발행 가능한 같은 Plane의 Demand 요청 중 page buffer 재사용, 이어지는 q+1 주소를 우선한다. Group 경계를 넘는 q+1은 우선하지 않는다. Demand가 있으면 Prefetch는 그 뒤다.',
        '- 오래된 요청을 연속 8회까지 우회할 수 있다. 한도에 도달하거나 가장 오래된 해당 우선순위 요청의 eligible 이후 대기가 1,000μs 이상이면 오래된 요청을 선택한다. 후보가 없는 경우 미래 요청을 기다리지 않는다.',
        '- Channel 내 Plane 간 경쟁은 각 Plane에서 대표하는 가장 오래된 작업 순서를 유지한다. 이 제한은 CA 선택 시의 규칙이며 busy/maintenance가 포함된 절대 완료시간 보장이 아니다.',
        '- 기본 `ca_policy`는 fifo이며, locality를 명시한 설정에서만 새 정책을 적용한다. 기존 모델 결과를 덮어쓰지 않았다.','',
        '## A2 동일 설정 비교','',
        '16KiB 분산·Prefetch ON·QD2,048/port를 고정했다. 유효 Host 처리량 단위는 GB/s다.','',
        '| Buffer MiB | FIFO | Locality | 변화 | FIFO Long 비율 | Locality Long 비율 |','|---|---:|---:|---:|---:|---:|']
    for r in a2:lines.append(f"| {r['buffer_mib']} | {r['fifo_gbps']:.3f} | {r['locality_gbps']:.3f} | {r['gain_pct']:+.1f}% | {r['fifo_long_pct']:.2f}% | {r['locality_long_pct']:.2f}% |")
    lines+=['','![A2 locality comparison](locality_a2.png)','','## 패턴별 동일 설정 비교','','모두 16KiB 분산·PF ON·QD2,048/port다. 각 셀은 FIFO → Locality GB/s이며 다른 QD의 최고값과 혼합하지 않았다.','','| 패턴 | 8MiB | 16MiB | 24MiB | 32MiB |','|---|---:|---:|---:|---:|']
    for pat in ('A1','A2','B1','B2','B3'):
        vals=[next(r for r in fixed if r['pattern']==pat and r['buffer_mib']==str(m)) for m in (8,16,24,32)]
        lines.append('| '+pat+' | '+' | '.join(f"{r['fifo_gbps']:.3f} → {r['locality_gbps']:.3f}" for r in vals)+' |')
    lines+=['','## 지연과 port 완료 시점','','A2·16KiB 분산·PF ON·QD2,048/port. 수락 전 대기를 포함한 지표다. Port 완료 시점은 첫 요청 제시부터 해당 port의 마지막 반환까지이며 유한 trace의 완료 편차다.','','| MiB | 평균 offer 지연 FIFO→Locality μs | p99 offer FIFO→Locality μs | Port 완료 min–max FIFO μs | Port 완료 min–max Locality μs |','|---|---:|---:|---:|---:|']
    for mib in (8,16,24,32):
        match=lambda r:r['pattern']=='A2' and r['buffer_mib']==str(mib) and r['stripe']=='16384' and r['prefetch']=='True' and r['outstanding']=='2048'
        b=next(r for r in rows if match(r) and r['ca_policy']=='fifo');r=next(r for r in rows if match(r) and r['ca_policy']=='locality')
        bp=json.loads(b['port_completion_us']);rp=json.loads(r['port_completion_us'])
        lines.append(f"| {mib} | {n(b,'mean_offer_latency_us'):.2f} → {n(r,'mean_offer_latency_us'):.2f} | {n(b,'p99_offer_latency_us'):.2f} → {n(r,'p99_offer_latency_us'):.2f} | {min(bp):.2f}–{max(bp):.2f} | {min(rp):.2f}–{max(rp):.2f} |")
    best=max(pairs,key=lambda r:r['locality_gbps'])
    positive=sum(r['gain_pct']>1e-8 for r in pairs);negative=sum(r['gain_pct']< -1e-8 for r in pairs)
    lines+=['','## 비교 범위 내 최고값과 한계','',
        f"최고 locality 처리량은 {best['locality_gbps']:.3f}GB/s다. 조건은 {best['pattern']}, buffer {best['buffer_mib']}MiB, stripe {int(best['stripe'])//1024}KiB, PF {best['prefetch']}, QD{best['outstanding']}/port이며 동일 FIFO 조건 {best['fifo_gbps']:.3f}GB/s 대비 {best['gain_pct']:+.1f}%다.",
        f"비교한 {len(pairs)}개 조건 중 증가 {positive}개, 감소 {negative}개다. 나머지는 부동소수점 오차 허용 범위에서 동일하다.",
        '실험은 PF ON·QD2,048의 패턴/배치/버퍼 40개와, 기존 FIFO에서 용량·패턴별 최고값을 냈던 추가 설정을 평가했다. 새 정책의 모든 QD·PF 조합을 탐색한 전역 최적화가 아니다. 우회 8회와 대기 1,000μs도 초기 튜닝 값이며 실제 fairness/SLA 보장은 별도 검증이 필요하다.',
        '평균 sensing과 Long 비율은 원본의 count_tr_*와 함께 제공한다. Throughput 증가를 실제 제품 성능으로 해석하지 않는다. UCIe 상세와 Die/LUN 공유 제약, 실제 예측기는 기존과 같이 포함하지 않는다.',
        '새 정책은 내부 재정렬이 가능한 controller를 가정한다. 순차 후보는 이미 lookup이 끝난 demand 또는 기존 prefetch에서만 고른다. 아직 알려지지 않은 미래 주소를 scheduler가 직접 참조하지 않는다. 기존 Prefetch 후보 생성 자체는 합성 oracle 가정을 유지한다.','',
        '## 재현과 검증','',
        '```sh','python3 -m unittest test_znand test_znand_expansion test_znand_locality -q','python3 -m znand.locality_sweep','python3 -m znand.locality_report','```','',
        '기존 동작 보존·내부 재정렬과 외부 순서 유지·우회 횟수·age 제한·Demand 우선·Group 경계·32/64Plane 진행성 검증을 포함한 테스트 42개를 통과했다. FIFO 대조군 4개는 기존 전체 길이 CSV의 처리량·sensing·Long 횟수·지연을 정확히 재현한다.',
        '[매칭 비교 CSV](matched_comparison.csv), [원본 CSV](sweep.csv), [설정](cases.json), [실행 검증](manifest.json).']
    (out/'RESULTS_KO.md').write_text('\n'.join(lines)+'\n')
    # Usable one-run example for the user's main A2/32MiB diagnosis.
    spec=next(s for s in json.loads((out/'cases.json').read_text()) if s['pattern']=='A2' and s['buffer_mib']==32 and s['config']['stripe']==16384 and s['config']['outstanding']==2048 and s['config']['ca_policy']=='locality')
    Path('znand/locality_A2_32MiB.json').write_text(json.dumps(spec['config'],indent=2))
    print(json.dumps(dict(best=best,improved=positive,decreased=negative,total=len(pairs)),indent=2))
if __name__=='__main__':main()
