"""Team-independent plugin graph: decision intents, navigation, camera aim.

Local manifests select processes. The HTTP catalog contains no executable,
credential, hidden state or authority; an explicit pipeline owns motion only.
"""
from __future__ import annotations
import copy
from pathlib import Path
import re
import time
from .profile import read_json_snapshot,digest
from .json_adapter import JsonLineAdapter,SharedCleanupBudget
from ..platform_v2.adapters import BaseAdapter,Registry,descriptor
from ..platform_v2.contracts import ContractError,exact,IDENTITY
from ..platform_v2.navigation_contracts import NAV_PROFILE,validate_navigation_observation

SCHEMA='polar.sim.robotio-plugins.v1'
CATALOG_SCHEMA='polar.sim.robotio-plugin-catalog.v1'

def _id(value):
    if type(value) is not str or not re.fullmatch(r'custom_[a-z0-9_]{1,100}',value):raise ContractError('robotio_custom_id_required')
    return value

def _robots(value):
    if type(value) is not list or not 1<=len(value)<=64 or any(type(r) is not str or not re.fullmatch(r'[a-z][a-z0-9_]{0,127}',r) for r in value) or len(set(value))!=len(value):
        raise ContractError('robotio_robot_scope')
    return list(value)

def load_robotio_plugins(path):
    from .navigation_plugin import load_navigation_plugins
    from .decision_plugin import load_decision_plugins
    from .aim_plugin import load_aim_plugins
    path=Path(path).absolute();value,sha=read_json_snapshot(path)
    exact(value,('schema','manifests','pipelines'),'robotio_manifest')
    if type(value['schema']) is not str or value['schema']!=SCHEMA:raise ContractError('robotio_manifest_version')
    exact(value['manifests'],('navigation','decision','aim'),'robotio_components')
    rows={};paths={};hashes={str(path):sha};ids={}
    for category,loader in (('navigation',load_navigation_plugins),('decision',load_decision_plugins),('aim',load_aim_plugins)):
        name=value['manifests'][category]
        if name is None:rows[category]=[];continue
        if type(name) is not str or not name or '\0' in name:raise ContractError('robotio_manifest_path')
        selected=(path.parent/name).resolve()
        loaded,source_sha=loader(selected);rows[category]=loaded;paths[category]=selected;hashes[str(selected)]=source_sha
        for row in loaded:
            aid=_id(row['adapter_id'])
            if aid in ids:raise ContractError('robotio_duplicate_component_id')
            ids[aid]=(category,row)
    pipelines=value['pipelines']
    if type(pipelines) is not list or len(pipelines)>16:raise ContractError('robotio_pipeline_count')
    for row in pipelines:
        exact(row,('adapter_id','label','decision_plugin_id','navigation_plugin_id','supported_robots'),'robotio_pipeline')
        aid=_id(row['adapter_id'])
        if aid in ids:raise ContractError('robotio_duplicate_pipeline_id')
        if type(row['label']) is not str or not 1<=len(row['label'])<=200:raise ContractError('robotio_pipeline_label')
        robots=_robots(row['supported_robots'])
        for key,category in (('decision_plugin_id','decision'),('navigation_plugin_id','navigation')):
            item=ids.get(_id(row[key]))
            if item is None or item[0]!=category:raise ContractError('robotio_pipeline_component_kind')
            if not set(robots)<=set(item[1]['supported_robots']):raise ContractError('robotio_pipeline_scope_exceeds_component')
        navigation=ids[row['navigation_plugin_id']][1]
        if navigation['capabilities']['goal_input_modes']!=['decision_intent_v1']:raise ContractError('robotio_pipeline_requires_goal_navigation')
        from .decision_plugin import decision_profile
        from .navigation_plugin import uses_navigation_feedback
        decision=ids[row['decision_plugin_id']][1]
        if (decision_profile(decision['capabilities'])=='own_referee_navigation_v2'
            and not uses_navigation_feedback(navigation['capabilities'])):
            raise ContractError('robotio_pipeline_requires_navigation_feedback')
        ids[aid]=('pipeline',row)
    return dict(path=path,sha=sha,rows=rows,paths=paths,hashes=hashes,pipelines=copy.deepcopy(pipelines))

