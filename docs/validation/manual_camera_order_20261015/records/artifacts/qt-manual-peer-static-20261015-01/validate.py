"""AST-isolated schedule/protocol bounds; no Qt, network, physics or peer run."""
import ast,copy,hashlib,io,json,threading,types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
p=ROOT/'tools/qa_qt_manual_peer.py';raw=p.read_bytes();tree=ast.parse(raw.decode('utf8'));main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
functions={n.name:n for n in main.body if isinstance(n,ast.FunctionDef)}
class NoQtImports(ast.NodeTransformer):
    def visit_ImportFrom(self,node):
        return None if node.module and node.module.startswith('PySide6') else node
def function(name,env):
    node=NoQtImports().visit(copy.deepcopy(functions[name]));m=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]));exec(compile(m,str(p),'exec'),env)
clock=[10.];events=[];state=dict(held_key=None,held_since_host_wall=None,initial_motion_stage=0)
def movement(key,pressed):
    if not pressed:events.append((key,False,clock[0]-state['held_since_host_wall']))
    else:events.append((key,True,None))
    state['held_key']=key if pressed else None;state['held_since_host_wall']=clock[0] if pressed else None
env=dict(state=state,time=types.SimpleNamespace(perf_counter=lambda:clock[0]),movement_key=movement,
    Qt=types.SimpleNamespace(Key=types.SimpleNamespace(Key_W='W',Key_S='S')))
function('drive_inputs',env);drive=env['drive_inputs']
for at in (10.,10.999,11.,11.999,12.,12.999,13.,16.):clock[0]=at;drive(at-10.)
assert [(k,b) for k,b,_ in events]==[('W',True),('W',False),('S',True),('S',False),('W',True),('W',False),('S',True)]
assert events[1][2]==1. and events[3][2]==1.
# Execute unchanged emit body wrapped in a fixture outer function so its real
# nonlocal stdout counter remains meaningful. Nothing goes to actual stdout.
node=copy.deepcopy(functions['emit']);outer=ast.FunctionDef(name='factory',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),
    body=[ast.Assign(targets=[ast.Name(id='stdout_rows',ctx=ast.Store())],value=ast.Constant(value=4095)),node,
          ast.Return(value=ast.Name(id='emit',ctx=ast.Load()))],decorator_list=[])
stream=io.BytesIO();e=dict(protocol=stream,lock=threading.RLock(),json=json)
exec(compile(ast.fix_missing_locations(ast.Module(body=[outer],type_ignores=[])),str(p),'exec'),e);emit=e['factory']()
try:emit('sdk_manual_batch')
except RuntimeError:pass
else:raise AssertionError('no reserved finished row')
emit('qt_finished',clean=False)
try:emit('qt_finished',clean=False)
except RuntimeError:pass
else:raise AssertionError('row bound ignored')
assert json.loads(stream.getvalue())=={'event':'qt_finished','clean':False}
proof=dict(ast_pass=True,source_sha256=hashlib.sha256(raw).hexdigest(),fixture='AST isolated functions only',
    schedule_original_key_holds_pass=True,first_hold_seconds=[events[1][2],events[3][2]],
    stdout4096_reserved_terminal_bound_pass=True,Qt_started=False,HTTP_started=False,physics_started=False)
(HERE/'RESULT.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf8');print(json.dumps(proof,indent=2))
