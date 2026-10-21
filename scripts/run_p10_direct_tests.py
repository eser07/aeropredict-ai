"""Run ONLY GenLayer Direct Mode; disable the Studio artifact-cleanup plugin.

Requires genlayer-test==0.29.2. No deployment, wallet or paid calls.
The pinned SDK is downloaded to the selected test cache on first use.
Windows changes only stdin transport for SDK calldata (file -> pipe).
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--runtime-path",type=Path)
parser.add_argument("--cache",type=Path,required=True,help="Dedicated test cache directory; must include gltest-direct in its name")
parser.add_argument("--report",type=Path,required=True)
args=parser.parse_args()
if args.runtime_path:sys.path.insert(0,str(args.runtime_path.resolve()))
cache=args.cache.resolve()
if "gltest-direct" not in str(cache):parser.error("Cache path must contain gltest-direct for SDK test isolation")
report=args.report.resolve()
report.parent.mkdir(parents=True,exist_ok=True)
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"]="1"
import gltest.direct.sdk_loader as loader
loader.CACHE_DIR=cache
loader.get_latest_version=lambda:"v0.2.12"
if os.name=="nt":
    # Windows compatibility: feed the same SDK calldata via a pipe; no unlink-open-file.
    import gltest.direct.loader as contract_loader
    import inspect
    function_source=inspect.getsource(contract_loader._inject_message_to_fd0)
    function_source=function_source[:function_source.index('    # Create a temp file')]+'    read_fd, write_fd = os.pipe()\n    try:\n        os.write(write_fd, encoded)\n    finally:\n        os.close(write_fd)\n    vm._original_stdin_fd = os.dup(0)\n    os.dup2(read_fd, 0)\n    os.close(read_fd)\n'
    namespace={}
    exec(function_source,contract_loader.__dict__,namespace)
    contract_loader._inject_message_to_fd0=namespace['_inject_message_to_fd0']

import pytest
os.chdir(ROOT)
xml_path=report.with_suffix(".xml")
tests=["tests/test_aero_forecast.py","tests/p10_genlayer_direct_test.py","tests/p10_local_pilot_test.py","tests/p10_evidence_test.py"]
temp_dir=(cache.parent/"p10-pytest-temp").resolve()
if not temp_dir.is_relative_to(cache.parent):raise ValueError("Unsafe test temp path")
code=pytest.main(["--basetemp="+str(temp_dir),"-p","gltest.direct.pytest_plugin","-p","no:cacheprovider",*tests,"-q","--tb=short","--junitxml="+str(xml_path)])
suites=ET.parse(xml_path).getroot()
cases=list(suites.iter("testcase"))
paths=["contracts/P10ForecastVerifier.py","contracts/AeroForecastVerifier.py","contracts/BaseRpcProbe.py","scripts/p10_forecast_v2.py","tests/p10_genlayer_direct_test.py","scripts/p10_evidence.py","scripts/p10_pilot_status.py","tests/p10_evidence_test.py"]
from datetime import datetime,timezone
summary={"mode":"GenLayer Direct Mode","sdk_release":"v0.2.12","genlayer_test":"0.29.2","passed":code==0,
 "tests":len(cases),"failures":len(list(suites.iter("failure"))),"errors":len(list(suites.iter("error"))),
 "ran_at_utc":datetime.now(timezone.utc).isoformat(),"network_consensus":False,"rpc":"mocked responses only",
 "paid_transactions":0,"windows_transport_adapter":os.name=="nt",
 "source_sha256":{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in paths}}
report.write_text(json.dumps(summary,indent=2),encoding="utf-8")
raise SystemExit(code)