class DecisionNavigationAdapter(BaseAdapter):
    """Separate reviewed decision and navigation peers, one binding/deadline."""
    def __init__(self,config,*,make_decision,make_navigation,hashes,clock=time.perf_counter,
                 decision_profile='own_referee_v1',navigation_feedback=False):
        exact(config,(),'robotio_pipeline_binding_config')
        if (type(decision_profile) is not str or decision_profile not in ('own_referee_v1','own_referee_navigation_v2')
            or type(navigation_feedback) is not bool):
            raise ContractError('robotio_pipeline_feedback_profile')
        if decision_profile=='own_referee_navigation_v2' and not navigation_feedback:
            raise ContractError('robotio_pipeline_requires_navigation_feedback')
        self.decision_profile=decision_profile;self.navigation_feedback=navigation_feedback
        self.clock=clock;self.hashes=dict(hashes);self._failed=False;self._cancelled=False
        self.decision=self.navigation=None;self._last_seq=-1;self.shutdown_status=None
        self._budget=SharedCleanupBudget()
        try:
            self.decision=make_decision();self.navigation=make_navigation()
            for peer in (self.decision,self.navigation):peer._resource_budget=self._budget
        except BaseException:
            self.close();raise
    def reset(self,context):
        if self._cancelled or self._failed:raise ContractError('robotio_pipeline_cancelled')
        try:
            super().reset(context);deadline=self.clock()+2.
            for path,sha in self.hashes.items():
                if digest(Path(path))!=sha:raise ContractError('robotio_graph_changed_after_registration')
            self.decision.reset(context,deadline=deadline)
            self.navigation.reset(context,deadline=deadline)
            if self.clock()>=deadline:raise ContractError('robotio_pipeline_reset_expired')
        except BaseException:
            self._failed=True;self.cancel();self.close();raise
    def act(self,observation):
        from ..platform_v2.decision_contracts import build_decision_observation,validate_decision_intent
        if self._cancelled or self._failed:raise ContractError('robotio_pipeline_cancelled')
        o=validate_navigation_observation(observation)
        if any(type(o[k]) is not type(v) or o[k]!=v for k,v in self.context.items()):raise ContractError('robotio_pipeline_context')
        if o['observed_seq']<=self._last_seq:raise ContractError('robotio_pipeline_replayed_observation')
        if self.clock()>=o['wall_deadline']:raise ContractError('robotio_pipeline_expired')
        try:
            feedback=self.navigation.observe(o) if self.navigation_feedback else None
            if self._cancelled or self.clock()>=o['wall_deadline']:raise ContractError('robotio_pipeline_feedback_expired')
            decision_o=build_decision_observation(o,
                feedback if self.decision_profile=='own_referee_navigation_v2' else None,
                profile=self.decision_profile)
            intent=validate_decision_intent(self.decision.act(decision_o),decision_o)
            if self._cancelled or self.clock()>=o['wall_deadline']:raise ContractError('robotio_pipeline_intent_expired')
            # Both children receive the SAME original identity and deadline.
            # No cached tactical result is relabeled onto a newer scan.
            result=self.navigation.act_with_intent(o,intent)
            if self._cancelled or self.clock()>=o['wall_deadline']:raise ContractError('robotio_pipeline_result_expired')
            self._last_seq=o['observed_seq'];return result
        except BaseException:
            self._failed=True;self.cancel();self.close();raise
    def cancel(self):
        self._cancelled=True
        for peer in (self.decision,self.navigation):
            if peer is not None:JsonLineAdapter.cancel(peer)
    def close(self):
        if self.shutdown_status is not None:
            if not self.shutdown_status.get('clean'):
                raise RuntimeError('RobotIO pipeline cleanup unproved: '+','.join(self.shutdown_status['errors']))
            return
        self.cancel();deadline=self._budget.claim();errors=[];proofs={}
        # Owned WSL peers cooperate concurrently under this same deadline.
        # Send both stop requests before waiting for either process tree;
        # navigation may need its live ROS children to cancel real goals.
        for name in ('navigation','decision'):
            peer=getattr(self,name,None)
            owner=getattr(peer,'_owned_process',None)
            request_stop=getattr(owner,'request_stop',None)
            if request_stop is None:continue
            try:
                if not callable(request_stop):raise TypeError('owned_stop_not_callable')
                if time.perf_counter()>=deadline:raise TimeoutError('original_shared_cleanup_expired')
                request_stop()
            except BaseException as exc:errors.append(name+'_stop_request:'+type(exc).__name__)
        for name in ('navigation','decision'):
            peer=getattr(self,name,None)
            if peer is None:continue
            try:peer.close(deadline=deadline)
            except BaseException as exc:errors.append(name+':'+type(exc).__name__)
            proof=copy.deepcopy(getattr(peer,'shutdown_status',None));proofs[name]=proof
            if not proof or not proof.get('clean'):errors.append(name+'_cleanup_unproved')
        self.shutdown_status=dict(clean=not errors,errors=errors,peers=proofs,resource_budget_s=1.5)
        if errors:raise RuntimeError('RobotIO pipeline cleanup unproved: '+','.join(errors))

