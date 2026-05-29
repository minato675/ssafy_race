# SSAFY Race Bot Tuning Notes

SSAFY Race 시뮬레이터에서 Python 기반 자율주행 봇을 튜닝하며 얻은 결과와 다음 작업 방향을 정리한 문서입니다.

주요 목표는 수동 조작이 아닌 코드 기반 주행에서 맵별 랩타임을 줄이고, 좁고 급격한 코너가 많은 `Map 160`에서 안정성을 확보하는 것입니다.

## 프로젝트 구조

| 경로 | 설명 |
|---|---|
| `Template_Python/Bot_Python/` | 주행 봇 모델 파일 |
| `Template_Python/benchmark_bot.py` | 모델 벤치마크 실행 스크립트 |
| `Template_Python/map_benchmark_summary.json` | Map 10/60/160 교차 벤치마크 결과 |
| `Template_Python/benchmark_results.jsonl` | 개별 벤치마크 누적 결과 |
| `settings/` | 시뮬레이터 설정 관련 파일 |

## 실행 환경

- OS: Windows
- Simulator: SSAFY Race
- Bot language: Python
- Python virtual environment: `Template_Python/.venv`
- AirSim settings path: `%USERPROFILE%/Documents/AirSim/settings.json`
- 시뮬레이터 실행 중 `0xc0000005 Access Violation`이 발생할 경우, 실행 환경변수에 아래 값을 추가합니다.

```powershell
$env:OPENSSL_ia32cap=":~0x20000000"
```

`benchmark_bot.py`에는 위 우회 설정을 적용한 상태입니다.

## 벤치마크 실행 방법

```powershell
Template_Python/.venv/Scripts/python.exe `
  Template_Python/benchmark_bot.py `
  Template_Python/Bot_Python/<MODEL>.py `
  --name <MODEL_NAME> `
  --timeout 270
```

실행 후 주요 로그는 아래 형태로 생성됩니다.

| 로그 | 설명 |
|---|---|
| `Template_Python/<MODEL_NAME>_stdout.log` | 봇 실행 표준 출력 |
| `Template_Python/<MODEL_NAME>_stderr.log` | 봇 실행 오류 출력 |
| `Template_Python/<MODEL_NAME>_bench_stdout.log` | 벤치마크 표준 출력 |
| `Template_Python/<MODEL_NAME>_bench_stderr.log` | 벤치마크 오류 출력 |

## 튜닝 원칙

현재 튜닝 방향은 다음과 같습니다.

1. 직선 구간에서는 가능한 최고 속도를 유지합니다.
2. 약한 커브는 브레이크 없이 조향만으로 통과합니다.
3. 급격한 커브에서만 감속합니다.
4. 강한 헤어핀 진입 목표 속도는 약 `80 km/h`를 기준으로 합니다.
5. 감속 시작 지점은 속도 기반 제동거리 계산으로 추정합니다.
6. 코너 직전에 감속이 완료되도록 제동거리 파라미터를 조정합니다.
7. 고속 구간에서는 중앙 복귀 조향을 매우 약하게 적용해 드리프트처럼 끌리는 현상을 줄입니다.
8. 후보 모델은 한 번에 대량 실행하지 않고, 결과를 분석한 뒤 다음 모델을 수정합니다.

제동거리 계산의 기본 아이디어는 아래와 같습니다.

```text
brake_distance = (v^2 - target_v^2) / (2 * decel)
```

여기서 `v`와 `target_v`는 m/s 단위이며, 실제 모델에서는 `margin`, `scale`, `offset` 같은 보정 파라미터를 둡니다.

## Map 160 특화 모델 결과

`Map 160`은 도로 폭이 좁고 헤어핀이 많아 일반 맵용 모델보다 별도 튜닝이 필요했습니다.

