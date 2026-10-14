"""Never silently relabel legacy/latest actors as the frozen v5 source."""
import json,subprocess,sys
import pytest
from rm_match.timing.aim import TimingMatchAim

@pytest.mark.parametrize('spec',[{}, {'id':'original_upstream'}, {'source_commit':'079a','sha256':{'binary':'different'}}])
def test_unqualified_actor_rejected_before_process(tmp_path,spec):
 path=tmp_path/'spec.json';path.write_text(json.dumps(spec))
 with pytest.raises(ValueError,match='exact frozen 40f7'):
  TimingMatchAim(None,path,tmp_path/'output')
 assert not (tmp_path/'output').exists()

def test_legacy_original_cli_has_clear_error():
 p=subprocess.run([sys.executable,'-m','rm_match.opening_runner','--aim','original-rmcs-stop'],capture_output=True,text=True)
 assert p.returncode==2 and 'legacy original-rmcs-stop protocol is unsupported' in p.stderr
