import unittest
from znand.model import Config, Input, PAGE, Simulator


class AdmissionOnly(Simulator):
    def pump(self):
        pass


class RoundRobinAdmissionTests(unittest.TestCase):
    def make_sim(self, counts=(3,3,3,3), **options):
        c=Config.die32(trace=True,availability=1.,stripe=PAGE,**options)
        inputs=[Input(p,(p*16+i)*PAGE,4096,0.) for p,n in enumerate(counts) for i in range(n)]
        return AdmissionOnly(c,inputs)

    def grants(self,s):
        return [e['port'] for e in s.log if e['event']=='accept']

    def one_credit(self,s):
        # Isolate shared-credit arbitration: exactly one new page can be reserved.
        limit=len(s.items)+1
        s.capacity=lambda head=False:len(s.items)<limit
        s.admit()
        s.now+=.01

    def test_repeated_single_credit_rotates_without_starvation(self):
        s=self.make_sim()
        for _ in range(12):self.one_credit(s)
        self.assertEqual(self.grants(s),[0,1,2,3]*3)

    def test_failed_pass_retains_priority(self):
        s=self.make_sim();self.one_credit(s)
        s.capacity=lambda head=False:False
        for _ in range(3):s.admit()
        self.assertEqual(s.admission_next_port,1)
        self.one_credit(s)
        self.assertEqual(self.grants(s),[0,1])

    def test_empty_full_and_future_ports_do_not_block_ready_port(self):
        s=self.make_sim((3,0,3,3),outstanding=1)
        self.one_credit(s)  # Port 0 reaches its QD limit.
        s.req[s.sources[2][0]]['offer']=10.
        self.one_credit(s)  # Empty 1 and future 2 are skipped.
        self.assertEqual(self.grants(s),[0,3])
        s.now=10.;self.one_credit(s)
        self.assertEqual(self.grants(s),[0,3,2])

    def test_multiple_grants_preserve_circular_order_and_host_rate(self):
        s=self.make_sim();s.admission_next_port=2;s.admit()
        self.assertEqual(self.grants(s),[2,3,0,1])
        s.admit()  # No additional grant before each port's next AR cycle.
        self.assertEqual(len(self.grants(s)),4)
        self.assertEqual(s.admission_next_port,2)

    def test_merged_request_is_a_successful_grant(self):
        s=self.make_sim((1,1,0,0))
        s.req[1]['key']=s.req[0]['key']
        self.one_credit(s)
        self.assertEqual(self.grants(s),[0,1])
        self.assertEqual(s.admission_next_port,2)
        self.assertEqual(len(s.items),1)


if __name__=='__main__':unittest.main()
