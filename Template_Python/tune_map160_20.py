import json
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(r"C:\Simulator")
BOT_DIR = ROOT / "Template_Python" / "Bot_Python"
TEMPLATE = BOT_DIR / "v2.py"
PYTHON = ROOT / "Template_Python" / ".venv" / "Scripts" / "python.exe"
BENCHMARK = ROOT / "Template_Python" / "benchmark_bot.py"
SETTINGS = Path(r"C:\Users\SSAFY\Documents\AirSim\settings.json")
SUMMARY = ROOT / "Template_Python" / "map160_tuning_summary_20.json"
SELECTED = BOT_DIR / "v2_map160_best.py"
FASTEST = BOT_DIR / "v2_map160_fastest.py"

MAP_ID = "160"
PREVIOUS_BEST_TIME = 134.73448181152344
PREVIOUS_BEST_PENALTY = 22
PENALTY_WEIGHT = 0.12


def replace_once(text, old, new, name):
    if old not in text:
        raise RuntimeError(f"Pattern not found for {name}: {old}")
    return text.replace(old, new, 1)


def set_map(map_id):
    settings = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    settings.setdefault("Algo", {})["Map"] = str(map_id)
    settings["ControlMode"] = "Code"
    SETTINGS.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_old_candidates():
    for path in BOT_DIR.glob("v2_map160_c*.py"):
        path.unlink()


def build_candidate(name, params):
    text = TEMPLATE.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "self.accident_count = 0",
        "self.accident_count = 0\n        self.prev_steering = 0.0",
        name,
    )
    text = replace_once(
        text,
        "angle_num = int(sensing_info.speed / 45)",
        f"angle_num = int(sensing_info.speed / {params['angle_div']})",
        name,
    )
    text = replace_once(
        text,
        "middle_add = (sensing_info.to_middle / 80) * -1",
        f"middle_add = (sensing_info.to_middle / {params['middle_den']}) * -1",
        name,
    )
    text = replace_once(
        text,
        "steer_factor = sensing_info.speed * 0.85",
        f"steer_factor = sensing_info.speed * {params['steer_mid']}",
        name,
    )
    text = replace_once(
        text,
        "steer_factor = sensing_info.speed * 0.7",
        f"steer_factor = sensing_info.speed * {params['steer_high']}",
        name,
    )
    text = replace_once(
        text,
        "look_ahead = int(sensing_info.speed / 30) + 1",
        f"look_ahead = int(sensing_info.speed / {params['look_div']}) + 1",
        name,
    )
    text = replace_once(
        text,
        "look_ahead = self._clamp(look_ahead, 1, min(6, len(sensing_info.track_forward_angles)))",
        f"look_ahead = self._clamp(look_ahead, 1, min({params['look_cap']}, len(sensing_info.track_forward_angles)))",
        name,
    )

    speeds = params["speeds"]
    for old, new in zip(
        ["170", "145", "120", "95", "75", "55"],
        [str(value) for value in speeds],
    ):
        text = replace_once(text, f"target_speed = {old}", f"target_speed = {new}", name)

    thresholds = params["gap_thresholds"]
    text = replace_once(text, "if speed_gap > 35:", f"if speed_gap > {thresholds[0]}:", name)
    text = replace_once(text, "elif speed_gap > 25:", f"elif speed_gap > {thresholds[1]}:", name)
    text = replace_once(text, "elif speed_gap > 15:", f"elif speed_gap > {thresholds[2]}:", name)
    text = replace_once(text, "elif speed_gap > 5:", f"elif speed_gap > {thresholds[3]}:", name)

    text = replace_once(
        text,
        "if sensing_info.speed < 60 and max_curve < 60:",
        f"if sensing_info.speed < {params['launch_speed']} and max_curve < {params['launch_curve']}:",
        name,
    )

    old_hairpin = """        if max_curve > 80:
            if set_steering > 0:
                set_steering += 0.25
            else:
                set_steering -= 0.25
"""
    new_hairpin = f"""        if max_curve > {params['hairpin_threshold']}:
            if set_steering > 0:
                set_steering += {params['hairpin_boost']}
            else:
                set_steering -= {params['hairpin_boost']}

        edge_ratio = abs(sensing_info.to_middle) / max(half_road_width, 0.001)
        if edge_ratio > {params['edge_start']}:
            edge_strength = min(1.0, (edge_ratio - {params['edge_start']}) / max(1.0 - {params['edge_start']}, 0.001))
            center_dir = -1.0 if sensing_info.to_middle > 0 else 1.0
            set_steering += center_dir * {params['edge_gain']} * edge_strength
            if sensing_info.speed > {params['edge_speed']}:
                set_throttle = min(set_throttle, {params['edge_throttle']})
                set_brake = max(set_brake, {params['edge_brake']})
"""
    text = replace_once(text, old_hairpin, new_hairpin, name)

    if params["smoothing"] > 0:
        text = replace_once(
            text,
            "        set_steering = self._clamp(set_steering, -1.0, 1.0)",
            f"""        if self.is_accident is False:
            set_steering = (self.prev_steering * {params['smoothing']}) + (set_steering * {1.0 - params['smoothing']})
            self.prev_steering = set_steering

        set_steering = self._clamp(set_steering, -1.0, 1.0)""",
            name,
        )

    path = BOT_DIR / f"{name}.py"
    path.write_text(text, encoding="utf-8")
    return path


