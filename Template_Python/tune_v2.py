import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(r"C:\Simulator")
TEMPLATE = ROOT / "Template_Python" / "Bot_Python" / "v2.py"
BOT_DIR = ROOT / "Template_Python" / "Bot_Python"
PYTHON = ROOT / "Template_Python" / ".venv" / "Scripts" / "python.exe"
BENCHMARK = ROOT / "Template_Python" / "benchmark_bot.py"
BEST = BOT_DIR / "v2_best.py"
SUMMARY = ROOT / "Template_Python" / "tuning_summary.json"


BASELINE_TIME = 115.06216430664062


def make_candidate(name, replacements):
    text = TEMPLATE.read_text(encoding="utf-8")
    for old, new in replacements:
        if old not in text:
            raise RuntimeError(f"Pattern not found for {name}: {old}")
        text = text.replace(old, new, 1)

    path = BOT_DIR / f"{name}.py"
    path.write_text(text, encoding="utf-8")
    return path


def run_candidate(path, name):
    proc = subprocess.run(
        [str(PYTHON), str(BENCHMARK), str(path), "--name", name, "--timeout", "260"],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=430,
    )
    output = proc.stdout.strip()
    json_start = output.find("{")
    if json_start == -1:
        return {"name": name, "completed": False, "error": output}
    return json.loads(output[json_start:])


def main():
    candidates = [
        (
            "v2_tune_safe_corner",
            [
                ("target_speed = 170", "target_speed = 172"),
                ("target_speed = 145", "target_speed = 142"),
                ("target_speed = 120", "target_speed = 112"),
                ("target_speed = 95", "target_speed = 86"),
                ("target_speed = 75", "target_speed = 64"),
                ("target_speed = 55", "target_speed = 48"),
            ],
        ),
        (
            "v2_tune_fast_straight",
            [
                ("target_speed = 170", "target_speed = 182"),
                ("target_speed = 145", "target_speed = 152"),
                ("target_speed = 120", "target_speed = 122"),
                ("target_speed = 95", "target_speed = 90"),
                ("target_speed = 75", "target_speed = 66"),
                ("target_speed = 55", "target_speed = 48"),
            ],
        ),
        (
            "v2_tune_soft_center",
            [
                ("middle_add = (sensing_info.to_middle / 80) * -1", "middle_add = (sensing_info.to_middle / 95) * -1"),
                ("target_speed = 170", "target_speed = 178"),
                ("target_speed = 145", "target_speed = 148"),
                ("target_speed = 120", "target_speed = 116"),
                ("target_speed = 95", "target_speed = 88"),
                ("target_speed = 75", "target_speed = 65"),
                ("target_speed = 55", "target_speed = 48"),
            ],
        ),
    ]

    best_time = BASELINE_TIME
    best_result = {"name": "baseline_v2", "race_time": BASELINE_TIME}
    results = []

    for name, replacements in candidates:
        path = make_candidate(name, replacements)
        result = run_candidate(path, name)
        results.append(result)
        race_time = result.get("race_time")
        if result.get("completed") and race_time is not None and race_time < best_time:
            best_time = race_time
            best_result = result
            shutil.copyfile(path, BEST)
        elif path.exists():
            path.unlink()

        SUMMARY.write_text(
            json.dumps({"best": best_result, "results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if not BEST.exists():
        shutil.copyfile(TEMPLATE, BEST)

    print(SUMMARY.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
