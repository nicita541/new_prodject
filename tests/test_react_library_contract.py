import json
from pathlib import Path
import shutil
import uuid
import unittest

from fastapi.testclient import TestClient
from app.config import ROOT, TEMP
from app.server import create_app
from tests.library_contract_fixture import build_library, identifier


class ReactLibraryContractTests(unittest.TestCase):
    def setUp(self):
        self.directory=TEMP/('react-contract-'+uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        manager,self.library=build_library(self.directory)
        self.client=TestClient(create_app(manager),base_url='http://127.0.0.1')
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.directory.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(self.directory)

    def test_frontend_fixture_is_exact_current_backend_snapshot(self):
        expected=json.loads((ROOT/'frontend/src/test/fixtures/library.json').read_text('utf-8'))
        response=self.client.get('/api/library')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),expected)
        self.assertEqual(set(expected),{'projects','episodes'})
        self.assertTrue(all('episodes' not in p for p in expected['projects']))
        self.assertTrue(all(set(j)=={'id','status','created_at'} for e in expected['episodes'] for j in e['jobs']))

    def test_restore_returns_actual_id_archived_and_next_snapshot_removes_trash_item(self):
        item=identifier(8)
        response=self.client.post(f'/api/episodes/{item}/restore')
        self.assertEqual(response.json(),{'id':item,'archived':False})
        restored=next(e for e in self.client.get('/api/library').json()['episodes'] if e['id']==item)
        self.assertNotIn('archived_at',restored)
        response=self.client.delete(f'/api/episodes/{item}')
        self.assertEqual(response.json(),{'id':item,'archived':True})


if __name__=='__main__':unittest.main()
