from DrivingInterface.drive_controller import DrivingController


class DrivingClient(DrivingController):
    def __init__(self):
        # =========================================================== #
        #  Area for member variables =============================== #
        # =========================================================== #
        # Editing area starts from here
        #

        self.is_debug = False

        self.track_type = 99

        self.is_accident = False
        self.recovery_count = 0
        self.accident_count = 0
        self.prev_steering = 0.0

        # ===========================================================
        # 속도 / 감속 튜닝 파라미터
        # ===========================================================
        # 기본 주행은 항상 최고 속도 유지
        self.MAX_THROTTLE = 1.0

        # 강한 커브에서만 감속할 목표 속도
        self.HARD_CURVE_TARGET_SPEED = 70.0

        # 이 각도 이상부터 강한 커브로 판단
        # 값을 낮추면 더 자주 감속, 높이면 더 공격적으로 주행
        self.HARD_CURVE_ANGLE = 70.0

        # 속도에 따라 몇 개 앞의 각도까지 볼지 결정하는 값
        # 값을 낮추면 더 멀리 봄, 높이면 가까이 봄
        self.BRAKE_LOOKAHEAD_SPEED_DIV = 1

        # 최소 / 최대 확인 구간
        self.MIN_BRAKE_LOOKAHEAD = 3
        self.MAX_BRAKE_LOOKAHEAD = 30

        # 강한 커브 감속 시작 여유값
        # 예: target 80, margin 10이면 90km/h 초과부터 브레이크 시작
        self.BRAKE_START_MARGIN = 8.0

        # 현재 속도가 목표 속도보다 얼마나 빠른지에 따른 브레이크 강도
        # 제동거리를 아직 모르므로 여기 값을 바꿔가며 튜닝
        self.BRAKE_GAP_LIGHT = 10000.0
        self.BRAKE_GAP_MIDDLE = 25000.0
        self.BRAKE_GAP_HEAVY = 40000.0

        self.BRAKE_POWER_LIGHT = 1000
        self.BRAKE_POWER_MIDDLE = 1000
        self.BRAKE_POWER_HEAVY = 1000
        self.BRAKE_POWER_FULL = 1000.0

        # 브레이크 중 throttle을 얼마나 남길지
        self.THROTTLE_DURING_LIGHT_BRAKE = 0.45
        self.THROTTLE_DURING_MIDDLE_BRAKE = 0.25
        self.THROTTLE_DURING_HEAVY_BRAKE = 0.1
        self.THROTTLE_DURING_FULL_BRAKE = 0.0

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

        if self.is_debug:
            print("=========================================================")
            print("[MyCar] to middle: {}".format(sensing_info.to_middle))
            print("[MyCar] collided: {}".format(sensing_info.collided))
            print("[MyCar] car speed: {} km/h".format(sensing_info.speed))
            print("[MyCar] is moving forward: {}".format(sensing_info.moving_forward))
            print("[MyCar] moving angle: {}".format(sensing_info.moving_angle))
            print("[MyCar] lap_progress: {}".format(sensing_info.lap_progress))
            print(
                "[MyCar] track_forward_angles: {}".format(
                    sensing_info.track_forward_angles
                )
            )
            print(
                "[MyCar] track_forward_obstacles: {}".format(
                    sensing_info.track_forward_obstacles
                )
            )
            print(
                "[MyCar] opponent_cars_info: {}".format(sensing_info.opponent_cars_info)
            )
            print(
                "[MyCar] distance_to_way_points: {}".format(
                    sensing_info.distance_to_way_points
                )
            )
            print("=========================================================")

        ###########################################################################
        # 기본값 초기화
        # 평소에는 항상 최고 속도 유지
        set_throttle = self.MAX_THROTTLE
        set_brake = 0.0
        set_steering = 0.0

        half_road_width = self.half_road_limit - 1.25

        # ===========================================================
        # 1. 조향 계산
        # ===========================================================
        angle_num = int(sensing_info.speed / 38)
        angle_num = self._clamp(
            angle_num, 0, len(sensing_info.track_forward_angles) - 1
        )
        ref_angle = sensing_info.track_forward_angles[angle_num]

        middle_add = (sensing_info.to_middle / 95) * -1

        steer_factor = sensing_info.speed * 1.5
        if sensing_info.speed > 70:
            steer_factor = sensing_info.speed * 0.85
        if sensing_info.speed > 100:
            steer_factor = sensing_info.speed * 0.7

        steer_factor = max(steer_factor, 30)

        set_steering = (ref_angle - sensing_info.moving_angle) / (steer_factor + 0.001)
        set_steering += middle_add

        # ===========================================================
        # 2. 속도 / 브레이크 제어
        # ===========================================================
        # 요구사항:
        # 1. 평소 속도는 항상 최고 유지
        # 2. 커브각도가 심한 경우에만 80까지 브레이크
        # 3. 약한 커브는 브레이크 없이 조향으로 진행
        # 4. 제동거리 관련 값은 파라미터로 튜닝 가능

        brake_look_ahead = int(sensing_info.speed / self.BRAKE_LOOKAHEAD_SPEED_DIV) + 1
        brake_look_ahead = self._clamp(
            brake_look_ahead,
            self.MIN_BRAKE_LOOKAHEAD,
            min(self.MAX_BRAKE_LOOKAHEAD, len(sensing_info.track_forward_angles)),
        )

        forward_angles = sensing_info.track_forward_angles[:brake_look_ahead]
        max_curve = max(abs(angle) for angle in forward_angles)

        is_hard_curve = max_curve >= self.HARD_CURVE_ANGLE

        if is_hard_curve:
            target_speed = self.HARD_CURVE_TARGET_SPEED
            speed_gap = sensing_info.speed - target_speed

            # 목표 속도보다 충분히 빠를 때만 브레이크
            if speed_gap > self.BRAKE_GAP_HEAVY:
                set_throttle = self.THROTTLE_DURING_FULL_BRAKE
                set_brake = self.BRAKE_POWER_FULL

            elif speed_gap > self.BRAKE_GAP_MIDDLE:
                set_throttle = self.THROTTLE_DURING_HEAVY_BRAKE
                set_brake = self.BRAKE_POWER_HEAVY

            elif speed_gap > self.BRAKE_GAP_LIGHT:
                set_throttle = self.THROTTLE_DURING_MIDDLE_BRAKE
                set_brake = self.BRAKE_POWER_MIDDLE

            elif speed_gap > self.BRAKE_START_MARGIN:
                set_throttle = self.THROTTLE_DURING_LIGHT_BRAKE
                set_brake = self.BRAKE_POWER_LIGHT

            else:
                # 이미 80 근처까지 감속했다면 다시 가속
                set_throttle = self.MAX_THROTTLE
                set_brake = 0.0

        else:
            # 약한 커브는 브레이크 없이 조향으로만 처리
            target_speed = 999
            set_throttle = self.MAX_THROTTLE
            set_brake = 0.0

        # 강한 커브에서는 조향을 조금 더 강하게 넣어 코너 진입 안정화
        if is_hard_curve:
            if set_steering > 0:
                set_steering += 0.10
            else:
                set_steering -= 0.10

        # 도로 가장자리로 밀렸을 때 중앙 복귀 보정
        edge_ratio = abs(sensing_info.to_middle) / max(half_road_width, 0.001)
        if edge_ratio > 0.64:
            edge_strength = min(1.0, (edge_ratio - 0.64) / max(1.0 - 0.64, 0.001))
            center_dir = -1.0 if sensing_info.to_middle > 0 else 1.0
            set_steering += center_dir * 0.18 * edge_strength

            # 가장자리에서는 너무 위험할 때만 최소 감속
            if sensing_info.speed > 120 and edge_ratio > 0.8:
                set_throttle = min(set_throttle, 0.7)
                set_brake = max(set_brake, 0.15)

        # ===========================================================
        # 3. 장애물 회피
        # ===========================================================
        if sensing_info.track_forward_obstacles:
            first_obstacles = sensing_info.track_forward_obstacles[0]
            first_dist = first_obstacles["dist"]

            if first_dist < 30:
                first_to_middle = first_obstacles["to_middle"]
                car_to_middle = sensing_info.to_middle
                diff_to_middle = first_to_middle - car_to_middle

                if self.is_debug:
                    print("diff_to_middle", diff_to_middle)

                steer_coeff = 50
                safe_margin = 2.2

                if abs(diff_to_middle) < safe_margin:
                    need_steering = (safe_margin - abs(diff_to_middle)) / safe_margin

                    if car_to_middle > 0:
                        if (
                            half_road_width - max(car_to_middle, first_to_middle)
                            > safe_margin
                        ):
                            set_steering = +need_steering * steer_coeff / steer_factor
                        else:
                            set_steering = -need_steering * steer_coeff / steer_factor
                    elif car_to_middle < 0:
                        if (
                            half_road_width + min(car_to_middle, first_to_middle)
                            > safe_margin
                        ):
                            set_steering = -need_steering * steer_coeff / steer_factor
                        else:
                            set_steering = +need_steering * steer_coeff / steer_factor
                    else:
                        if first_to_middle < 0:
                            set_steering = +need_steering * steer_coeff / steer_factor
                        elif first_to_middle > 0:
                            set_steering = -need_steering * steer_coeff / steer_factor

                    # 장애물 회피는 예외적으로 감속 허용
                    if sensing_info.speed > 110:
                        set_throttle = min(set_throttle, 0.6)
                        set_brake = max(set_brake, 0.25)

                if self.is_debug:
                    print("set_steering", set_steering)

        # ===========================================================
        # 4. 충돌 상황 감지 후 복구
        # ===========================================================
        if sensing_info.speed > 30.0:
            self.is_accident = False
            self.recovery_count = 0
            self.accident_count = 0

        if (
            sensing_info.lap_progress > 0.5
            and self.is_accident is False
            and (-1.0 < sensing_info.speed < 1.0)
        ):
            self.accident_count += 1

        if self.accident_count > 6:
            self.is_accident = True

        if self.is_accident is True:
            set_steering = 0.02
            set_brake = 0.0
            set_throttle = -1
            self.recovery_count += 1

        if self.recovery_count > 20:
            self.is_accident = False
            self.recovery_count = 0
            self.accident_count = 0
            set_steering = 0
            set_brake = 0
            set_throttle = 0

        ###########################################################################
        # 최종 제어값 보정
        set_steering = self._clamp(set_steering, -1.0, 1.0)
        set_throttle = self._clamp(set_throttle, -1.0, 1.0)
        set_brake = self._clamp(set_brake, 0.0, 1.0)

        car_controls.steering = set_steering
        car_controls.throttle = set_throttle
        car_controls.brake = set_brake

        if self.is_debug:
            print(
                "[MyCar] target_speed:{}, max_curve:{}, is_hard_curve:{}".format(
                    target_speed, max_curve, is_hard_curve
                )
            )
            print(
                "[MyCar] steering:{}, throttle:{}, brake:{}".format(
                    car_controls.steering, car_controls.throttle, car_controls.brake
                )
            )

        #
        # Editing area ends
        # ==========================================================#
        return car_controls

    def set_player_name(self):
        player_name = ""
        return player_name


if __name__ == "__main__":
    print("[MyCar] Start Bot!")
    client = DrivingClient()
    return_code = client.run()
    print("[MyCar] End Bot!")

    exit(return_code)
