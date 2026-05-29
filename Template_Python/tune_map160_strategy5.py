import json
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(r"C:\Simulator")
BOT_DIR = ROOT / "Template_Python" / "Bot_Python"
BASE_MODEL = BOT_DIR / "v2_map160_best.py"
PYTHON = ROOT / "Template_Python" / ".venv" / "Scripts" / "python.exe"
BENCHMARK = ROOT / "Template_Python" / "benchmark_bot.py"
SETTINGS = Path(r"C:\Users\SSAFY\Documents\AirSim\settings.json")
SUMMARY = ROOT / "Template_Python" / "map160_strategy5_late_summary.json"
BEST = BOT_DIR / "v2_map160_strategy_late_best.py"
FASTEST = BOT_DIR / "v2_map160_strategy_late_fastest.py"

MAP_ID = "160"
PENALTY_WEIGHT = 0.12


def set_map(map_id):
    settings = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    settings.setdefault("Algo", {})["Map"] = str(map_id)
    settings["ControlMode"] = "Code"
    SETTINGS.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def replace_once(text, old, new, name):
    if old not in text:
        raise RuntimeError(f"Pattern not found for {name}: {old}")
    return text.replace(old, new, 1)


def make_candidate(name, speed_profile, brake_profile):
    text = BASE_MODEL.read_text(encoding="utf-8")

    text = replace_once(text, "target_speed = 170", "target_speed = 190", name)
    text = replace_once(text, "target_speed = 145", "target_speed = 155", name)

    insert_at = """        else:
            target_speed = 55

        speed_gap = sensing_info.speed - target_speed
"""
    hairpin_logic = f"""        else:
            target_speed = 55

        hairpin_name = None
        hairpin_target_speed = None
        lap_progress = sensing_info.lap_progress % 100.0

        # Map 160 hairpin zones from waypoint curvature clustering.
        # Difficulty: hairpin 2 > hairpin 4 > hairpin 1 == hairpin 3.
        if 16.8 <= lap_progress <= 21.8:
            hairpin_name = "hp2"
            hairpin_target_speed = {speed_profile["hp2"]}
        elif 44.5 <= lap_progress <= 49.2:
            hairpin_name = "hp1"
            hairpin_target_speed = {speed_profile["hp13"]}
        elif 60.8 <= lap_progress <= 65.8:
            hairpin_name = "hp3"
            hairpin_target_speed = {speed_profile["hp13"]}
        elif 82.0 <= lap_progress <= 92.5:
            hairpin_name = "hp4"
            hairpin_target_speed = {speed_profile["hp4"]}

        if hairpin_target_speed is not None:
            target_speed = hairpin_target_speed

        speed_gap = sensing_info.speed - target_speed
"""
    text = replace_once(text, insert_at, hairpin_logic, name)

    text = replace_once(
        text,
        "if sensing_info.speed < 55 and max_curve < 50:",
        "if hairpin_target_speed is None and sensing_info.speed < 55 and max_curve < 50:",
        name,
    )

    after_launch = """        if hairpin_target_speed is None and sensing_info.speed < 55 and max_curve < 50:
            set_throttle = 1.0
            set_brake = 0.0

"""
    hairpin_brake = f"""        if hairpin_target_speed is None and sensing_info.speed < 55 and max_curve < 50:
            set_throttle = 1.0
            set_brake = 0.0

        if hairpin_target_speed is not None:
            hairpin_gap = sensing_info.speed - hairpin_target_speed
            if hairpin_gap > {brake_profile["hard_gap"]}:
                set_throttle = min(set_throttle, {brake_profile["hard_throttle"]})
                set_brake = max(set_brake, {brake_profile["hard_brake"]})
            elif hairpin_gap > {brake_profile["mid_gap"]}:
                set_throttle = min(set_throttle, {brake_profile["mid_throttle"]})
                set_brake = max(set_brake, {brake_profile["mid_brake"]})
            elif hairpin_gap > {brake_profile["soft_gap"]}:
                set_throttle = min(set_throttle, {brake_profile["soft_throttle"]})
                set_brake = max(set_brake, {brake_profile["soft_brake"]})

"""
    text = replace_once(text, after_launch, hairpin_brake, name)

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
    if result.get("race_time") is None or result.get("penalty_count") is None:
        return None
    return result["race_time"] + (result["penalty_count"] * PENALTY_WEIGHT)