| Model | Race Time | Penalties | Notes |
|---|---:|---:|---|
| `v2_map160_best.py` | `133.3167s` | `8` | 현재 최고 점수 모델 |
| `v2_map160_fastest.py` | `133.0287s` | `24` | 순수 랩타임은 가장 빠르지만 패널티가 많음 |
| `v2_map160_iter05_hp1_settle.py` | `135.0064s` | `0` | 가장 좋은 무패널티 후보 |
| `v2_map160_iter07_speed_floor.py` | `135.0511s` | `0` | iter05와 유사하나 개선 없음 |
| `v2_map160_iter08_hp2_only.py` | `135.3833s` | `8` | HP2만 보정, HP1 패널티 재발 |
| `v2_map160_maxspeed_brake_stable.py` | `141.0204s` | `41` | 물리 기반 감속 적용 범위가 넓어 실패 |

## Map 160 코스 관찰

- 도로 반폭은 약 `7.0` 수준으로 관찰되었습니다.
- 헤어핀 `1`과 `2`에서 대부분의 모델이 가장 크게 흔들렸습니다.
- 초반 관찰 난이도는 `2 > 4 > 1 = 3`이었지만, 반복 주행 결과 `1`과 `2`가 핵심 병목으로 확인되었습니다.
- 주요 곡률 구간은 대략 아래 위치에서 나타났습니다.

| 구간 | Progress | 특징 |
|---|---:|---|
| Hairpin 2 | `18.9%` 부근 | 가장 어려운 초반 헤어핀 |
| Hairpin 1 | `46.6%` 부근 | 고속 진입 시 패널티가 잦은 구간 |
| Hairpin 3 | `62.6%` 부근 | 중후반 커브 |
| Hairpin 4 | `83.9%` - `91.2%` | 후반 복합 헤어핀 |

## 교차 맵 벤치마크

아래 결과는 `baseline_v2`와 `v2_10_*` 계열 모델을 `Map 10`, `Map 60`, `Map 160`에서 비교한 것입니다.

점수 기준은 아래와 같습니다.

```text
score = race_time + penalty_count * 0.12
```

점수가 낮을수록 좋은 결과입니다.

### 맵별 최고 모델

| Map | Best Model | Race Time | Penalties | Score |
|---:|---|---:|---:|---:|
| `10` | `v2_10_c06_lookahead_less` | `75.893s` | `0` | `75.893` |
| `60` | `v2_10_c03_brake_late` | `181.364s` | `0` | `181.364` |
| `160` | `v2_10_c09_soft_center` | `134.776s` | `21` | `137.296` |

### Map 10

| Rank | Model | Race Time | Penalties | Score |
|---:|---|---:|---:|---:|
| `1` | `v2_10_c06_lookahead_less` | `75.893s` | `0` | `75.893` |
| `2` | `v2_10_c03_brake_late` | `78.247s` | `0` | `78.247` |
| `3` | `v2_10_c08_steer_less` | `78.585s` | `0` | `78.585` |
| `4` | `v2_10_c09_soft_center` | `78.929s` | `0` | `78.929` |
| `5` | `v2_10_c10_soft_hairpin` | `78.939s` | `0` | `78.939` |
| `6` | `baseline_v2` | `78.954s` | `0` | `78.954` |
| `7` | `v2_10_c01_gentle_top` | `79.105s` | `0` | `79.105` |

### Map 60

| Rank | Model | Race Time | Penalties | Score |
|---:|---|---:|---:|---:|
| `1` | `v2_10_c03_brake_late` | `181.364s` | `0` | `181.364` |
| `2` | `v2_10_c10_soft_hairpin` | `182.066s` | `0` | `182.066` |
| `3` | `v2_10_c09_soft_center` | `182.354s` | `0` | `182.354` |
| `4` | `v2_10_c08_steer_less` | `182.657s` | `0` | `182.657` |
| `5` | `v2_10_c01_gentle_top` | `183.738s` | `4` | `184.218` |
| `6` | `v2_10_c06_lookahead_less` | `190.068s` | `7` | `190.908` |
| `7` | `baseline_v2` | `191.328s` | `0` | `191.328` |

