"""Export the React fixture through the real GET /api/library implementation."""
from pathlib import Path
import json
import sys
import uuid
import shutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.config import TEMP, setup_environment
from app.server import create_app
from fastapi.testclient import TestClient
from tests.library_contract_fixture import build_library


if __name__=='__main__':
    setup_environment()
    directory=TEMP/('react-library-contract-'+uuid.uuid4().hex)
    directory.mkdir(parents=True)
    try:
        manager,_=build_library(directory)
        with TestClient(create_app(manager),base_url='http://127.0.0.1') as client:
            response=client.get('/api/library');response.raise_for_status()
            snapshot=response.json()
    finally:
        directory.resolve().relative_to(TEMP.resolve())
        shutil.rmtree(directory)
    output=ROOT/'frontend/src/test/fixtures/library.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Exported real Library.snapshot: projects=3 episodes=7 job_refs=6')
