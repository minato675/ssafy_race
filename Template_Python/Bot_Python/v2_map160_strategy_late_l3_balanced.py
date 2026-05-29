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

        # 속도가 빠를수록 더 먼 구간까지 확인하여 미리 감속한다.
        look_ahead = int(sensing_info.speed / 26) + 1
        look_ahead = self._clamp(look_ahead, 1, min(7, len(sensing_info.track_forward_angles)))

        forward_angles = sensing_info.track_forward_angles[:look_ahead]
        max_curve = max(abs(angle) for angle in forward_angles)

        # 커브 강도별 목표 속도 설정
        # 값이 높을수록 공격적인 주행, 낮을수록 안정적인 주행
        if max_curve < 10:
            target_speed = 190
        elif max_curve < 25:
            target_speed = 155
        elif max_curve < 40:
            target_speed = 120
        elif max_curve < 60:
            target_speed = 95
        elif max_curve < 80:
            target_speed = 75
        else:
            target_speed = 55

        hairpin_name = None
        hairpin_target_speed = None
        lap_progress = sensing_info.lap_progress % 100.0

        # Map 160 hairpin zones from waypoint curvature clustering.
        # Difficulty: hairpin 2 > hairpin 4 > hairpin 1 == hairpin 3.
        if 16.8 <= lap_progress <= 21.8:
            hairpin_name = "hp2"
            hairpin_target_speed = 74
        elif 44.5 <= lap_progress <= 49.2:
            hairpin_name = "hp1"
            hairpin_target_speed = 92
        elif 60.8 <= lap_progress <= 65.8:
            hairpin_name = "hp3"
            hairpin_target_speed = 92
        elif 82.0 <= lap_progress <= 92.5:
            hairpin_name = "hp4"
            hairpin_target_speed = 82

        if hairpin_target_speed is not None:
            target_speed = hairpin_target_speed

        speed_gap = sensing_info.speed - target_speed

        # 현재 속도가 목표 속도보다 빠르면 감속, 느리면 가속
        if speed_gap > 35:
            set_throttle = 0.2
            set_brake = 1.0
        elif speed_gap > 25:
            set_throttle = 0.3
            set_brake = 0.8
        elif speed_gap > 15:
            set_throttle = 0.45
            set_brake = 0.5
        elif speed_gap > 5:
            set_throttle = 0.65
            set_brake = 0.2
        else:
            set_throttle = 1.0
            set_brake = 0.0

        # 출발/저속 구간에서는 속도 회복 우선
        if hairpin_target_speed is None and sensing_info.speed < 55 and max_curve < 50:
            set_throttle = 1.0
            set_brake = 0.0

        if hairpin_target_speed is not None:
            hairpin_gap = sensing_info.speed - hairpin_target_speed
            if hairpin_gap > 28:
                set_throttle = min(set_throttle, 0.14)
                set_brake = max(set_brake, 0.85)
            elif hairpin_gap > 20:
                set_throttle = min(set_throttle, 0.3)
                set_brake = max(set_brake, 0.55)
            elif hairpin_gap > 10:
                set_throttle = min(set_throttle, 0.58)
                set_brake = max(set_brake, 0.24)

        # 매우 급한 커브에서는 조향을 조금 더 강하게 넣어 탈출 실패를 줄인다.
        if max_curve > 80:
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
        set_steering = self._clamp(set_steering, -1.0, 1.0)
        set_throttle = self._clamp(set_throttle, -1.0, 1.0)
        set_brake = self._clamp(set_brake, 0.0, 1.0)

        car_controls.steering = set_steering
        car_controls.throttle = set_throttle
        car_controls.brake = set_brake

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
