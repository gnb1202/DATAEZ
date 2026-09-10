"""Local runner safeguards; no Docker service or paid API is needed."""
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run


class DemoRunnerTests(unittest.TestCase):
    def test_settings_persist_secrets_and_ports_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(run, 'STATE', Path(tmp)):
            initial = run.settings(SimpleNamespace(web_port=3139, api_port=8149))
            again = run.settings(SimpleNamespace(web_port=None, api_port=None))
            self.assertEqual(initial, again)
            with self.assertRaisesRegex(RuntimeError, 'already fixed'):
                run.settings(SimpleNamespace(web_port=3140, api_port=None))
            self.assertEqual(json.loads((Path(tmp)/'settings.json').read_text()), initial)

    def test_foreign_project_label_prevents_stop(self):
        foreign = {'Id':'foreign', 'Config':{'Labels':{run.LABEL:'another-workspace'}}}
        with patch.object(run,'docker',side_effect=['foreign',json.dumps([foreign])]) as docker:
            with self.assertRaisesRegex(RuntimeError, 'refusing to manage'):
                run.resources('container')
            self.assertEqual(docker.call_count,2)

    def test_foreign_volume_prevents_start(self):
        with patch.object(run,'docker',side_effect=['foreign',json.dumps([{'Labels':{}}])]):
            with self.assertRaisesRegex(RuntimeError, 'unrecognized volume'):
                run.resources('volume')

    def test_missing_model_key_and_real_port_conflict_have_distinct_errors(self):
        def model(key):
            return json.dumps({'services':{'api':{'environment':{'OPENAI_API_KEY':key}}}})
        config = {'web_port':3139,'api_port':8149}
        with patch.object(run,'docker',return_value=model('sk-...')):
            with self.assertRaisesRegex(RuntimeError, 'Set OPENAI_API_KEY'):
                run.preflight(config,{},[])
        with socket.socket() as occupied:
            if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
                occupied.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            occupied.bind(('127.0.0.1',0)); occupied.listen()
            config['web_port']=occupied.getsockname()[1]
            with patch.object(run,'docker',return_value=model('test-model-key')):
                with self.assertRaisesRegex(RuntimeError, f"Port {config['web_port']} is in use"):
                    run.preflight(config,{},[])

    def test_missing_settings_with_persistent_volume_fails_before_start(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(run,'STATE',Path(tmp)), \
             patch.object(run,'resources',side_effect=[[],[{'Name':'existing'}]]), \
             patch.object(run,'docker',return_value='ok') as docker, \
             patch('sys.argv',['run.py','start']):
            with self.assertRaisesRegex(RuntimeError, 'Restore it before starting'):
                run.main()
            self.assertFalse((Path(tmp)/'settings.json').exists())
            self.assertEqual(docker.call_count,1)


if __name__ == '__main__':
    unittest.main()
