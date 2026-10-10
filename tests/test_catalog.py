import unittest
from app.catalog import find_conflicts, optimize_agenda

S = [
 {"code":"A","title":"AI Integration","description":"customer lessons","date":"2026-10-27","startTime":"10:00","endTime":"10:45","areasOfInterest":["Integration"]},
 {"code":"B","title":"AI Agents","description":"","date":"2026-10-27","startTime":"10:40","endTime":"11:20","areasOfInterest":["AI Agents"]},
 {"code":"C","title":"Partner Growth","description":"business outcomes","date":"2026-10-27","startTime":"12:00","endTime":"12:45","areasOfInterest":[]}
]

class CatalogTest(unittest.TestCase):
    def test_conflict(self):
        r = find_conflicts(S, ['A','B'], 0)
        self.assertEqual(1, len(r['conflicts']))
    def test_optimize(self):
        r = optimize_agenda(S, {"date":"2026-10-27","interests":["integration","partner"]})
        self.assertTrue(r['agenda'])

if __name__ == '__main__': unittest.main()