### Map 160 교차 맵 참고

Map 160에서는 아래 교차 맵 모델보다 `v2_map160_best.py` 계열의 특화 모델을 우선 사용하는 것이 좋습니다.

| Rank | Model | Race Time | Penalties | Score |
|---:|---|---:|---:|---:|
| `1` | `v2_10_c09_soft_center` | `134.776s` | `21` | `137.296` |
| `2` | `v2_10_c10_soft_hairpin` | `134.734s` | `22` | `137.374` |
| `3` | `baseline_v2` | `135.655s` | `38` | `140.215` |
| `4` | `v2_10_c01_gentle_top` | `136.718s` | `30` | `140.318` |
| `5` | `v2_10_c03_brake_late` | `136.274s` | `35` | `140.474` |
| `6` | `v2_10_c08_steer_less` | `136.934s` | `50` | `142.934` |
| `7` | `v2_10_c06_lookahead_less` | `139.363s` | `74` | `148.243` |

## 효과가 있었던 접근

- HP1/HP2 구간에 한정해 라인을 안정화한 모델이 패널티를 크게 줄였습니다.
- 급한 중앙 복귀를 줄이고, 도로 안에 있을 때는 천천히 복귀하도록 만든 것이 고속 흔들림 감소에 도움이 되었습니다.
- 강한 헤어핀에서는 인위적인 조향보다 진입 전 속도 관리와 라인 안정화가 더 중요했습니다.

## 효과가 낮았던 접근

- 단순히 `hard_curve_angle >= 75` 같은 단일 웨이포인트 기준만 사용하는 방식은 감속 타이밍이 늦었습니다.
- 누적 곡률 기준을 너무 낮게 잡으면 약한 커브에서도 불필요하게 브레이크가 걸렸습니다.
- 도로 양끝을 강하게 활용하는 레이싱 라인은 이론적으로는 좋아 보였지만, 좁은 Map 160에서는 조향 포화와 패널티를 만들었습니다.
- 모든 헤어핀에 동일한 감속 규칙을 적용하면 HP1/HP2에서 불안정성이 커졌습니다.

## 물리 기반 감속 실험 파라미터

마지막 물리 기반 감속 실험 모델인 `v2_map160_brake_physics_v5.py`의 주요 파라미터입니다.

```python
self.hard_curve_angle = 75
self.hard_curve_cumulative_angle = 150
self.hard_curve_cumulative_min_peak = 60
self.hard_curve_window = 5
self.hard_curve_scan = 14
self.hard_curve_target_speed = 80
self.hard_curve_release_angle = 50
self.brake_decel_mps2 = 7.2
self.brake_distance_margin = 18
self.brake_distance_scale = 0.92
self.brake_distance_offset = -8
self.hard_brake_steer_scale = 0.70
self.steer_unlock_speed = 95
self.high_speed_return_deadband = 0.50
self.high_speed_center_gain = 0.035
self.high_speed_steer_delta = 0.11
```

해당 모델은 약한 커브에서의 불필요한 감속은 일부 줄였지만, HP1 구간에서 감속과 조향 전략이 충돌하며 패널티가 많이 발생했습니다.

## 다음 개선 방향

가장 유망한 다음 실험은 `v2_map160_best.py` 또는 `v2_map160_iter05_hp1_settle.py`를 기반으로, 물리 기반 감속을 HP1/HP2 구간에만 제한적으로 적용하는 것입니다.

추천 실험 범위는 아래와 같습니다.

| 구간 | Progress Window | 목표 |
|---|---:|---|
| HP2 | `14.5%` - `21.0%` | 초반 가장 어려운 헤어핀 안정화 |
| HP1 | `42.5%` - `48.5%` | 고속 진입 패널티 감소 |

구간 밖에서는 기존 최고 모델의 속도/조향 전략을 유지하고, 약한 커브에서는 브레이크 없이 통과하도록 제한하는 것이 좋습니다.