def register_robotio_plugins(registry,path,*,clock=time.perf_counter,wsl_prepared=None):
    from .navigation_plugin import register_navigation_plugins,uses_navigation_feedback
    from .decision_plugin import DecisionPluginAdapter,decision_profile
    from .aim_plugin import register_aim_plugins
    if not isinstance(registry,Registry):raise ContractError('robotio_registration_requires_local_registry')
    graph=load_robotio_plugins(path);wsl_prepared={} if wsl_prepared is None else wsl_prepared
    catalog=registry.plugin_catalog();decision_factories={}
    existing={d['adapter_id'] for d in registry.descriptors()}
    catalog_ids={row['plugin_id'] for row in catalog}
    additions=[r['adapter_id'] for category in ('navigation','aim') for r in graph['rows'][category]]+[r['adapter_id'] for r in graph['pipelines']]
    component_ids=set(additions)|{r['adapter_id'] for r in graph['rows']['decision']}
    if (component_ids&(existing|catalog_ids) or len(existing)+len(additions)>32
        or len(catalog)+sum(len(rows) for rows in graph['rows'].values())+len(graph['pipelines'])>64):
        raise ContractError('robotio_registry_collision_or_capacity')
    # Registration is a startup transaction, never a running runtime mutation.
    # Keep the target's original frozen specs/factories/capability objects while
    # validating all new metadata in a separate registry. No factory runs here.
    staged=Registry()
    staged._specs=dict(registry._specs);staged._capabilities=dict(registry._capabilities)
    for category,rows in graph['rows'].items():
        for row in rows:
            catalog.append(dict(plugin_id=row['adapter_id'],category=category,label=row['label'],
                version='1.0.0',capabilities=copy.deepcopy(row['capabilities']),supported_robots=list(row['supported_robots']),
                transport=row['transport'],manifest_sha256=graph['hashes'][str(graph['paths'][category])],
                negotiation='exact_peer_capabilities_on_reset' if category!='aim' else 'declared_aim_contract',
                qualification='interface_not_algorithm_or_live_acceptance'))
    for category,register in (('navigation',register_navigation_plugins),('aim',register_aim_plugins)):
        if not graph['rows'][category]:continue
        result=register(staged,graph['paths'][category],clock=clock,wsl_prepared=wsl_prepared.get(category))
        if (type(result) is not dict or type(result.get('manifest_sha256')) is not str
            or result['manifest_sha256']!=graph['hashes'][str(graph['paths'][category])]):
            raise ContractError('robotio_component_changed_during_registration')
    for row in graph['rows']['decision']:
        def make(row=row):
            if row['transport']=='wsl_jsonl_v1':
                pool=wsl_prepared.get('decision')
                if pool is None:raise ContractError('wsl_plugin_requires_explicit_preparation')
                return pool.take(row['adapter_id'],graph['hashes'][str(graph['paths']['decision'])])
            return DecisionPluginAdapter({},registration=copy.deepcopy(row),manifest=graph['paths']['decision'],
                manifest_sha=graph['hashes'][str(graph['paths']['decision'])],clock=clock)
        decision_factories[row['adapter_id']]=make
    for row in graph['pipelines']:
        nav=staged.get(row['navigation_plugin_id']);make_decision=decision_factories[row['decision_plugin_id']]
        dec_row=next(r for r in graph['rows']['decision'] if r['adapter_id']==row['decision_plugin_id'])
        profile=decision_profile(dec_row['capabilities'])
        feedback=uses_navigation_feedback(nav.descriptor['navigation_plugin_capabilities'])
        def factory(config,nav=nav,make_decision=make_decision,profile=profile,feedback=feedback):
            return DecisionNavigationAdapter(config,make_decision=make_decision,make_navigation=lambda:nav.factory({}),
                hashes=graph['hashes'],clock=clock,decision_profile=profile,navigation_feedback=feedback)
        dec_ready=dec_row['transport']!='wsl_jsonl_v1' or (wsl_prepared.get('decision') is not None
            and wsl_prepared['decision'].sha==graph['hashes'][str(graph['paths']['decision'])]
            and row['decision_plugin_id'] in wsl_prepared['decision'].instances)
        ready=nav.descriptor.get('available',False) and dec_ready
        d=descriptor(row['adapter_id'],'navigation',row['label'],['pointcloud','imu'],available=ready,
            reason='available' if ready else 'explicit_local_wsl_prepare_required',
            supported_robots=list(row['supported_robots']),observation_profile=NAV_PROFILE,
            robotio_pipeline=dict(decision_plugin_id=row['decision_plugin_id'],navigation_plugin_id=row['navigation_plugin_id']),
            local_registration=True,qualification='interface_not_algorithm_or_live_acceptance')
        d.update(ui_config_contract='empty_v1',navigation_plugin_contract=NAV_PROFILE,
            reset_observation_policy='discard_reset_observation_v1',
            navigation_plugin_capabilities=copy.deepcopy(nav.descriptor['navigation_plugin_capabilities']),
            goal_input_modes=copy.deepcopy(nav.descriptor['goal_input_modes']))
        staged.register(d,factory)
        catalog.append(dict(plugin_id=row['adapter_id'],category='pipeline',label=row['label'],version='1.0.0',
            supported_robots=list(row['supported_robots']),components=copy.deepcopy(d['robotio_pipeline']),
            qualification='interface_not_algorithm_or_live_acceptance'))
    staged.set_plugin_catalog(catalog)
    # The graph, decision snapshots and re-read actuator component manifests
    # must still have the FIRST reviewed bytes immediately before publication.
    for selected,expected_sha in graph['hashes'].items():
        try:actual_sha=digest(Path(selected))
        except (OSError,ValueError):raise ContractError('robotio_graph_changed_during_registration') from None
        if actual_sha!=expected_sha:raise ContractError('robotio_graph_changed_during_registration')
    registry.__dict__.update(_specs=staged._specs,_capabilities=staged._capabilities,
        _plugin_catalog=staged._plugin_catalog)
    return dict(schema=SCHEMA,manifest_sha256=graph['sha'],registered_adapter_ids=additions,
        navigation_robots=sorted({robot for row in graph['rows']['navigation'] for robot in row['supported_robots']}),
        catalog_schema=CATALOG_SCHEMA,qualification='registration_only')

