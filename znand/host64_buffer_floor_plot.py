"""Plot measured buffer-capacity points; matplotlib is optional for simulation."""
import argparse
import json
from pathlib import Path

from .host64_buffer_floor import ROOT
from .pf_qd_sweep import digest, read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT)
    args = parser.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    out = args.out
    rows = read(out / 'rows.json')
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
    for ax, length in zip(axes, (32768, 8192)):
        ax.axhspan(200, 270, color='#e9f4ec', zorder=0)
        ax.axhline(200, color='#555555', linestyle='--', linewidth=1.2, label='200 GB/s target')
        for pattern, color, marker in (('A1', '#1768ac', 'o'), ('A2', '#d45d00', 's')):
            group = sorted((r for r in rows if (r['pattern'], r['per_port']) == (pattern, length)
                            and r['buffer_mib'] <= 16), key=lambda r: r['buffer_mib'])
            ax.plot([r['buffer_mib'] for r in group], [r['bandwidth_gbps'] for r in group],
                    color=color, marker=marker, markersize=4, linewidth=1.5, label=pattern)
            passing = [r for r in group if r['bandwidth_gbps'] >= 200]
            if passing:
                first = passing[0]
                ax.scatter([first['buffer_mib']], [first['bandwidth_gbps']], s=85,
                           facecolors='none', edgecolors=color, linewidth=1.8, zorder=4)
        ax.set_title(f'{length:,} requests / port', fontsize=12)
        ax.set_xlabel('Shared controller buffer (MiB)')
        ax.set_xlim(0, 16.5)
        ax.set_ylim(40, 270)
        ax.set_xticks(range(0, 17, 2))
        ax.grid(axis='y', color='#cccccc', alpha=.55)
        ax.spines[['top', 'right']].set_visible(False)
    axes[0].set_ylabel('Whole-run Host throughput (GB/s)')
    axes[1].legend(loc='lower right', frameon=True)
    fig.suptitle('64-Plane region layout: buffer capacity and throughput', fontsize=14)
    fig.text(.5, .025, 'Fixed tR / QD 2,048 per port / PF OFF / 4 balanced address regions / seed 7\n'
             'Points are measurements; connecting lines are visual guides. Rings mark the smallest measured passing capacity.',
             ha='center', fontsize=8, color='#444444')
    fig.tight_layout(rect=(0, .10, 1, .93))
    fig.savefig(out / 'buffer_capacity.png', dpi=180)
    fig.savefig(out / 'buffer_capacity.pdf')
    plt.close(fig)
    (out / 'plot_manifest.json').write_text(json.dumps(dict(
        source_sha256=digest(__file__), rows_sha256=digest(out / 'rows.json'),
        png_sha256=digest(out / 'buffer_capacity.png'), pdf_sha256=digest(out / 'buffer_capacity.pdf')),
        indent=2) + '\n')


if __name__ == '__main__':
    main()
