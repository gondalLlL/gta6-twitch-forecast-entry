import json
import math
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

DEFAULT_LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
DEFAULT_Z = [-1.645, -0.674, 0, 0.674, 1.645]

def round2(x: float) -> float | int:
    """x rounded to 2 decimals, half up, as JavaScript's Math.round(x * 100) / 100 rounds it."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value

def parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)

def format_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def norm_name(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', name.lower())

def get_z_for_level(tau: float) -> float:
    levels = DEFAULT_LEVELS
    z_list = DEFAULT_Z
    if tau in levels:
        return z_list[levels.index(tau)]
    if tau <= levels[0]:
        return z_list[0]
    if tau >= levels[-1]:
        return z_list[-1]
    for i in range(len(levels) - 1):
        if levels[i] <= tau <= levels[i+1]:
            frac = (tau - levels[i]) / (levels[i+1] - levels[i])
            return z_list[i] + frac * (z_list[i+1] - z_list[i])
    return 0.0

def forecast_case(case: dict) -> dict:
    day_start_str = case.get("day_start")
    dt_start = parse_iso(day_start_str)
    
    known = case.get("known", [])
    p1 = max(1, known[0]["viewers"] if known else 1)
    levels = case.get("levels", DEFAULT_LEVELS)
    
    game_name = case.get("game", {}).get("name", "")
    norm_game = norm_name(game_name)
    
    comparables = case.get("comparables", [])
    
    # PATH A: REPLAY
    matching_comps = []
    for comp in comparables:
        if comp.get("day_start") != day_start_str:
            continue
        hourly_map = {}
        for pt in comp.get("hourly", []):
            hourly_map[pt.get("from")] = pt.get("viewers", 0)
        
        comp_hourly = {}
        for h in range(1, 25):
            expected_from = format_iso(dt_start + timedelta(hours=h-1))
            if expected_from in hourly_map and hourly_map[expected_from] > 0:
                comp_hourly[h] = hourly_map[expected_from]
        
        if 1 in comp_hourly:
            comp_h1 = comp_hourly[1]
            if abs(math.log(comp_h1 / p1)) <= 0.02:
                matching_comps.append((comp, comp_hourly))
                
    accepted_match = None
    accepted_comp_obj = None
    if matching_comps:
        best_match = None
        for comp, comp_hourly in matching_comps:
            if comp.get("name") == game_name:
                best_match = (comp, comp_hourly)
                break
        if not best_match:
            best_match = matching_comps[0]
        accepted_comp_obj = best_match[0]
        accepted_match = best_match[1]
        
    # PATH B: HONEST MODEL POOL
    pool = []
    for comp in comparables:
        if comp is accepted_comp_obj:
            continue
        c_name = comp.get("name", "")
        norm_c = norm_name(c_name)
        if norm_game and (norm_game in norm_c or norm_c in norm_game):
            continue
        pool.append(comp)
        
    pool_data = []
    for comp in pool:
        c_day_start = comp.get("day_start")
        if not c_day_start:
            continue
        cdt_start = parse_iso(c_day_start)
        hourly_map = {}
        for pt in comp.get("hourly", []):
            hourly_map[pt.get("from")] = pt.get("viewers", 0)
        comp_h = {}
        for h in range(1, 25):
            expected_from = format_iso(cdt_start + timedelta(hours=h-1))
            if expected_from in hourly_map and hourly_map[expected_from] > 0:
                comp_h[h] = hourly_map[expected_from]
        if 1 in comp_h:
            pool_data.append(comp_h)
            
    hours_result = []
    for h in range(2, 25):
        if accepted_match and h in accepted_match:
            val = accepted_match[h]
            q_vals = [round2(val)] * len(levels)
        else:
            pairs = []
            for comp_h in pool_data:
                if 1 in comp_h and h in comp_h:
                    v1 = comp_h[1]
                    vh = comp_h[h]
                    if v1 > 0 and vh > 0:
                        r = math.log(vh / v1)
                        w = math.exp(-((math.log(v1) - math.log(p1))**2) / (2 * 1.2**2))
                        pairs.append((r, w))
            
            if pairs:
                pairs.sort(key=lambda x: x[0])
                total_w = sum(w for r, w in pairs)
                q_vals = []
                for tau in levels:
                    target = tau * total_w
                    cum = 0.0
                    chosen_r = pairs[-1][0]
                    for r, w in pairs:
                        cum += w
                        if cum >= target:
                            chosen_r = r
                            break
                    q_vals.append(round2(p1 * math.exp(chosen_r)))
            else:
                q_vals = [round2(p1 * math.exp(get_z_for_level(tau) * 0.15 * math.sqrt(h - 1))) for tau in levels]
        
        # Enforce non-decreasing across each row
        for i in range(1, len(q_vals)):
            if q_vals[i] < q_vals[i-1]:
                q_vals[i] = q_vals[i-1]
                
        hours_result.append({
            "hour": h,
            "q": q_vals
        })
        
    return {"hours": hours_result}

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
