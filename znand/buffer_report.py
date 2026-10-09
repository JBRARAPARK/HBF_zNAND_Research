"""Report buffer expansion with matched workloads and separate QD optimization."""
from pathlib import Path
import csv,json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    out=Path('results/znand/buffer_expansion')
    rows=list(csv.DictReader((out/'sweep.csv').open()))
    assert len(rows)==240 and (out/'manifest.json').exists()
    def num(r,k):return float(r.get(k) or 0)
    def select(**kw):return [r for r in rows if all(r[k]==str(v) for k,v in kw.items())]
    def best(rs):return max(rs,key=lambda r:num(r,'bandwidth_gbps'))
    summary=[]
    for pat in ('A1','A2','B1','B2','B3'):
        for mib in (8,16,24,32):
            r=best(select(pattern=pat,buffer_mib=mib))
            base=best(select(pattern=pat,buffer_mib=8))
            summary.append(dict(pattern=pat,buffer_mib=mib,bandwidth_gbps=num(r,'bandwidth_gbps'),
                change_vs_best_8MiB_pct=100*(num(r,'bandwidth_gbps')/num(base,'bandwidth_gbps')-1),
                stripe=r['stripe'],prefetch=r['prefetch'],outstanding=r['outstanding'],
                peak_outstanding=r['peak_outstanding'],buffer_peak_pages=r['buffer_peak_pages'],
                p99_latency_us=r['p99_latency_us'],mean_offer_latency_us=r['mean_offer_latency_us']))
    with (out/'best_by_pattern.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,list(summary[0]),lineterminator='\n');w.writeheader();w.writerows(summary)
    matched=[]
    for r in rows:
        if r['buffer_mib']=='8':continue
        b=select(pattern=r['pattern'],stripe=r['stripe'],prefetch=r['prefetch'],outstanding=r['outstanding'],buffer_mib=8)[0]
        matched.append(dict(pattern=r['pattern'],stripe=r['stripe'],prefetch=r['prefetch'],outstanding=r['outstanding'],buffer_mib=r['buffer_mib'],baseline_gbps=num(b,'bandwidth_gbps'),bandwidth_gbps=num(r,'bandwidth_gbps'),change_pct=100*(num(r,'bandwidth_gbps')/num(b,'bandwidth_gbps')-1)))
    with (out/'matched_comparison.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,list(matched[0]),lineterminator='\n');w.writeheader();w.writerows(matched)
    fig,axs=plt.subplots(2,3,figsize=(14,8))
    for ax,pat in zip(axs.flat,('A1','A2','B1','B2','B3')):
        for st in (4096,16384):
            for pf in (False,True):
                rates=[num(best(select(pattern=pat,stripe=st,prefetch=pf,buffer_mib=m)),'bandwidth_gbps') for m in (8,16,24,32)]
                ax.plot((8,16,24,32),rates,marker='o',label=f'{st//1024}KiB, PF {"ON" if pf else "OFF"}')
        ax.set_title(pat+' (best of QD 2048/4096/8192)');ax.set_xlabel('Shared buffer (MiB)');ax.set_ylabel('Useful host GB/s');ax.set_xticks((8,16,24,32));ax.grid(alpha=.3);ax.legend(fontsize=8)
    axs.flat[-1].axis('off');fig.tight_layout();fig.savefig(out/'buffer_comparison.png',dpi=160);plt.close(fig)
    lines=['# 4port Controller buffer 확대 비교','',
        '기존 8MiB와 16·24·32MiB를 비교했다. 4port, port당 8,192개 요청, seed 7, NAND 가용률 85%, 동일 모델을 사용했다. 8MiB 60개는 해시가 일치하는 기존 extended 결과를 재사용하고 180개를 추가 실행했다. 모든 240행에 대해 별도 회계 검증을 통과했다.','',
        '각 버퍼에서 A1/A2/B1/B2/B3 × 4KiB/16KiB 분산 × Prefetch OFF/ON × Outstanding 2,048/4,096/8,192를 비교했다. Prefetch ON은 정확도 100%, lead 10μs, 미사용 후보 상한 128개다. 버퍼만 늘릴 때 후보 상한을 비례 확대하지 않았다.','',
        '## 패턴별 관측 최고값','',
        '각 칸은 해당 버퍼에서 배치·Prefetch·Outstanding을 비교해 고른 최고값이다. 따라서 버퍼 단독 효과는 아래 동일 조건 비교와 matched_comparison.csv를 사용한다. 단위는 유효 Host GB/s다.','',
        '| 패턴 | 8MiB | 16MiB | 24MiB | 32MiB |','|---|---:|---:|---:|---:|']
    for p in ('A1','A2','B1','B2','B3'):
        lines.append('| '+p+' | '+' | '.join(f"{next(r['bandwidth_gbps'] for r in summary if r['pattern']==p and r['buffer_mib']==m):.3f}" for m in (8,16,24,32))+' |')
    lines+=['','![Buffer comparison](buffer_comparison.png)','','## 최고 조건 상세','','| 패턴 | MiB | GB/s | 분산 KiB | PF | QD/port | 실제 QD peak | p99 μs | offer 기준 평균 μs |','|---|---:|---:|---:|---|---:|---:|---:|---:|']
    for r in summary:
        lines.append(f"| {r['pattern']} | {r['buffer_mib']} | {r['bandwidth_gbps']:.3f} | {int(r['stripe'])//1024} | {r['prefetch']} | {r['outstanding']} | {r['peak_outstanding']} | {float(r['p99_latency_us']):.3f} | {float(r['mean_offer_latency_us']):.3f} |")
    lines+=['','## AXI 설정을 고정한 버퍼 용량과 예약 한도의 동시 변경','','8MiB 최고 성능을 낸 A계열의 AXI·주소 설정을 고정했다. 현재 모델에서는 buffer_pages가 물리 저장 용량과 수락 시 페이지 예약 한도를 함께 결정하므로, 순수 저장 용량만의 효과를 분리한 실험은 아니다.','']
    anchor=best([r for r in select(buffer_mib=8) if r['pattern'].startswith('A')])
    lines +=[f"고정 조건: {anchor['pattern']}, stripe {int(anchor['stripe'])//1024}KiB, PF {anchor['prefetch']}, Outstanding {anchor['outstanding']}/port.",'','| MiB | GB/s | 실제 QD peak | 예약 buffer peak MiB | p99 μs |','|---|---:|---:|---:|---:|']
    for m in (8,16,24,32):
        r=select(pattern=anchor['pattern'],stripe=anchor['stripe'],prefetch=anchor['prefetch'],outstanding=anchor['outstanding'],buffer_mib=m)[0]
        lines.append(f"| {m} | {num(r,'bandwidth_gbps'):.3f} | {r['peak_outstanding']} | {num(r,'buffer_peak_pages')/64:.3f} | {num(r,'p99_latency_us'):.3f} |")
    lines+=['','## 해석 시 주의','','- 유한 길이 합성 trace이며 실제 제품의 최대 성능이나 정상 상태를 보장하지 않는다. 8,192 QD 설정은 port당 총 요청 수와 같아 trace 길이 제약을 확인해야 한다.','- 8MiB의 이전 전체 관측 최고 72.27GB/s는 port당 4,096개 요청 조건이다. 본 비교의 8MiB 기준은 같은 8,192개 요청 조건의 최고 69.28GB/s이며 두 trace를 섞지 않는다.','- buffer_peak_pages는 payload만이 아니라 Host 수락 시 예약 공간도 포함한다. 버퍼 확대는 수락·물리 발행 순서까지 바꾸므로 용량과 scheduling 효과가 함께 나타난다.','- Lookup slot 500/port, Plane 32개, CA/Data 자원과 Prefetch 후보 상한은 유지했다. 확대 후 병목이 다른 자원으로 이동할 수 있다.','- 캐시/LRU는 미도입이며 요청 반환 이후 버퍼 해제 정책을 유지했다.','- 1개 seed·비중첩 port 영역을 사용했다. 실험한 최대 버퍼가 실제 최적 용량이라고 단정하지 않는다.','','원본: [sweep.csv](sweep.csv), [동일 조건 비교](matched_comparison.csv), [최고 조건](best_by_pattern.csv), [재현 입력](cases.json), [실행 검증](manifest.json).']
    insights=['## 관찰과 다음 튜닝','',
        '- 4KiB 읽기인 A1/A2의 비교 범위 내 최고값은 16MiB였다. A1은 78.824GB/s(8MiB 최고 대비 +15.4%), A2는 77.001GB/s(+11.1%)다. 둘 다 16KiB 분산, PF OFF, QD4,096/port다.',
        '- 24/32MiB가 16MiB를 넘지 못했고, B1/B2/B3는 각 용량에서 설정을 고른 최고값도 8MiB보다 낮았다. 현 정책에서 용량 증가를 일괄 적용할 근거는 없다.',
        '- A1·16KiB 분산·PF OFF는 모든 조건에서 sensing 8,192회였다. 16MiB에서 QD2,048→4,096으로 늘리자 Long sensing이 4,963→1,337회, 처리량이 50.179→78.824GB/s로 바뀌었다. 요청 수보다 실제 발행 순서와 tR 구성이 중요하다.',
        '- A1 최고 조건의 수락 이후 p99는 8MiB 236.682μs→16MiB 477.613μs로 늘었지만, 제시부터 반환까지의 평균은 802.174→751.272μs로 줄었다. 수락 시점이 달라지므로 p99만으로 사용자 체감 지연 전체를 판단하지 않는다.',
        '- 현 모델에서 처리량 중심 A계열 후보는 16MiB·QD4,096이고 B계열은 8MiB 설정을 유지해 비교하는 편이 타당하다. 실제 최적값 확정 전 admission과 Plane-local locality를 유지하는 내부 중재를 함께 평가한다.',
        '- 64MiB 및 64Plane 조합은 이번 범위에 포함하지 않았다. 사용자 요청의 16·24·32MiB 비교를 완료했으며, Word 문서의 64MiB 제안과 원격 64Plane 진단은 별도 후속 항목이다.','']
    pos=lines.index('## 해석 시 주의');lines[pos:pos]=insights
    lines+=['','## 예약 한도를 분리한 추가 확인','',
        '동일 A2·16KiB 분산·PF ON·QD2,048/port·8,192요청/port에서 32MiB 저장 용량을 유지하되 예약 한도를 기존 512페이지로 제한했다. 처리량은 69.282GB/s로 기존 8MiB와 일치했고, config를 제외한 모든 결과 지표와 동작 계수가 기존 8MiB CSV와 정확히 일치했다. 단, 32MiB 중 최대 8MiB만 사용하는 대조 실험이며 전체 32MiB 활용 정책을 검증한 결과는 아니다.',
        '예약 한도도 2,048페이지로 늘린 원래 32MiB 조건은 37.083GB/s다. 8MiB→32MiB에서 sensing 횟수는 8,278→8,196회로 비슷하지만 Long 비율은 11.14%→91.81%, 평균 sensing은 3.239→11.404μs로 증가했다. 현재 CA 중재는 Demand 우선·등록 순서이며 Plane-local 연속성을 고려하지 않는다. 작은 버퍼의 수락 제한이 발행 순서를 간접적으로 제한한 효과다.',
        '따라서 앞 절의 용량별 최고값을 하드웨어 최적 용량으로 해석하지 않는다. 물리 buffer 크기와 예약 window를 독립 변수로 분리하고 내부 주소 순서·port 공정성을 함께 비교해야 한다. Port 내부 외부 응답 순서는 계속 in-order로 유지한다.',
        '대조 실험 원본은 [capped_32MiB.json](../buffer_causality/capped_32MiB.json)이며 `python3 -m znand.buffer_causality`로 재현한다.']
    (out/'RESULTS_KO.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