def parse_json_output(output, name):
    for idx, char in enumerate(output):
        if char != "{":
            continue
        try:
            return json.loads(output[idx:])
        except json.JSONDecodeError:
            continue
    return {
        "name": name,
        "completed": False,
        "race_time": None,
        "error": "benchmark did not return JSON",
        "output_tail": output[-4000:],
    }


def run_candidate(path, name):
    proc = subprocess.run(
        [str(PYTHON), str(BENCHMARK), str(path), "--name", name, "--timeout", "340"],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=540,
    )
    result = parse_json_output(proc.stdout.strip(), name)
    result["returncode"] = proc.returncode
    return result


def score(result):
    race_time = result.get("race_time")
    penalties = result.get("penalty_count")
    if race_time is None or penalties is None:
        return None
    return race_time + (penalties * PENALTY_WEIGHT)


def write_summary(results, candidates, selected=None, fastest=None):
    ranked_by_time = sorted(
        [result for result in results if result.get("race_time") is not None],
        key=lambda result: result["race_time"],
    )
    ranked_by_score = sorted(
        [result for result in results if result.get("score") is not None],
        key=lambda result: result["score"],
    )
    SUMMARY.write_text(
        json.dumps(
            {
                "map_id": MAP_ID,
                "previous_best": {
                    "name": "v2_10_c10_soft_hairpin",
                    "race_time": PREVIOUS_BEST_TIME,
                    "penalty_count": PREVIOUS_BEST_PENALTY,
                    "score": PREVIOUS_BEST_TIME + (PREVIOUS_BEST_PENALTY * PENALTY_WEIGHT),
                },
                "penalty_weight": PENALTY_WEIGHT,
                "selected": selected,
                "fastest": fastest,
                "ranking_by_score": ranked_by_score,
                "ranking_by_time": ranked_by_time,
                "candidates": candidates,
                "results": results,
                "updated_at_epoch": time.time(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def candidates():
    base = {
        "angle_div": 45,
        "middle_den": 95,
        "steer_mid": 0.85,
        "steer_high": 0.70,
        "look_div": 30,
        "look_cap": 6,
        "speeds": [170, 145, 120, 95, 75, 55],
        "gap_thresholds": [35, 25, 15, 5],
        "launch_speed": 55,
        "launch_curve": 50,
        "hairpin_threshold": 80,
        "hairpin_boost": 0.18,
        "edge_start": 0.68,
        "edge_gain": 0.16,
        "edge_speed": 105,
        "edge_throttle": 0.75,
        "edge_brake": 0.08,
        "smoothing": 0.0,
    }

    variants = [
        ("v2_map160_c01_c10_edge_light", {"middle_den": 80, "hairpin_boost": 0.18, "edge_start": 0.72, "edge_gain": 0.12}),
        ("v2_map160_c02_c10_edge_med", {"middle_den": 80, "hairpin_boost": 0.18, "edge_start": 0.66, "edge_gain": 0.18, "edge_brake": 0.10}),
        ("v2_map160_c03_c09_edge_med", {"middle_den": 90, "hairpin_boost": 0.25, "edge_start": 0.66, "edge_gain": 0.18, "edge_brake": 0.10}),
        ("v2_map160_c04_soft_center_edge", {"middle_den": 105, "hairpin_boost": 0.18, "edge_start": 0.62, "edge_gain": 0.22, "edge_brake": 0.14}),
        ("v2_map160_c05_more_lookahead", {"middle_den": 95, "look_div": 26, "look_cap": 7, "hairpin_boost": 0.16, "edge_start": 0.64, "edge_gain": 0.18}),
        ("v2_map160_c06_more_lookahead_safe", {"look_div": 24, "look_cap": 7, "speeds": [165, 140, 112, 84, 62, 44], "gap_thresholds": [31, 22, 12, 4], "hairpin_boost": 0.14, "edge_start": 0.60, "edge_gain": 0.24, "edge_brake": 0.18}),
        ("v2_map160_c07_safe_speeds", {"speeds": [165, 140, 112, 84, 62, 44], "gap_thresholds": [31, 22, 12, 4], "hairpin_boost": 0.18, "edge_start": 0.62, "edge_gain": 0.20, "edge_brake": 0.14}),
        ("v2_map160_c08_very_safe_speeds", {"speeds": [160, 135, 106, 78, 58, 40], "gap_thresholds": [29, 20, 10, 3], "look_div": 26, "look_cap": 7, "hairpin_boost": 0.12, "edge_start": 0.58, "edge_gain": 0.28, "edge_brake": 0.22, "edge_throttle": 0.55}),
        ("v2_map160_c09_late_brake_guard", {"middle_den": 95, "gap_thresholds": [38, 28, 17, 6], "hairpin_boost": 0.16, "edge_start": 0.62, "edge_gain": 0.24, "edge_brake": 0.18, "edge_throttle": 0.65}),
        ("v2_map160_c10_early_brake_soft", {"middle_den": 100, "gap_thresholds": [30, 22, 12, 4], "hairpin_boost": 0.15, "edge_start": 0.64, "edge_gain": 0.18, "smoothing": 0.12}),
        ("v2_map160_c11_early_angle", {"angle_div": 38, "middle_den": 95, "look_div": 28, "look_cap": 7, "hairpin_boost": 0.14, "edge_start": 0.64, "edge_gain": 0.18}),
        ("v2_map160_c12_early_angle_safe", {"angle_div": 36, "middle_den": 105, "look_div": 26, "look_cap": 7, "speeds": [165, 140, 112, 84, 62, 44], "gap_thresholds": [31, 22, 12, 4], "hairpin_boost": 0.12, "edge_start": 0.60, "edge_gain": 0.24, "edge_brake": 0.18}),
        ("v2_map160_c13_less_high_steer", {"steer_mid": 0.90, "steer_high": 0.76, "middle_den": 95, "hairpin_boost": 0.16, "edge_start": 0.62, "edge_gain": 0.20, "edge_brake": 0.14}),
        ("v2_map160_c14_more_high_steer_guard", {"steer_mid": 0.82, "steer_high": 0.68, "middle_den": 110, "hairpin_boost": 0.12, "edge_start": 0.60, "edge_gain": 0.28, "edge_brake": 0.20, "edge_throttle": 0.60}),
        ("v2_map160_c15_smoothing_light", {"middle_den": 95, "hairpin_boost": 0.16, "edge_start": 0.64, "edge_gain": 0.20, "smoothing": 0.10}),
        ("v2_map160_c16_smoothing_med", {"middle_den": 105, "look_div": 28, "look_cap": 7, "speeds": [168, 142, 115, 88, 66, 48], "hairpin_boost": 0.14, "edge_start": 0.62, "edge_gain": 0.22, "edge_brake": 0.14, "smoothing": 0.18}),
        ("v2_map160_c17_smooth_safe", {"middle_den": 110, "look_div": 26, "look_cap": 7, "speeds": [162, 136, 108, 80, 60, 42], "gap_thresholds": [30, 21, 11, 4], "hairpin_boost": 0.10, "edge_start": 0.58, "edge_gain": 0.30, "edge_brake": 0.24, "edge_throttle": 0.55, "smoothing": 0.20}),
        ("v2_map160_c18_fast_with_guard", {"middle_den": 90, "speeds": [172, 146, 120, 92, 70, 50], "gap_thresholds": [36, 26, 16, 5], "hairpin_boost": 0.15, "edge_start": 0.60, "edge_gain": 0.26, "edge_brake": 0.18, "edge_throttle": 0.62}),
        ("v2_map160_c19_lane_guard_strong", {"middle_den": 115, "look_div": 28, "look_cap": 7, "speeds": [168, 142, 114, 86, 64, 46], "gap_thresholds": [30, 22, 12, 4], "hairpin_boost": 0.12, "edge_start": 0.55, "edge_gain": 0.34, "edge_brake": 0.28, "edge_throttle": 0.50, "smoothing": 0.12}),
        ("v2_map160_c20_lane_guard_balanced", {"middle_den": 105, "look_div": 28, "look_cap": 7, "speeds": [170, 142, 116, 88, 66, 48], "gap_thresholds": [32, 24, 14, 5], "hairpin_boost": 0.12, "edge_start": 0.58, "edge_gain": 0.28, "edge_brake": 0.20, "edge_throttle": 0.58, "smoothing": 0.08}),
    ]

    built = []
    for name, overrides in variants:
        params = {**base, **overrides}
        built.append((name, params))
    return built


def main():
    original_settings = SETTINGS.read_text(encoding="utf-8-sig")
    candidate_defs = candidates()
    results = []
    write_summary(results, [{"name": name, "params": params} for name, params in candidate_defs])

    try:
        cleanup_old_candidates()
        set_map(MAP_ID)
        for index, (name, params) in enumerate(candidate_defs, start=1):
            path = build_candidate(name, params)
            print(f"[{index}/{len(candidate_defs)}] start: {name}", flush=True)
            result = run_candidate(path, name)
            race_time = result.get("race_time")
            result.update(
                {
                    "model": name,
                    "bot_file": str(path),
                    "map_id": MAP_ID,
                    "params": params,
                    "score": score(result),
                    "delta_vs_previous_best": (race_time - PREVIOUS_BEST_TIME) if race_time is not None else None,
                }
            )
            results.append(result)
            write_summary(results, [{"name": n, "params": p} for n, p in candidate_defs])
            print(
                f"[{index}/{len(candidate_defs)}] done: {name}, completed={result.get('completed')}, "
                f"race_time={result.get('race_time')}, penalties={result.get('penalty_count')}, "
                f"score={result.get('score')}",
                flush=True,
            )
    finally:
        SETTINGS.write_text(original_settings, encoding="utf-8")

    completed = [result for result in results if result.get("completed") and result.get("race_time") is not None]
    fastest = min(completed, key=lambda result: result["race_time"], default=None)
    selected = min(completed, key=lambda result: result["score"], default=None)

    if fastest:
        shutil.copyfile(fastest["bot_file"], FASTEST)
    if selected:
        shutil.copyfile(selected["bot_file"], SELECTED)

    write_summary(results, [{"name": n, "params": p} for n, p in candidate_defs], selected, fastest)
    print(SUMMARY.read_text(encoding="utf-8"), flush=True)


if __name__ == "__main__":
    main()
