"""Explicit offline native wrapper; no live wall deadline is extended/reused."""
import math
from .native_adapter import NativeSourceAdapter
from .offline_contract import validate_offline_observation,offline_action,validate_offline_action
from .contracts import ContractError

class OfflineNativeAdapter(NativeSourceAdapter):
 def act(self,o):
  o=validate_offline_observation(o)
  if any(o[k]!=self.context[k] for k in self.context):raise ContractError('offline_context_mismatch')
  # Native control evaluates at modeled result time, using the explicitly
  # earlier controller own sample. Camera exposure pose is independent.
  sensor=dict(o,sim_time=o['schedule']['result_available_ns']/1e9)
  def hold():
   q=o['own']['qpos']
   return offline_action(o,dict(frame='base_link',yaw_rad=math.atan2(math.sin(q[3]),math.cos(q[3])),pitch_rad=max(-math.pi/2,min(math.pi/2,q[4])),active=False,confidence=None,fire_permission=False))
  return validate_offline_action(self._act_sensor(sensor,hold,lambda c:offline_action(o,c)),o)