def prepare_robotio_resources(path,*,repo_root,shared_root):
    """Explicit resource-only setup before physics; no frames or warm inference."""
    graph=load_robotio_plugins(path);pools={}
    try:
        for category,rows in graph['rows'].items():
            selected=[r for r in rows if r['transport']=='wsl_jsonl_v1']
            if not selected:continue
            if category=='aim':
                from .wsl_jsonl import PreparedWslAimPlugins
                pools[category]=PreparedWslAimPlugins(graph['paths'][category],repo_root=repo_root,shared_root=Path(shared_root)/category)
            else:
                from .robotio_wsl import PreparedWslPlugins
                pools[category]=PreparedWslPlugins(selected,manifest=graph['paths'][category],
                    manifest_sha=graph['hashes'][str(graph['paths'][category])],repo_root=repo_root,shared_root=Path(shared_root)/category)
        return pools
    except BaseException as original:
        deadline=time.perf_counter()+1.5;errors=[]
        orphan=getattr(original,'resources',None)
        if orphan is not None and hasattr(orphan,'close_unclaimed'):pools['failed_preparation']=orphan
        for category,pool in pools.items():
            try:pool.close_unclaimed(deadline=deadline)
            except BaseException as exc:errors.append(category+':'+type(exc).__name__)
        if errors:
            failure=RuntimeError('RobotIO preparation cleanup unproved: '+','.join(errors))
            failure.resources=pools;raise failure from original
        raise
