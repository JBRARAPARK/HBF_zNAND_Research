"""Scientific time-series figures with actual outstanding and request counts."""
import argparse
import json
from pathlib import Path

from .pf_qd_sweep import digest, read
from .saturation_sweep import ROOT
from .saturation_report import best_by_buffer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT)
    args = parser.parse_args()
    out = args.out
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    rows = read(out / 'rows.json')
    selected = best_by_buffer(rows)
    colors = ['#1768ac', '#d45d00', '#238443', '#88419d']
    outputs = []

    def save(fig, name):
        for suffix in ('png', 'pdf'):
            path = out / f'{name}.{suffix}'
            fig.savefig(path, dpi=160, bbox_inches='tight')
            outputs.append(path)
        plt.close(fig)

    for pattern in ('A1', 'A2'):
        best = next(r for r in selected if r['pattern'] == pattern and r['buffer_mib'] == 8)
        over = next(r for r in rows if r['pattern'] == pattern and r['buffer_mib'] == 8 and r['configured_qd_per_port'] == 2048)
        fig, axes = plt.subplots(5, 2, figsize=(14, 13), sharex=True)
        for column, case in enumerate((best, over)):
            series = read(out / 'timelines' / (case['name'] + '.json'))
            xs = [(r['t_start_us'] + r['t_end_us']) / 2 for r in series]
            col = axes[:, column]
            for ax in col:
                ax.axvspan(0, 200, color='#bbbbbb', alpha=.3)
                ax.axvspan(case['peak_start_us'], case['peak_end_us'], color='#74c476', alpha=.16)
                ax.grid(axis='y', alpha=.25)
                ax.spines[['top', 'right']].set_visible(False)
                ax.set_xlim(0, 2200)
            col[0].plot(xs, [r['bandwidth_gbps'] for r in series], color='#222222', linewidth=1.6, label='Total')
            for port in range(4):
                col[0].plot(xs, [r[f'p{port}_gbps'] for r in series], color=colors[port], linewidth=.9, label=f'Port {port}')
                col[1].plot(xs, [r[f'p{port}_outstanding_mean'] for r in series], color=colors[port], linewidth=1.2, label=f'Port {port}')
            col[0].axhline(200, color='#666666', linestyle='--', linewidth=.8)
            col[0].set_ylim(0, 275)
            col[0].set_title(f"8 MiB | QD cap {case['configured_qd_per_port']:,}/port\n"
                             f"2 ms mean {case['fixed_gbps']:.2f} GB/s | Best 500 us {case['peak_500us_gbps']:.2f}", fontsize=11)
            col[0].legend(ncol=5, fontsize=7, loc='upper center', bbox_to_anchor=(.5, -.015), frameon=False)
            col[1].axhline(case['configured_qd_per_port'], color='#777777', linestyle='--', linewidth=.9, label='Configured cap')
            col[1].set_ylim(bottom=0)
            col[1].text(.02, .93, 'Actual mean total: ' + f"{case['fixed_actual_outstanding']:.1f}",
                        transform=col[1].transAxes, va='top', fontsize=9,
                        bbox=dict(facecolor='white', alpha=.8, edgecolor='none'))
            col[2].plot(xs, [r['accepted_requests'] for r in series], color='#1768ac', label='Accepted')
            col[2].plot(xs, [r['completed_requests'] for r in series], color='#d45d00', linestyle='--', label='Completed')
            col[2].legend(fontsize=8, loc='upper right')
            col[2].text(.02, .93, f"Best 500 us: {case['peak_completed_requests']:,} completed",
                        transform=col[2].transAxes, va='top', fontsize=9,
                        bbox=dict(facecolor='white', alpha=.8, edgecolor='none'))
            col[3].plot(xs, [r['cumulative_accepted'] for r in series], color='#1768ac', label='Accepted')
            col[3].plot(xs, [r['cumulative_completed'] for r in series], color='#d45d00', linestyle='--', label='Completed')
            col[3].yaxis.set_major_formatter(FuncFormatter(lambda v, pos: f'{v/1000:g}k'))
            col[3].legend(fontsize=8, loc='upper left')
            col[4].plot(xs, [r['buffer_mean_mib'] for r in series], color='#238443', label='Reserved buffer')
            col[4].axhline(8, color='#777777', linestyle='--', linewidth=.9)
            col[4].set_ylim(0, 8.6)
            col[4].set_xlabel('Time from first request (us)')
        for row_index, label in enumerate(('Host throughput (GB/s)', 'Actual outstanding / port',
                                           'Requests / 25 us', 'Cumulative requests', 'Buffer used (MiB)')):
            axes[row_index, 0].set_ylabel(label)
        fig.suptitle(f'{pattern}: continuous load, device outstanding and time-window throughput', fontsize=14, y=.995)
        fig.text(.5, .005, 'Gray: initial 200 us excluded. Green: highest 500 us average window. '
                 'Every port has continuous Host input; no end-of-work drain.\n'
                 'Outstanding = accepted minus final responses completed. tR and device scheduling are unchanged.',
                 ha='center', fontsize=9)
        fig.tight_layout(rect=(0, .04, 1, .97), h_pad=1.3)
        save(fig, pattern + '_time_comparison')

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    buffers = sorted({r['buffer_mib'] for r in rows})
    palette = plt.get_cmap('tab10')
    for column, pattern in enumerate(('A1', 'A2')):
        for index, mib in enumerate(buffers):
            group = sorted((r for r in rows if r['pattern'] == pattern and r['buffer_mib'] == mib),
                           key=lambda r: r['configured_qd_per_port'])
            color = palette(index)
            axes[0, column].plot([r['configured_qd_per_port'] for r in group], [r['fixed_gbps'] for r in group],
                                 marker='o', color=color, label=f'{mib:g} MiB', linewidth=1.3)
            axes[1, column].scatter([r['fixed_actual_outstanding'] for r in group], [r['fixed_gbps'] for r in group],
                                    marker='o', color=color, label=f'{mib:g} MiB', s=40, alpha=.8)
        axes[0, column].set_xscale('log', base=2)
        ticks = sorted({r['configured_qd_per_port'] for r in rows})
        axes[0, column].set_xticks(ticks, [str(q) for q in ticks])
        axes[0, column].set_xlabel('Configured device QD cap / port')
        axes[1, column].set_xlabel('Actual mean device outstanding, all ports')
        axes[0, column].set_title(pattern)
        axes[0, column].legend(fontsize=9)
        for ax in axes[:, column]:
            ax.axhline(200, color='#777777', linestyle='--', linewidth=1)
            ax.axhline(256, color='#aaaaaa', linestyle=':', linewidth=1)
            ax.set_ylim(40, 270)
            ax.grid(alpha=.2)
            ax.spines[['top', 'right']].set_visible(False)
    axes[0, 0].set_ylabel('Fixed 2 ms average (GB/s)')
    axes[1, 0].set_ylabel('Fixed 2 ms average (GB/s)')
    fig.suptitle('64-Plane region layout: buffer capacity, configured QD and actual outstanding', fontsize=14)
    fig.text(.5, .015, 'Continuous load / 200 us warmup / 2 ms measurement / PF OFF / fixed tR / seed 7\n'
             'A total outstanding count does not show its distribution across ports; see the time-series figures.',
             ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .065, 1, .95))
    save(fig, 'outstanding_performance')
    (out / 'plot_manifest.json').write_text(json.dumps(dict(source_sha256=digest(__file__),
        rows_sha256=digest(out / 'rows.json'), outputs={str(p): digest(p) for p in outputs}), indent=2) + '\n')


if __name__ == '__main__':
    main()
