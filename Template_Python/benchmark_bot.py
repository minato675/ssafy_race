import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Simulator")
BOT_DIR = ROOT / "Template_Python" / "Bot_Python"
PYTHON = ROOT / "Template_Python" / ".venv" / "Scripts" / "python.exe"
RESULTS = ROOT / "Template_Python" / "benchmark_results.jsonl"


def kill_processes():
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -eq 'python.exe' -and "
                "$_.ExecutablePath -like 'C:\\Simulator\\Template_Python\\.venv\\*' -and "
                "$_.CommandLine -like '*Bot_Python*' -and "
                "$_.CommandLine -notlike '*benchmark_bot.py*' } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            ),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    for image in ("Algo.exe", "Algo-Win64-Shipping.exe"):
        subprocess.run(
            ["taskkill", "/F", "/IM", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def start_simulator():
    env = os.environ.copy()
    env["OPENSSL_ia32cap"] = ":~0x20000000"
    subprocess.Popen(
        [str(ROOT / "Algo.exe"), "-ResX=640", "-ResY=480", "-windowed"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_simulator(timeout=45):
    sys.path.insert(0, str(BOT_DIR / "DrivingInterface"))
    import airsim

    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            client = airsim.CarClient(timeout_value=5)
            if client.ping():
                return client
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"Simulator did not become ready: {last_error}")


def wait_for_track_data(client, timeout=140):
    # The RPC endpoint can answer before the selected map has published waypoints.
    time.sleep(8)
    deadline = time.time() + timeout
    last_count = 0
    while time.time() < deadline:
        try:
            sys.path.insert(0, str(BOT_DIR / "DrivingInterface"))
            import airsim

            client = airsim.CarClient(timeout_value=10)
        except Exception:
            pass
        for vehicle_name in ("Car1", ""):
            try:
                user = client.getAlgoUserAPI(vehicle_name)
                waypoints = list(getattr(user, "wayPoints", []) or [])
                last_count = max(last_count, len([point for point in waypoints if point]))
                if last_count > 20:
                    return client
            except Exception:
                pass
        time.sleep(1)
    raise RuntimeError(f"Track data was not ready; non-empty waypoints={last_count}")


def run_benchmark(bot_file, name, timeout=260, reuse_simulator=False):
    if reuse_simulator:
        client = wait_for_simulator()
    else:
        kill_processes()
        time.sleep(1)
        start_simulator()
    client = wait_for_simulator()
    client = wait_for_track_data(client)

    # Start from a clean API-control state so the bot can claim Car1.
    try:
        client.reset()
        time.sleep(1)
        client.enableApiControl(False, "Car1")
    except Exception:
        pass

    stdout_path = ROOT / "Template_Python" / f"{name}_stdout.log"
    stderr_path = ROOT / "Template_Python" / f"{name}_stderr.log"
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        bot = subprocess.Popen(
            [str(PYTHON), "-u", str(bot_file)],
            cwd=str(BOT_DIR),
            stdout=stdout,
            stderr=stderr,
        )

    started = time.time()
    best_snapshot = {}
    completed = False
    lap1_time = None
    while time.time() - started < timeout:
        time.sleep(0.5)
        try:
            admin = client.getAlgoAdminAPI("Car1")
            user = client.getAlgoUserAPI("Car1")
            race_time = float(getattr(admin, "ac_PlayerRaceTime", 0.0) or 0.0)
            current_lap = int(getattr(user, "ac_player_current_lap", 0) or 0)
            if lap1_time is None and current_lap >= 2 and race_time > 0:
                lap1_time = race_time
            snapshot = {
                "race_time": race_time,
                "lap1_time_est": lap1_time,
                "lap2_time_est": (race_time - lap1_time) if lap1_time is not None else None,
                "first_lap_time": float(getattr(admin, "ac_player_first_lap_time", 0.0) or 0.0),
                "race_times": list(getattr(admin, "ac_PlayerRaceTimes", []) or []),
                "current_lap": current_lap,
                "lap_progress": float(getattr(user, "ac_player_lap_progress", 0.0) or 0.0),
                "complete": bool(getattr(user, "ac_RaceComplete_YN", False)),
            }
            best_snapshot = snapshot
            if snapshot["complete"]:
                completed = True
                break
        except Exception as exc:
            best_snapshot["poll_error"] = repr(exc)

        if bot.poll() is not None and best_snapshot.get("lap_progress", 0.0) < 99.0:
            break

    if bot.poll() is None:
        bot.terminate()
        try:
            bot.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bot.kill()

    stdout_text = stdout_path.read_text(encoding="utf-8", errors="ignore") if stdout_path.exists() else ""
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="ignore") if stderr_path.exists() else ""
    penalty_count = stdout_text.count("Penalty applied")

    result = {
        "name": name,
        "bot_file": str(bot_file),
        "completed": completed,
        "elapsed_wall": round(time.time() - started, 3),
        "penalty_count": penalty_count,
        "stdout_tail": stdout_text[-2000:],
        "stderr_tail": stderr_text[-2000:],
        **best_snapshot,
    }

    with RESULTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")

    if reuse_simulator:
        try:
            client.enableApiControl(False, "Car1")
        except Exception:
            pass
    else:
        kill_processes()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bot_file")
    parser.add_argument("--name", default=None)
    parser.add_argument("--timeout", type=int, default=260)
    parser.add_argument("--reuse-simulator", action="store_true")
    args = parser.parse_args()

    bot_file = Path(args.bot_file)
    if not bot_file.is_absolute():
        bot_file = BOT_DIR / bot_file
    name = args.name or bot_file.stem
    result = run_benchmark(bot_file, name, args.timeout, args.reuse_simulator)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
