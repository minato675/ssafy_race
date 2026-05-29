from DrivingInterface.drive_controller import DrivingController


class DrivingClient(DrivingController):
    def __init__(self):
        # =========================================================== #
        #  Area for member variables =============================== #
        # =========================================================== #
        # Editing area starts from here
        #

        self.is_debug = False  # 문제가 생겼는가

        self.track_type = 99

        self.is_accident = False  # 사고가 났는가
        self.recovery_count = 0  # 복구 횟수
        self.accident_count = 0
        self.prev_steering = 0.0  # 사고 횟수
        self.debug_tick = 0

        # Tunable braking model.
        # The car stays full throttle unless a severe corner is close enough.
        self.hard_curve_angle = 55          # deg: severe corner threshold.
        self.hard_curve_target_speed = 80   # km/h: finish braking near this speed before turn-in.
        self.hard_curve_release_angle = 38  # deg: release the 80 target after the corner opens.
        self.brake_decel_mps2 = 4.8         # estimated full-brake deceleration; lower = brake earlier.
        self.brake_distance_margin = 34     # meters: extra safety buffer before the corner.
        self.brake_distance_scale = 1.18    # multiplier for calculated braking distance.
        self.brake_distance_offset = 0      # meters: + earlier braking, - later braking.
        self.hard_brake_steer_scale = 0.55  # reduce steering while still too fast.
        self.steer_unlock_speed = 95        # km/h: normal steering returns below this speed.
        self.high_speed_return_deadband = 0.45  # road-width ratio; no center pull inside this.
        self.high_speed_center_gain = 0.018      # slow center return at high speed.
        self.high_speed_steer_delta = 0.055      # max steering change per tick above 130km/h.

        #
        # Editing area ends
        # ==========================================================#
        super().__init__()

    def _clamp(self, value, min_value, max_value):
        return max(min_value, min(value, max_value))

    def control_driving(self, car_controls, sensing_info):

        # =========================================================== #
        # Area for writing code about driving rule ================= #
        # =========================================================== #
        # Editing area starts from here
        #

        if self.is_debug:  # 문제 생겼을때 차량 정보 보여주기
            print("=========================================================")
            print("[MyCar] to middle: {}".format(sensing_info.to_middle))
            print("[MyCar] collided: {}".format(sensing_info.collided))
            print("[MyCar] car speed: {} km/h".format(sensing_info.speed))
            print("[MyCar] is moving forward: {}".format(sensing_info.moving_forward))
            print("[MyCar] moving angle: {}".format(sensing_info.moving_angle))
            print("[MyCar] lap_progress: {}".format(sensing_info.lap_progress))
            print("[MyCar] track_forward_angles: {}".format(sensing_info.track_forward_angles))
            print("[MyCar] track_forward_obstacles: {}".format(sensing_info.track_forward_obstacles))
            print("[MyCar] opponent_cars_info: {}".format(sensing_info.opponent_cars_info))
            print("[MyCar] distance_to_way_points: {}".format(sensing_info.distance_to_way_points))
            print("=========================================================")

        ###########################################################################
        # 기본값 초기화
        set_throttle = 0.8
        set_brake = 0.0
        set_steering = 0.0

        # 도로의 실제 폭의 1/2 로 계산됨
        half_road_width = self.half_road_limit - 1.25  # 도로폭에서 차량 폭 여유를 제외

        # ===========================================================
        # 1. 조향 계산
        # ===========================================================
        # 속도가 빠를수록 더 먼 전방 각도를 참고하되, 인덱스 초과를 방지한다.
        angle_num = int(sensing_info.speed / 45)
        angle_num = self._clamp(angle_num, 0, len(sensing_info.track_forward_angles) - 1)
        ref_angle = sensing_info.track_forward_angles[angle_num]

        # 차량의 차선 중앙 정렬을 위한 미세 조정 값 계산
        if sensing_info.speed > 130:
            lane_ratio = abs(sensing_info.to_middle) / max(half_road_width, 0.001)
            if lane_ratio < self.high_speed_return_deadband:
                middle_add = 0.0
            else:
                center_dir = -1.0 if sensing_info.to_middle > 0 else 1.0
                middle_add = center_dir * self.high_speed_center_gain * (lane_ratio - self.high_speed_return_deadband)
        else:
            middle_add = (sensing_info.to_middle / 95) * -1

        # 차량의 Speed 에 따라서 핸들을 돌리는 값을 조정함
        steer_factor = sensing_info.speed * 1.5
        if sensing_info.speed > 70:
            steer_factor = sensing_info.speed * 0.85
        if sensing_info.speed > 100:
            steer_factor = sensing_info.speed * 0.7

        # 너무 저속일 때 steer_factor가 작아져 조향이 튀는 것을 방지
        steer_factor = max(steer_factor, 30)

        # 전방의 커브 각도와 현재 차량 진행 각도의 차이를 기반으로 조향
        set_steering = (ref_angle - sensing_info.moving_angle) / (steer_factor + 0.001)
        set_steering += middle_add

        # ===========================================================
        # 2. 목표 속도 기반 throttle / brake 제어
        # ===========================================================
        # 기존 방식: 특정 각도 이상이면 브레이크
        # 개선 방식: 전방 커브 강도에 따라 target_speed를 정하고 현재 속도와 비교

        # Stay flat-out by default. Brake only when a severe curve is within
        # the configurable braking distance.
        scan_count = min(20, len(sensing_info.track_forward_angles))
        forward_angles = sensing_info.track_forward_angles[:scan_count]
        abs_angles = [abs(angle) for angle in forward_angles]
        max_curve = max(abs_angles) if abs_angles else 0

        hard_curve_index = None
        hard_curve_angle = 0
        for idx, angle in enumerate(abs_angles):
            if angle >= self.hard_curve_angle:
                hard_curve_index = idx
                hard_curve_angle = angle
                break

        if hard_curve_index is not None and hard_curve_index < len(sensing_info.distance_to_way_points):
            hard_curve_dist = sensing_info.distance_to_way_points[hard_curve_index]
        elif hard_curve_index is not None:
            hard_curve_dist = (hard_curve_index + 1) * 10
        else:
            hard_curve_dist = 999

        speed_mps = max(0.0, sensing_info.speed) / 3.6
        target_mps = self.hard_curve_target_speed / 3.6
        brake_physics_distance = 0.0
        if speed_mps > target_mps:
            brake_physics_distance = (
                (speed_mps * speed_mps - target_mps * target_mps)
                / max(2.0 * self.brake_decel_mps2, 0.001)
            )
        brake_distance = (
            brake_physics_distance * self.brake_distance_scale
            + self.brake_distance_margin
            + self.brake_distance_offset
        )
        brake_distance = max(0.0, brake_distance)

        current_curve = abs_angles[0] if abs_angles else 0
        severe_curve_now = current_curve >= self.hard_curve_release_angle
        severe_curve_close = hard_curve_index is not None and hard_curve_dist <= brake_distance
        hard_curve_mode = severe_curve_now or severe_curve_close

        if hard_curve_mode:
            target_speed = self.hard_curve_target_speed
        else:
            target_speed = 999

        speed_gap = sensing_info.speed - target_speed
        distance_pressure = 0.0
        if hard_curve_mode and brake_distance > 0:
            distance_pressure = self._clamp((brake_distance - hard_curve_dist) / brake_distance, 0.0, 1.0)

        if hard_curve_mode and speed_gap > 0:
            if speed_gap > 45 or distance_pressure > 0.32:
                set_throttle = 0.0
                set_brake = 1.0
            elif speed_gap > 30 or distance_pressure > 0.22:
                set_throttle = 0.10
                set_brake = 0.85
            elif speed_gap > 18 or distance_pressure > 0.12:
                set_throttle = 0.25
                set_brake = 0.60
            elif speed_gap > 7:
                set_throttle = 0.45
                set_brake = 0.30
            else:
                set_throttle = 0.75
                set_brake = 0.08
        else:
            set_throttle = 1.0
            set_brake = 0.0

        if hard_curve_mode and sensing_info.speed > self.steer_unlock_speed:
            set_steering *= self.hard_brake_steer_scale

        # 매우 급한 커브에서는 조향을 조금 더 강하게 넣어 탈출 실패를 줄인다.
        if max_curve > 80 and (not hard_curve_mode or sensing_info.speed <= self.steer_unlock_speed):
            if set_steering > 0:
                set_steering += 0.16
            else:
                set_steering -= 0.16

        edge_ratio = abs(sensing_info.to_middle) / max(half_road_width, 0.001)
        if edge_ratio > 0.64:
            edge_strength = min(1.0, (edge_ratio - 0.64) / max(1.0 - 0.64, 0.001))
            center_dir = -1.0 if sensing_info.to_middle > 0 else 1.0
            set_steering += center_dir * 0.18 * edge_strength
            if sensing_info.speed > 105:
                set_throttle = min(set_throttle, 0.75)
                set_brake = max(set_brake, 0.08)

        # ===========================================================
        # 3. 장애물 회피
        # ===========================================================
        if sensing_info.track_forward_obstacles:
            first_obstacles = sensing_info.track_forward_obstacles[0]
            first_dist = first_obstacles['dist']

            if first_dist < 30:
                first_to_middle = first_obstacles['to_middle']
                car_to_middle = sensing_info.to_middle
                diff_to_middle = first_to_middle - car_to_middle

                if self.is_debug:
                    print('diff_to_middle', diff_to_middle)

                steer_coeff = 50
                safe_margin = 2.2

                if abs(diff_to_middle) < safe_margin:
                    need_steering = (safe_margin - abs(diff_to_middle)) / safe_margin

                    if car_to_middle > 0:
                        # 차가 오른쪽에 있으면 오른쪽 여유 확인 후 회피 방향 결정
                        if half_road_width - max(car_to_middle, first_to_middle) > safe_margin:
                            set_steering = +need_steering * steer_coeff / steer_factor
                        else:
                            set_steering = -need_steering * steer_coeff / steer_factor
                    elif car_to_middle < 0:
                        # 차가 왼쪽에 있으면 왼쪽 여유 확인 후 회피 방향 결정
                        if half_road_width + min(car_to_middle, first_to_middle) > safe_margin:
                            set_steering = -need_steering * steer_coeff / steer_factor
                        else:
                            set_steering = +need_steering * steer_coeff / steer_factor
                    else:
                        # 차량이 정가운데인 경우 장애물 반대 방향으로 회피
                        if first_to_middle < 0:
                            set_steering = +need_steering * steer_coeff / steer_factor
                        elif first_to_middle > 0:
                            set_steering = -need_steering * steer_coeff / steer_factor

                    # 장애물 회피 중에는 약간 감속하여 안정성 확보
                    if sensing_info.speed > 100:
                        set_throttle = min(set_throttle, 0.6)
                        set_brake = max(set_brake, 0.3)

                if self.is_debug:
                    print('set_steering', set_steering)

        # ===========================================================
        # 4. 충돌 상황 감지 후 복구
        # ===========================================================
        # 30Km/h 이상의 속도로 달리는 경우 정상 상황으로 간주
        if sensing_info.speed > 30.0:
            self.is_accident = False
            self.recovery_count = 0
            self.accident_count = 0

        # 레이싱 시작 후 Speed 1km/h 이하가 지속되면 사고 가능성 체크
        if sensing_info.lap_progress > 0.5 and self.is_accident is False and (-1.0 < sensing_info.speed < 1.0):
            self.accident_count += 1

        # Speed 1km/h 이하인 상태가 지속되면 충돌로 간주
        if self.accident_count > 6:
            self.is_accident = True

        # 충돌로 멈춘 경우 후진 시작
        if self.is_accident is True:
            set_steering = 0.02
            set_brake = 0.0
            set_throttle = -1
            self.recovery_count += 1

        # 어느 정도 후진되었을 때 정상 주행 상태로 복귀
        if self.recovery_count > 20:
            self.is_accident = False
            self.recovery_count = 0
            self.accident_count = 0
            set_steering = 0
            set_brake = 0
            set_throttle = 0

        ###########################################################################
        # 최종 제어값 보정
        if sensing_info.speed > 130 and max_curve < self.hard_curve_angle:
            steering_delta = set_steering - self.prev_steering
            set_steering = self.prev_steering + self._clamp(
                steering_delta, -self.high_speed_steer_delta, self.high_speed_steer_delta
            )

        set_steering = self._clamp(set_steering, -1.0, 1.0)
        set_throttle = self._clamp(set_throttle, -1.0, 1.0)
        set_brake = self._clamp(set_brake, 0.0, 1.0)

        car_controls.steering = set_steering
        car_controls.throttle = set_throttle
        car_controls.brake = set_brake
        self.prev_steering = car_controls.steering
        self.debug_tick += 1
        if hard_curve_mode and self.debug_tick % 15 == 0:
            print("[BRKDBG] prog={:.2f} speed={:.1f} curve={} dist={:.1f} brake_dist={:.1f} pressure={:.2f} target={} steer={:.3f} thr={:.2f} brk={:.2f}".format(
                sensing_info.lap_progress, sensing_info.speed, hard_curve_angle,
                hard_curve_dist, brake_distance, distance_pressure, target_speed,
                car_controls.steering, car_controls.throttle, car_controls.brake
            ), flush=True)

        if self.is_debug:
            print("[MyCar] target_speed:{}, max_curve:{}".format(target_speed, max_curve))
            print("[MyCar] steering:{}, throttle:{}, brake:{}"\
                  .format(car_controls.steering, car_controls.throttle, car_controls.brake))

        #
        # Editing area ends
        # ==========================================================#
        return car_controls

    # ============================
    # If you have NOT changed the <settings.json> file
    # ===> player_name = ""
    #
    # If you changed the <settings.json> file
    # ===> player_name = "My car name" (specified in the json file)  ex) Car1
    # ============================
    def set_player_name(self):
        player_name = ""
        return player_name


if __name__ == '__main__':
    print("[MyCar] Start Bot!")
    client = DrivingClient()
    return_code = client.run()
    print("[MyCar] End Bot!")

    exit(return_code)
