# Brief: A throughput-based R2A for pydash (installed into pydash's r2a/ by lft-pydash-client): each
# segment gets the highest quality whose bitrate fits 80% of the mean throughput of the last 3 segments,
# as dash-play does; the first one, with nothing measured yet, the lowest.
import time

from player.parser import parse_mpd
from r2a.ir2a import IR2A

WINDOW = 3


class R2AThroughput(IR2A):

    def __init__(self, id):
        IR2A.__init__(self, id)
        self.qi, self.throughputs, self.sent = [], [], 0.0

    def handle_xml_request(self, msg):
        self.send_down(msg)

    def handle_xml_response(self, msg):
        self.qi = parse_mpd(msg.get_payload()).get_qi()
        self.send_up(msg)

    def handle_segment_size_request(self, msg):
        recent = self.throughputs[-WINDOW:]
        budget = 0.8 * sum(recent) / len(recent) if recent else 0
        msg.add_quality_id(max([q for q in self.qi if q <= budget] or self.qi[:1]))
        self.sent = time.perf_counter()
        self.send_down(msg)

    def handle_segment_size_response(self, msg):
        self.throughputs.append(msg.get_bit_length() / (time.perf_counter() - self.sent))
        self.send_up(msg)

    def initialize(self):
        pass

    def finalization(self):
        pass
