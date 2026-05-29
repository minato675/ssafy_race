import json
import subprocess
import time
from pathlib import Path


ROOT = Path(r"C:\Simulator")
BOT_DIR = ROOT / "Template_Python" / "Bot_Python"
PYTHON = ROOT / "Template_Python" / ".venv" / "Scripts" / "python.exe"
BENCHMARK = ROOT / "Template_Python" / "benchmark_bot.py"
SETTINGS = Path(r"C:\Users\SSAFY\Documents\AirSim\settings.json")
TUNING_SUMMARY = ROOT / "Template_Python" / "tuning_summary_10.json"
SUMMARY = ROOT / "Template_Python" / "map_benchmark_summary.json"

MAPS = [
    {"label": "map10", "name": "Map 10", "id": "10"},
    {"label": "map60", "name": "Map 60", "id": "60"},
    {"label": "map160", "name": "Map 160", "id": "160"},
]

TIMEOUTS = {
    "10": 360,
    "60": 420,
    "160": 560,
}


def load_models():
    models = [{"name": "baseline_v2", "path": str(BOT_DIR / "v2.py")}]
    summary = json.loads(TUNING_SUMMARY.read_text(encoding="utf-8"))
    for candidate in summary.get("kept_candidates", []):
        path = Path(candidate)
        if path.exists():
            models.append({"name": path.stem, "path": str(path)})
    return models


def set_map(map_id):
    settings = json.loads(SETTINGS.read_text(encoding="utf-8-sig"))
    settings.setdefault("Algo", {})["Map"] = str(map_id)
    settings["ControlMode"] = "Code"
    SETTINGS.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_json_output(output, fallback):
    for idx, char in enumerate(output):
        if char != "{":
            continue
        try:
            return json.loads(output[idx:])
        except json.JSONDecodeError:
            continue
    return {
        **fallback,
        "completed": False,
        "race_time": None,
        "error": "benchmark did not return JSON",
        "output_tail": output[-4000:],
    }


def run_benchmark(model, map_info):
    timeout = TIMEOUTS.get(map_info["id"], 420)
    run_name = f"{model['name']}_{map_info['label']}"
    try:
        proc = subprocess.run(
            [
                str(PYTHON),
                str(BENCHMARK),
                model["path"],
                "--name",
                run_name,
                "--timeout",
                str(timeout),
            ],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout + 190,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "name": run_name,
            "model": model["name"],
            "map_label": map_info["label"],
            "map_name": map_info["name"],
            "map_id": map_info["id"],
            "completed": False,
            "race_time": None,
            "error": f"benchmark timed out after {timeout + 190}s",
            "output_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
        }
    result = parse_json_output(
        proc.stdout.strip(),
        {
            "name": run_name,
            "model": model["name"],
            "map_label": map_info["label"],
            "map_name": map_info["name"],
            "map_id": map_info["id"],
        },
    )
    result.update(
        {
            "model": model["name"],
            "map_label": map_info["label"],
            "map_name": map_info["name"],
            "map_id": map_info["id"],
            "returncode": proc.returncode,
        }
    )
    return result


def write_summary(results, models):
    by_map = {}
    for map_info in MAPS:
        rows = [r for r in results if r.get("map_id") == map_info["id"]]
        rows.sort(key=lambda r: (r.get("race_time") is None, r.get("race_time") or 999999))
        by_map[map_info["label"]] = rows

    SUMMARY.write_text(
        json.dumps(
            {
                "maps": MAPS,
                "models": models,
                "results": results,
                "ranking_by_map": by_map,
                "updated_at_epoch": time.time(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main():
    original_settings = SETTINGS.read_text(encoding="utf-8")
    models = load_models()
    results = []
    write_summary(results, models)

    try:
        total = len(MAPS) * len(models)
        index = 0
        for map_info in MAPS:
            set_map(map_info["id"])
            for model in models:
                index += 1
                print(
                    f"[{index}/{total}] start: map={map_info['name']}({map_info['id']}), "
                    f"model={model['name']}",
                    flush=True,
                )
                result = run_benchmark(model, map_info)
                results.append(result)
                write_summary(results, models)
                print(
                    f"[{index}/{total}] done: map={map_info['name']}, model={model['name']}, "
                    f"completed={result.get('completed')}, race_time={result.get('race_time')}, "
                    f"penalties={result.get('penalty_count')}",
                    flush=True,
                )
    finally:
        SETTINGS.write_text(original_settings, encoding="utf-8")
        write_summary(results, models)

    print(SUMMARY.read_text(encoding="utf-8"), flush=True)


if __name__ == "__main__":
    main()
