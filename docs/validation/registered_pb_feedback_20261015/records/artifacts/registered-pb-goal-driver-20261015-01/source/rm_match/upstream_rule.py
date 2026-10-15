"""Exact upstream rule_decide function plus explicit RMUL field configuration.

Provenance: lulunomaro/llm-RM-navigation @ 6ff95524df1a6aadce7697e366ab32ac5e9bbafc
sentry-brain/deploy/sentry_decide_server.py, blob 967e396947ab608b4e6a4aa609c79f95a6dc4c7a.
The function body below is copied byte-for-byte. RMUC 28x15 waypoints and clamp are
NOT reused: this module supplies an explicitly named RMUL 12x8 scenario profile.
No HTTP, model, credential lookup, or network fallback exists in this module.
This executes the user's original deterministic fallback, not LLM inference.
"""
import math

SOURCE_COMMIT = '6ff95524df1a6aadce7697e366ab32ac5e9bbafc'
SOURCE_BLOB = '967e396947ab608b4e6a4aa609c79f95a6dc4c7a'
FIELD_PROFILE = 'rmul2026_centered_12x8_occupation_scenario'
WAYPOINTS = {
    '红': [(-.6, -1.2, '中央控制区红方驻守点')],
    '蓝': [( .6,  1.2, '中央控制区蓝方驻守点')],
}


def clamp_point(p):
    try:
        x, y = float(p['x']), float(p['y'])
    except (TypeError, KeyError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return {'x': round(min(5.4, max(-5.4, x)), 2),
            'y': round(min(3.4, max(-3.4, y)), 2)}


def rule_decide(st, mem):
    own = st.get('own', {})
    side = '蓝' if own.get('id', 0) >= 100 else '红'
    wps = WAYPOINTS[side]
    mem.setdefault('wp_idx', 0)

    def bp():
        b = st.get('bases', {}).get('own')
        if isinstance(b, list) and len(b) == 2:
            return {'x': b[0], 'y': b[1]}
        if isinstance(b, dict):
            return {'x': b.get('x', 21.78 if side == '蓝' else 6.22), 'y': b.get('y', 7.45)}
        return {'x': 21.78 if side == '蓝' else 6.22, 'y': 7.45}

    alive = [e for e in st.get('enemies', []) if e.get('alive')]
    threats = sorted([e for e in alive if not e.get('objective') and e.get('dist', 99) <= 6],
                     key=lambda e: e.get('dist', 99))
    pos = own.get('pos', [14, 7.5])
    if own.get('hpPct', 100) < 35:
        p = clamp_point(bp())
        return {'behavior': 'RETREAT', 'target_point': {**p, 'label': '基地附近'}, 'reason': '血量过低，回防恢复'}
    if threats and own.get('hpPct', 0) > 45:
        tg = threats[0]
        d = tg.get('dist', 1) or 1
        k = max(0.0, 1 - 3.5 / d)
        p = clamp_point({'x': pos[0] + (tg['pos'][0] - pos[0]) * k, 'y': pos[1] + (tg['pos'][1] - pos[1]) * k})
        return {'behavior': 'ENGAGE', 'target_point': {**p, 'label': f"拦截{tg.get('type','敌')}"},
                'engage_target': f"{tg.get('type')}#{tg.get('id')}", 'reason': f"近距威胁 {tg.get('type')} d={tg.get('dist')}"}
    wp = wps[mem['wp_idx'] % len(wps)]
    import math
    if math.hypot(wp[0] - pos[0], wp[1] - pos[1]) < 1.2:
        mem['wp_idx'] = (mem['wp_idx'] + 1) % len(wps)
        wp = wps[mem['wp_idx'] % len(wps)]
    return {'behavior': 'PATROL', 'target_point': {'x': wp[0], 'y': wp[1], 'label': wp[2]}, 'reason': '无近距威胁，巡逻守线'}
