"""One-time real reset context and three scoped source-node acknowledgements."""
from __future__ import annotations
import copy
import re
from .ros2_bridge import parse_json,encode_json
from ..platform_v2.contracts import ContractError,exact,integer,string

NODES=('armor_detector_opencv','armor_tracker','projectile_motion')
CONFIGURE_SCHEMA='polar.sim.pb-aim-source-configure.v1'
CONFIGURED_SCHEMA='polar.sim.pb-aim-source-configured.v1'

class ConfigureOnce:
    def __init__(self,run_uuid,calibration_id):
        if type(run_uuid) is not str or not re.fullmatch(r'[0-9a-f]{32}',run_uuid):raise ContractError('pb_aim_run_uuid')
        string(calibration_id,'calibration_id')
        self.run_uuid=run_uuid;self.calibration_id=calibration_id;self._packet=None;self._acked=set()

    def begin(self,context):
        if self._packet is not None:raise ContractError('pb_aim_reset_once')
        exact(context,('robot_id','episode','binding_epoch'),'pb_aim_reset_context')
        string(context['robot_id'],'robot_id');integer(context['episode'],'episode');integer(context['binding_epoch'],'binding_epoch',1)
        self._packet=dict(schema=CONFIGURE_SCHEMA,run_uuid=self.run_uuid,
            **copy.deepcopy(context),calibration_id=self.calibration_id)
        return encode_json(self._packet,1024).decode('utf-8')

    def receive(self,raw):
        if self._packet is None:raise ContractError('pb_aim_unsolicited_configure_ack')
        value=parse_json(raw,1024)
        exact(value,('schema','run_uuid','robot_id','episode','binding_epoch','calibration_id','node'),'pb_aim_configure_ack')
        if type(value['schema']) is not str or value['schema']!=CONFIGURED_SCHEMA or type(value['node']) is not str or value['node'] not in NODES:
            raise ContractError('pb_aim_configure_ack_route')
        for key in ('run_uuid','robot_id','episode','binding_epoch','calibration_id'):
            if type(value[key]) is not type(self._packet[key]) or value[key]!=self._packet[key]:
                raise ContractError('pb_aim_configure_ack_identity')
        self._acked.add(value['node'])

    @property
    def ready(self):return self._packet is not None and self._acked==set(NODES)

    @property
    def acked_nodes(self):return sorted(self._acked)
