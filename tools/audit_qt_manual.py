"""Independent original-window/manual batch receipt join; no physics or IO."""
from __future__ import annotations
import math

CHANNELS=('motion','gimbal','fire')
def same(a,b):return type(a) is type(b) and a==b

def audit(rows,robot_id='red_infantry'):
    errors=[];batches={};positive=set();negative=set();gimbal=set();consumed=set();used=set()
    def reject(message):
        if len(errors)<64:errors.append(message)
    for index,row in enumerate(rows):
        if row.get('event')!='sdk_manual_batch':continue
        try:
            if set(row)!={'event','robot_id','window','request','ack','entered_host_wall','returned_host_wall'} or row['robot_id']!=robot_id:raise ValueError('event')
            w=row['window'];p=row['request'];ack=row['ack']
            if set(p)!={'robot_id','lease_epochs','window_id','valid_for_s','adapter_inputs','controls'}:raise ValueError('request_fields')
            if set(ack)!={'schema','accepted','robot_id','lease_epochs','window_id','batch_version','adapter_inputs','controls'}:raise ValueError('ack_fields')
            if w['robot_id']!=robot_id or p['robot_id']!=robot_id or ack['robot_id']!=robot_id or ack['accepted'] is not True or not same(ack['batch_version'],1):raise ValueError('identity')
            if ack['schema']!='rm.sim.platform.v2' or p['adapter_inputs']!=[] or ack['adapter_inputs']!=[]:raise ValueError('manual_only')
            if (type(p['lease_epochs']) is not dict or set(p['lease_epochs'])!=set(CHANNELS)
                or any(type(epoch) is not int or epoch<=0 or not same(epoch,w['lease_epochs'].get(c)) or not same(epoch,ack['lease_epochs'].get(c)) for c,epoch in p['lease_epochs'].items())):raise ValueError('epochs')
            if type(p['window_id']) is not int or p['window_id']<=0 or not same(p['window_id'],w['window_id']) or not same(p['window_id'],ack['window_id']):raise ValueError('window')
            if type(p['valid_for_s']) not in (float,int) or not 0<p['valid_for_s']<=.15 or not 0<w['valid_for_s']<=.15 or abs(w['expires_wall']-w['issued_wall']-w['valid_for_s'])>1e-6:raise ValueError('duration')
            start=row['entered_host_wall'];end=row['returned_host_wall']
            if not all(type(v) in (float,int) and math.isfinite(v) for v in (start,end)) or not start<=end<w['expires_wall']:raise ValueError('host_QPC_interval')
            if type(p['controls']) is not list or type(ack['controls']) is not list or len(p['controls'])!=3 or len(ack['controls'])!=3:raise ValueError('complete_controls')
            channels=set()
            for command,reply in zip(p['controls'],ack['controls']):
                if set(command)!={'channel','lease_epoch','seq','value'} or set(reply)!={'accepted','robot_id','channel','lease_epoch','seq','window_id','input_expires'}:raise ValueError('member_fields')
                c=command['channel'];epoch=command['lease_epoch'];seq=command['seq']
                if c not in CHANNELS or c in channels or type(seq) is not int or seq<0 or not same(epoch,p['lease_epochs'][c]):raise ValueError('member_identity')
                channels.add(c)
                if reply['accepted'] is not True or reply['robot_id']!=robot_id or any(not same(reply[k],v) for k,v in dict(channel=c,lease_epoch=epoch,seq=seq,window_id=p['window_id']).items()):raise ValueError('member_ACK_identity')
                expires=reply['input_expires']
                if type(expires) not in (float,int) or not math.isfinite(expires) or not w['issued_wall']<expires<=w['expires_wall'] or end>=expires:raise ValueError('member_ACK_expired')
                key=(c,epoch,seq)
                if key in batches:raise ValueError('duplicate_member')
                batches[key]=dict(value=command['value'],expires=expires,window=w,window_id=p['window_id'],batch_index=index)
            if channels!=set(CHANNELS):raise ValueError('coverage')
        except (KeyError,TypeError,ValueError,OverflowError) as exc:reject('batch:'+str(index)+':'+str(exc))
    for index,row in enumerate(rows):
        if row.get('event')!='actuator_consumed' or row.get('robot_id')!=robot_id or row.get('phase')!='integration_entry':continue
        try:
            if any(value.get('owner') is not None for value in row['adapter_authorizations'].values()):raise ValueError('adapter_bound_in_manual_receipt')
            if row['target']['motion'] is None:continue
            for c in CHANNELS:
                entry=row['manual_inputs'][c]
                if not all(type(entry[k]) is int for k in ('epoch','seq','input_window_id')):raise ValueError('receipt_typed_identity')
                key=(c,entry['epoch'],entry['seq']);source=batches.get(key)
                if source is None:raise ValueError('no_original_batch')
                if entry['owner']!=source['window']['session_id'] or not same(entry['input_window_id'],source['window_id']):raise ValueError('receipt_owner_window')
                wall=row['consume_wall']
                if not wall<min(source['expires'],entry['expires'],entry['input_expires'],entry['input_window_deadline'],source['window']['expires_wall']):raise ValueError('receipt_expired')
                value=row['target'][c]
                expected=source['value']['fire'] if c=='fire' else source['value']
                if type(value) is not type(expected) or value!=expected:raise ValueError('receipt_value')
                used.add(source['batch_index'])
            step=round(row['consume_sim_time']/.002);consumed.add(step)
            velocity=row['target']['motion']['vx_mps']
            if velocity>0:positive.add(step)
            if velocity<0:negative.add(step)
            if any(abs(row['target']['gimbal'][k])>1e-8 for k in ('yaw_rad','pitch_rad')):gimbal.add(step)
        except (KeyError,TypeError,ValueError,OverflowError) as exc:reject('receipt:'+str(index)+':'+str(exc))
    return dict(errors=errors,manual_batch_count=len({v['batch_index'] for v in batches.values()}),
        physically_consumed_batches=len(used),physical_steps=len(consumed),positive_x_steps=len(positive),
        negative_x_steps=len(negative),nonzero_gimbal_steps=len(gimbal),
        qualification='exact original manual SDK window/lease/seq/value/expiry join; no algorithm or full match')
