"""Acceptance-cohort latency statistics; incomplete cohorts are rejected.

Quantiles use nearest rank (ceil(p*N), one-based). Times are microseconds.
This module observes requests only and never changes device scheduling.
"""
import math
import statistics


def distribution(values):
    values = sorted(values)
    if not values:
        raise ValueError('Empty latency population')
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('Latency values must be finite and nonnegative')
    result = dict(n=len(values), mean_us=statistics.fmean(values), min_us=values[0], max_us=values[-1])
    for label, p in [('p50', .5), ('p95', .95), ('p99', .99), ('p99_9', .999)]:
        result[label + '_us'] = values[math.ceil(len(values) * p) - 1]
    return result


def cohort(requests, start, end):
    if end <= start:
        raise ValueError('Invalid acceptance window')
    selected = [r for r in requests if r['accepted'] is not None and start <= r['accepted'] < end]
    if not selected:
        raise ValueError('Empty acceptance cohort')
    incomplete = sum(r['end'] is None for r in selected)
    if incomplete:
        raise ValueError(f'{incomplete} cohort requests remain incomplete; continue saturated supply')
    return selected


def measurements(request):
    r = request
    boundaries = [r['accepted'], r['lookup_start'], r['lookup_end'], r['ready'], r['r_start'], r['end']]
    if any(b < a - 1e-8 for a, b in zip(boundaries, boundaries[1:])):
        raise ValueError('Request timestamps are not ordered')
    parts = dict(zip(('lookup_queue_us', 'lookup_service_us', 'post_lookup_to_ready_us',
                      'ready_to_host_start_us', 'host_transfer_us'),
                     (max(0., b - a) for a, b in zip(boundaries, boundaries[1:]))))
    result = dict(device_latency_us=r['end'] - r['accepted'],
                  first_byte_latency_us=r['r_start'] - r['accepted'],
                  admission_wait_us=r['accepted'] - r['offer'],
                  offered_latency_us=r['end'] - r['offer'], **parts)
    if not math.isclose(sum(parts.values()), result['device_latency_us'], abs_tol=1e-8):
        raise ValueError('Latency decomposition mismatch')
    return result


def summarize_latency(requests, start, end):
    selected = cohort(requests, start, end)
    def group(rs):
        values = [measurements(r) for r in rs]
        return {name: distribution(v[name] for v in values) for name in values[0]}
    return dict(acceptance_start_us=start, acceptance_end_us=end, requests=len(selected),
                censored_requests=0, quantile_method='nearest_rank',
                all=group(selected),
                per_port={str(p): group([r for r in selected if r['port'] == p])
                          for p in sorted({r['port'] for r in selected})},
                last_cohort_completion_us=max(r['end'] for r in selected),
                completions_after_cohort_window=sum(r['end'] >= end for r in selected))
