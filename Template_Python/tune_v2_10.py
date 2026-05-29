import json
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(r"C:\Simulator")
TEMPLATE = ROOT / "Template_Python" / "Bot_Python" / "v2.py"
BOT_DIR = ROOT / "Template_Python" / "Bot_Python"
PYTHON = ROOT / "Template_Python" / ".venv" / "Scripts" / "python.exe"
BENCHMARK = ROOT / "Template_Python" / "benchmark_bot.py"
BEST = BOT_DIR / "v2_best.py"
SUMMARY = ROOT / "Template_Python" / "tuning_summary_10.json"

BASELINE_NAME = "baseline_v2_restart2"
BASELINE_TIME = 115.06216430664062


def replace_once(text, old, new, name):
    if old not in text:
        raise RuntimeError(f"Pattern not found for {name}: {old}")
    return text.replace(old, new, 1)


def make_candidate(name, replacements):
    text = TEMPLATE.read_text(encoding="utf-8")
    for old, new in replacements:
        text = replace_once(text, old, new, name)

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
        [str(PYTHON), str(BENCHMARK), str(path), "--name", name, "--timeout", "260"],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=430,
    )
    result = parse_json_output(proc.stdout.strip(), name)
    result["returncode"] = proc.returncode
    return result


def write_summary(best_result, results, kept):
    summary = {
        "baseline": {"name": BASELINE_NAME, "race_time": BASELINE_TIME},
        "best": best_result,
        "kept_candidates": kept,
        "results": results,
        "updated_at_epoch": time.time(),
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_previous_candidates():
    for path in BOT_DIR.glob("v2_10_*.py"):
        path.unlink()


def main():
    cleanup_previous_candidates()

    candidates = [
        (
            "v2_10_c01_gentle_top",
            [
                ("target_speed = 170", "target_speed = 172"),
                ("target_speed = 145", "target_speed = 146"),
            ],
        ),
        (
            "v2_10_c02_mild_corner",
            [
                ("target_speed = 120", "target_speed = 116"),
                ("target_speed = 95", "target_speed = 90"),
                ("target_speed = 75", "target_speed = 70"),
                ("target_speed = 55", "target_speed = 52"),
            ],
        ),
        (
            "v2_10_c03_brake_late",
            [
                ("if speed_gap > 35:", "if speed_gap > 38:"),
                ("elif speed_gap > 25:", "elif speed_gap > 28:"),
                ("elif speed_gap > 15:", "elif speed_gap > 17:"),
                ("elif speed_gap > 5:", "elif speed_gap > 6:"),
            ],
        ),
        (
            "v2_10_c04_brake_early",
            [
                ("if speed_gap > 35:", "if speed_gap > 32:"),
                ("elif speed_gap > 25:", "elif speed_gap > 22:"),
                ("elif speed_gap > 15:", "elif speed_gap > 13:"),
                ("elif speed_gap > 5:", "elif speed_gap > 4:"),
            ],
        ),
        (
            "v2_10_c05_lookahead_more",
            [
                (
                    "look_ahead = int(sensing_info.speed / 30) + 1",
                    "look_ahead = int(sensing_info.speed / 26) + 1",
                ),
                (
                    "look_ahead = self._clamp(look_ahead, 1, min(6, len(sensing_info.track_forward_angles)))",
                    "look_ahead = self._clamp(look_ahead, 1, min(7, len(sensing_info.track_forward_angles)))",
                ),
            ],
        ),
        (
            "v2_10_c06_lookahead_less",
            [
                (
                    "look_ahead = int(sensing_info.speed / 30) + 1",
                    "look_ahead = int(sensing_info.speed / 38) + 1",
                ),
            ],
        ),
        (
            "v2_10_c07_steer_more",
            [
                ("steer_factor = sensing_info.speed * 0.85", "steer_factor = sensing_info.speed * 0.82"),
                ("steer_factor = sensing_info.speed * 0.7", "steer_factor = sensing_info.speed * 0.67"),
            ],
        ),
        (
            "v2_10_c08_steer_less",
            [
                ("steer_factor = sensing_info.speed * 0.85", "steer_factor = sensing_info.speed * 0.90"),
                ("steer_factor = sensing_info.speed * 0.7", "steer_factor = sensing_info.speed * 0.75"),
            ],
        ),
        (
            "v2_10_c09_soft_center",
            [
                (
                    "middle_add = (sensing_info.to_middle / 80) * -1",
                    "middle_add = (sensing_info.to_middle / 90) * -1",
                ),
            ],
        ),
        (
            "v2_10_c10_soft_hairpin",
            [
                ("set_steering += 0.25", "set_steering += 0.18"),
                ("set_steering -= 0.25", "set_steering -= 0.18"),
            ],
        ),
    ]

    best_time = BASELINE_TIME
    best_result = {"name": BASELINE_NAME, "race_time": BASELINE_TIME, "bot_file": str(TEMPLATE)}
    results = []
    kept = []
    write_summary(best_result, results, kept)

    for index, (name, replacements) in enumerate(candidates, start=1):
        path = make_candidate(name, replacements)
        print(f"[{index}/{len(candidates)}] benchmark start: {name}", flush=True)

        result = run_candidate(path, name)
        race_time = result.get("race_time")
        completed = bool(result.get("completed"))
        improved = completed and race_time is not None and race_time < BASELINE_TIME
        best_improved = improved and race_time < best_time

        result["improved_vs_baseline"] = improved
        if race_time is not None:
            result["delta_vs_baseline"] = race_time - BASELINE_TIME

        results.append(result)

        if improved:
            kept.append(str(path))
        elif path.exists():
            path.unlink()

        if best_improved:
            best_time = race_time
            best_result = result
            shutil.copyfile(path, BEST)

        write_summary(best_result, results, kept)
        delta = result.get("delta_vs_baseline")
        delta_text = f"{delta:+.3f}s" if isinstance(delta, (int, float)) else "n/a"
        print(
            f"[{index}/{len(candidates)}] done: {name}, completed={completed}, "
            f"race_time={race_time}, delta={delta_text}, penalties={result.get('penalty_count')}",
            flush=True,
        )

    if not BEST.exists():
        shutil.copyfile(TEMPLATE, BEST)

    print(SUMMARY.read_text(encoding="utf-8"), flush=True)


if __name__ == "__main__":
    main()
