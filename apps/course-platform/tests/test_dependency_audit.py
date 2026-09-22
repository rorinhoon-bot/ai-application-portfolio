"""Read-only dependency inventory: parsing, version evidence, and license uncertainty."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_dependencies import audit, parse_pins


class DependencyAuditTests(unittest.TestCase):
    def test_pins_and_unpinned_requirement_rejection(self):
        with tempfile.TemporaryDirectory(prefix='dep-pins-') as folder:
            path = Path(folder) / 'requirements.txt'
            path.write_text('# local lock\n-r other.txt\nA_B==1.2 --hash=sha256:abc\n', encoding='utf-8')
            self.assertEqual(parse_pins(path)['a-b']['pinned_version'], '1.2')
            path.write_text('A_B>=1.2\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'UNPINNED_REQUIREMENT'):
                parse_pins(path)

    def test_missing_version_and_license_conflict_are_distinct(self):
        with tempfile.TemporaryDirectory(prefix='dep-audit-') as folder:
            root = Path(folder)
            for project, lock in (('01-cited-rag', 'requirements.txt'),
                                  ('02-agent-research-workflow', 'requirements.txt'),
                                  ('03-mcp-tool-server', 'requirements.lock.txt')):
                path = root / 'projects' / project
                path.mkdir(parents=True)
                (path / lock).write_text('Alpha==1.0\nBeta==2.0\n', encoding='utf-8')
            metadata = {'alpha': {'installed_version': '1.1', 'license_declared': 'MIT',
                                  'license_classifiers': ['License :: Other/Proprietary License']},
                        'beta': {'installed_version': None, 'license_declared': None,
                                 'license_classifiers': []}}
            with patch('audit_dependencies.inspect_environment', return_value=metadata):
                result = audit(root)
            self.assertEqual(result['summary'], {'pins': 6, 'missing_distributions': 3,
                             'version_mismatches': 3, 'licenses_needing_review': 6,
                             'license_metadata_conflicts': 3})
            self.assertEqual(result['installations'], 0)
            self.assertEqual(result['downloads'], 0)


if __name__ == '__main__':
    unittest.main()
