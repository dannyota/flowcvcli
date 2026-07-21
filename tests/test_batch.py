"""Batch context: one GET per read-burst, invalidated by writes (no network)."""
import json
import unittest

from flowcvcli.api import FlowCV
from flowcvcli.config import Config


def make_resume():
    return {"id": "R1", "content": {"publication": {
        "sectionType": "publication", "displayName": "Publications",
        "iconKey": "newspaper", "entries": [{"id": "E1", "title": "Orig"}]}}}


class ScriptedFlowCV(FlowCV):
    """Serves the canned resume through the real request/get_resume path, counting
    the low-level `_send` calls so we can prove how many GETs a burst actually costs."""

    def __init__(self, resume):
        super().__init__(config=Config(resume_id="R1", cookie="flowcvsidapp=x"))
        self._resume = resume
        self.sends = []          # (method, path) per _send

    def _send(self, path, method, body, query, timeout):
        self._ensure_auth()
        self.sends.append((method, path))
        self._last_headers = {}
        if method == "GET" and path == "resumes/R1":
            env = {"success": True, "data": {"resume": self._resume}}
        else:
            env = {"success": True, "data": {}}
        return 200, json.dumps(env).encode()

    def resume_gets(self):
        return [s for s in self.sends if s == ("GET", "resumes/R1")]


class BatchCachingTest(unittest.TestCase):
    def test_many_reads_in_a_batch_fetch_once(self):
        fc = ScriptedFlowCV(make_resume())
        with fc.batch():
            fc.get_resume()
            fc.get_resume()
            fc.get_resume()
        self.assertEqual(len(fc.resume_gets()), 1)

    def test_no_caching_outside_a_batch(self):
        fc = ScriptedFlowCV(make_resume())
        fc.get_resume()
        fc.get_resume()
        fc.get_resume()
        self.assertEqual(len(fc.resume_gets()), 3)

    def test_a_write_invalidates_the_cache(self):
        fc = ScriptedFlowCV(make_resume())
        with fc.batch():
            fc.get_resume()                                    # fetch #1
            fc.get_resume()                                    # cached
            fc.request("resumes/save_entry", method="PATCH",   # write -> invalidate
                       body={"resumeId": "R1"})
            fc.get_resume()                                    # fetch #2 (refetch)
            fc.get_resume()                                    # cached again
        self.assertEqual(len(fc.resume_gets()), 2)

    def test_a_get_request_does_not_invalidate(self):
        fc = ScriptedFlowCV(make_resume())
        with fc.batch():
            fc.get_resume()                       # fetch #1
            fc.request("resumes/all")             # a GET must not bust the cache
            fc.get_resume()                       # still cached
        self.assertEqual(len(fc.resume_gets()), 1)

    def test_cache_is_dropped_when_the_batch_ends(self):
        fc = ScriptedFlowCV(make_resume())
        with fc.batch():
            fc.get_resume()
        fc.get_resume()                           # fresh batch/none -> refetch
        self.assertEqual(len(fc.resume_gets()), 2)

    def test_returned_copies_are_independent(self):
        fc = ScriptedFlowCV(make_resume())
        with fc.batch():
            a = fc.get_resume()
            a["content"]["publication"]["entries"][0]["title"] = "MUTATED"
            b = fc.get_resume()
        # Mutating a returned copy must not leak into a later cached read.
        self.assertEqual(b["content"]["publication"]["entries"][0]["title"], "Orig")
        self.assertEqual(len(fc.resume_gets()), 1)

    def test_nested_batches_share_one_fetch_and_survive_inner_exit(self):
        fc = ScriptedFlowCV(make_resume())
        with fc.batch():
            fc.get_resume()                       # fetch #1
            with fc.batch():
                fc.get_resume()                   # cached (nested)
            fc.get_resume()                       # still cached after inner exit
        self.assertEqual(len(fc.resume_gets()), 1)


if __name__ == "__main__":
    unittest.main()
