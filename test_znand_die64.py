import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from znand.model import Config, Input, Mapper, PAGE, Simulator
from znand.workloads import workload


class Die64Tests(unittest.TestCase):
    def test_all_physical_addresses_and_page_offsets(self):
        for stripe in (4096, PAGE):
            c = Config.die64(stripe=stripe)
            m = Mapper(c)
            slots = {}
            for i in range(256):
                key, off = m.map_hierarchical(i * 4096)
                slots.setdefault(key, set()).add(off)
            self.assertEqual(set(slots), {(d, ch, pl, 0) for d in range(4)
                                         for ch in range(2) for pl in range(8)})
            self.assertTrue(all(s == {0, 4096, 8192, 12288} for s in slots.values()))
            self.assertEqual(m.map_hierarchical(64 * PAGE), ((0, 0, 0, 1), 0))
            for ch in range(8):
                self.assertEqual(m.map_hierarchical(ch * stripe)[0][:2], divmod(ch, 2))

    def test_flat_and_die64_have_identical_workload_timing(self):
        for stripe in (4096, PAGE):
            for pattern in ('A1', 'A2', 'B', 'C1', 'C2', 'C3'):
                c = Config(channels=8, planes=8, stripe=stripe, io_gbps=40.05625,
                           buffer_pages=8, outstanding=64, trace=True)
                inputs = workload(pattern, per_port=96, overlap=.5)
                a, b = Simulator(c, inputs), Simulator(replace(c, dies=4, channels_per_die=2), inputs)
                a.run(); b.run()
                self.assertEqual(a.req, b.req)
                self.assertEqual(a.count, b.count)
                self.assertEqual(a.plane, b.plane)
                self.assertEqual(a.log, [{k: v for k, v in event.items() if k != 'physical_address'}
                                         for event in b.log])

    def test_same_die_pseudo_channels_overlap_but_one_pc_serializes(self):
        c = Config.die64(stripe=PAGE, availability=1., trace=True)
        sim = Simulator(c, [Input(0, 0, 64, 30.), Input(1, PAGE, 64, 30.),
                            Input(2, 8 * PAGE, 64, 30.)])
        sim.run()
        for kind in ('ca_start', 'data_start'):
            events = [e for e in sim.log if e['event'] == kind]
            pc0, pc1 = [e for e in events if e['key'][0] == 0], [e for e in events if e['key'][0] == 1]
            self.assertLess(max(pc0[0]['time_us'], pc1[0]['time_us']),
                            min(pc0[0]['time_us'] + pc0[0]['duration'], pc1[0]['time_us'] + pc1[0]['duration']))
            self.assertGreaterEqual(pc0[1]['time_us'] + 1e-9, pc0[0]['time_us'] + pc0[0]['duration'])

    def test_die_distribution_adds_no_penalty_without_shared_die_resources(self):
        c = Config.die64(stripe=PAGE, availability=1., outstanding=64)
        def run(channels):
            inputs = [Input(i % 4, ((i // 2) * 8 + channels[i % 2]) * PAGE, 4096, 30.)
                      for i in range(64)]
            s = Simulator(c, inputs); s.run()
            return [[r.get(k) for k in ('accepted', 'ready', 'r_start', 'end')] for r in s.req]
        self.assertEqual(run([0, 1]), run([0, 2]))

    def test_snapshot_requires_declared_die64_and_preserves_mapping(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'snapshot.json'
            c = Config.die64(snapshot=str(path))
            doc = dict(page_bytes=PAGE, model_geometry=dict(channels=8, planes_per_channel=8),
                       mapping={'0': [7, 7, 19]})
            path.write_text(json.dumps(doc))
            with self.assertRaises(ValueError): Mapper(c)
            doc['model_geometry'] = c.model_geometry
            path.write_text(json.dumps(doc))
            self.assertEqual(Mapper(c).map_hierarchical(0), ((3, 1, 7, 19), 0))
            doc.update(address_format='die_channel_plane_page', mapping={'0': [3, 1, 7, 19]})
            path.write_text(json.dumps(doc))
            self.assertEqual(Mapper(c).map(0), ((7, 7, 19), 0))


if __name__ == '__main__': unittest.main()
