"""Current workload names (schema 2), around the frozen historical device model.

A1/A2: 4KiB full reads. B: consecutive 64B reads covering every logical page.
C1/C2/C3: historical B1/B2/B3 sparse 64B reads. Legacy names are explicit aliases.
Historical experiment modules and their hashed inputs retain schema-1 identifiers.
"""
import math
import random
import warnings

from .model import Input, PAGE, workload as legacy_workload
from .partial_saturation import PartialReadSimulator

SCHEMA_VERSION = 2
PATTERNS = ('A1', 'A2', 'B', 'C1', 'C2', 'C3')
LEGACY_TO_CURRENT = {'B1': 'C1', 'B2': 'C2', 'B3': 'C3'}


def canonical_pattern(pattern):
    if pattern in LEGACY_TO_CURRENT:
        current = LEGACY_TO_CURRENT[pattern]
        warnings.warn(f'{pattern} is the legacy name of {current}; new B means consecutive 64B reads within each 4KiB page.',
                      FutureWarning, stacklevel=2)
        return current
    if pattern not in PATTERNS:
        raise ValueError(f'Unknown workload {pattern!r}; choose from {PATTERNS}')
    return pattern


def address_offset(pattern, sequence):
    """Byte address within a Port's region, using zero-based request sequence."""
    if sequence < 0:
        raise ValueError('sequence must be nonnegative')
    if pattern == 'B':
        return sequence * 64
    if pattern in ('A1', 'C1'):
        return sequence * 4096
    if pattern in ('A2', 'C2'):
        group, position = divmod(sequence, 3)
        return (group * 3 + (0, 2, 1)[position]) * 4096
    if pattern == 'C3':
        group, position = divmod(sequence, 4)
        return (group * 3 + (0, 2, 0, 1)[position]) * 4096 + (64 if position == 2 else 0)
    raise ValueError(pattern)


def workload(pattern='C3', ports=4, per_port=2048, overlap=0., host_mhz=1000., seed=7):
    pattern = canonical_pattern(pattern)
    if per_port < 1 or not 1 <= ports <= 4 or not 0 <= overlap <= 1 or host_mhz <= 0:
        raise ValueError('Invalid request count, port count, overlap or Host frequency')
    if pattern != 'B':
        old = 'B' + pattern[1] if pattern.startswith('C') else pattern
        return legacy_workload(old, ports, per_port, overlap, host_mhz, seed)
    logical_pages = math.ceil(per_port / 64)
    span = math.ceil(logical_pages * 4096 / (PAGE * 32)) * PAGE * 32
    result = []
    for port in range(ports):
        for sequence in range(per_port):
            offset = address_offset('B', sequence)
            logical = offset // 4096
            shared = random.Random(seed + logical // 3).random() < overlap
            base = 0 if shared else (port + 1) * span
            result.append(Input(port, base + offset, 64, 30. + sequence / host_mhz))
    return sorted(result, key=lambda r: (r.offer, r.port))


class ContinuousRead64Simulator(PartialReadSimulator):
    """Current B/C names with existing admission, buffer lifetime and in-order R."""
    def __init__(self, config, pattern, region_span, duration_us=2200., start_us=30.):
        pattern = canonical_pattern(pattern)
        if pattern not in ('B', 'C1', 'C2', 'C3'):
            raise ValueError('This observer accepts 64B workloads B/C1/C2/C3')
        # The legacy initializer only creates request zero, identical for all four.
        super().__init__(config, 'B1', region_span, duration_us, start_us)
        self.pattern = pattern

    def replenish(self, port):
        assert not self.sources[port]
        offset = address_offset(self.pattern, self.sequence[port])
        assert offset + 64 <= self.region_span, 'Increase the mapped address domain'
        address = (port + 1) * self.region_span + offset
        key, physical_offset = self.mapper.map(address)
        index = len(self.req)
        self.req.append(dict(port=port, addr=address, size=64, offer=self.now,
                             key=key, offset=physical_offset, lookup=False, accepted=None,
                             ready=None, end=None, head_since=None))
        self.sources[port].append(index)
        self.sequence[port] += 1