def write_summary(results, candidates, selected=None, fastest=None):
    scored = [r for r in results if r.get("score") is not None]
    timed = [r for r in results if r.get("race_time") is not None]
    SUMMARY.write_text(
        json.dumps(
            {
                "map_id": MAP_ID,
                "strategy": {
                    "straight_target_speed": 190,
                    "difficulty": "hp2 > hp4 > hp1 == hp3",
                    "hairpin_progress_ranges": {
                        "hp2": [16.8, 21.8],
                        "hp1": [44.5, 49.2],
                        "hp3": [60.8, 65.8],
                        "hp4": [82.0, 92.5],
                    },
                },
                "penalty_weight": PENALTY_WEIGHT,
                "selected": selected,
                "fastest": fastest,
                "ranking_by_score": sorted(scored, key=lambda r: r["score"]),
                "ranking_by_time": sorted(timed, key=lambda r: r["race_time"]),
                "candidates": candidates,
                "results": results,
                "updated_at_epoch": time.time(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def candidate_defs():
    levels = [
        ("v2_map160_strategy_late_l1_light", {"hp2": 90, "hp4": 96, "hp13": 104}),
        ("v2_map160_strategy_late_l2_mild", {"hp2": 82, "hp4": 90, "hp13": 98}),
        ("v2_map160_strategy_late_l3_balanced", {"hp2": 74, "hp4": 82, "hp13": 92}),
        ("v2_map160_strategy_late_l4_safe", {"hp2": 66, "hp4": 74, "hp13": 84}),
        ("v2_map160_strategy_late_l5_strong", {"hp2": 58, "hp4": 66, "hp13": 76}),
    ]
    brakes = [
        {"hard_gap": 40, "hard_throttle": 0.22, "hard_brake": 0.65, "mid_gap": 28, "mid_throttle": 0.42, "mid_brake": 0.35, "soft_gap": 14, "soft_throttle": 0.72, "soft_brake": 0.12},
        {"hard_gap": 34, "hard_throttle": 0.18, "hard_brake": 0.75, "mid_gap": 24, "mid_throttle": 0.36, "mid_brake": 0.45, "soft_gap": 12, "soft_throttle": 0.66, "soft_brake": 0.18},
        {"hard_gap": 28, "hard_throttle": 0.14, "hard_brake": 0.85, "mid_gap": 20, "mid_throttle": 0.30, "mid_brake": 0.55, "soft_gap": 10, "soft_throttle": 0.58, "soft_brake": 0.24},
        {"hard_gap": 24, "hard_throttle": 0.10, "hard_brake": 0.95, "mid_gap": 16, "mid_throttle": 0.24, "mid_brake": 0.68, "soft_gap": 8, "soft_throttle": 0.50, "soft_brake": 0.32},
        {"hard_gap": 20, "hard_throttle": 0.06, "hard_brake": 1.00, "mid_gap": 13, "mid_throttle": 0.18, "mid_brake": 0.80, "soft_gap": 6, "soft_throttle": 0.42, "soft_brake": 0.42},
    ]
    return [
        {"name": name, "speed_profile": speed_profile, "brake_profile": brake_profile}
        for (name, speed_profile), brake_profile in zip(levels, brakes)
    ]


def main():
    original_settings = SETTINGS.read_text(encoding="utf-8-sig")
    candidates = candidate_defs()
    results = []
    write_summary(results, candidates)

    try:
        set_map(MAP_ID)
        for index, candidate in enumerate(candidates, start=1):
            path = make_candidate(candidate["name"], candidate["speed_profile"], candidate["brake_profile"])
            print(f"[{index}/{len(candidates)}] start: {candidate['name']}", flush=True)
            result = run_candidate(path, candidate["name"])
            result.update(
                {
                    "model": candidate["name"],
                    "bot_file": str(path),
                    "map_id": MAP_ID,
                    "speed_profile": candidate["speed_profile"],
                    "brake_profile": candidate["brake_profile"],
                    "score": score(result),
                }
            )
            results.append(result)
            write_summary(results, candidates)
            print(
                f"[{index}/{len(candidates)}] done: {candidate['name']}, "
                f"completed={result.get('completed')}, race_time={result.get('race_time')}, "
                f"penalties={result.get('penalty_count')}, score={result.get('score')}",
                flush=True,
            )
    finally:
        SETTINGS.write_text(original_settings, encoding="utf-8")

    completed = [r for r in results if r.get("completed") and r.get("race_time") is not None]
    fastest = min(completed, key=lambda r: r["race_time"], default=None)
    selected = min(completed, key=lambda r: r["score"], default=None)

    if fastest:
        shutil.copyfile(fastest["bot_file"], FASTEST)
    if selected:
        shutil.copyfile(selected["bot_file"], BEST)

    write_summary(results, candidates, selected, fastest)
    print(SUMMARY.read_text(encoding="utf-8"), flush=True)


if __name__ == "__main__":
    main()
