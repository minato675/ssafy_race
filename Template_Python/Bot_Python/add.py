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
        self.accident_count = 0  # 사고 횟수

        # 3번 개선: 이전 steering 값을 저장해서 조향을 부드럽게 만듦
        self.prev_steering = 0.0

        # 연속 잔커브 중앙 관통 모드 상태 확인용
        self.is_central_cut_mode = False

        #
        # Editing area ends
        # ==========================================================#
        super().__init__()

    def clamp(self, value, min_value, max_value):
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
            print("[MyCar] track_forward_angles: {}".format(sensing_info.track_forward_angles))
            print("[MyCar] track_forward_obstacles: {}".format(sensing_info.track_forward_obstacles))
            print("[MyCar] opponent_cars_info: {}".format(sensing_info.opponent_cars_info))
            print("[MyCar] distance_to_way_points: {}".format(sensing_info.distance_to_way_points))
            print("=========================================================")

        ###########################################################################
        # 기본 도로 정보
        ###########################################################################
        half_load_width = self.half_road_limit - 1.25  # 도로 반폭에서 차량 폭 여유 제외
        forward_angles = sensing_info.track_forward_angles

        # 방어 코드: 전방 각도가 비어 있으면 중앙으로 천천히 복귀
        if not forward_angles:
            car_controls.steering = self.clamp(-sensing_info.to_middle / 50, -1.0, 1.0)
            car_controls.throttle = 0.5
            car_controls.brake = 0.0
            return car_controls

        # 속도가 빠를수록 더 먼 구간까지 확인
        look_ahead = int(sensing_info.speed / 30) + 1
        look_ahead = self.clamp(look_ahead, 1, min(6, len(forward_angles)))
        checked_angles = forward_angles[:look_ahead]

        # 조향 기준 각도: 기존 방식처럼 속도에 따라 한 지점을 참고하되 인덱스 초과 방지
        angle_num = int(sensing_info.speed / 45)
        angle_num = min(angle_num, len(forward_angles) - 1)
        ref_angle = forward_angles[angle_num]

        # 커브 강도 계산
        max_curve = max(abs(angle) for angle in checked_angles)
        curve_angle = sum(checked_angles) / len(checked_angles)

        ###########################################################################
        # 추가 개선: 연속 잔커브 중앙 관통 모드 판단
        # - 작은 좌우 커브가 반복되면, 매번 레이싱 라인을 타기보다 중앙을 뚫고 감
        # - 부호 변화가 많고, 작은 커브가 많을 때 central-cut mode 활성화
        ###########################################################################
        zigzag_angles = forward_angles[:min(6, len(forward_angles))]

        sign_change_count = 0
        small_curve_count = 0
        valid_signs = []

        for angle in zigzag_angles:
            if abs(angle) < 20:
                small_curve_count += 1

            # 3도 이하는 거의 직선으로 보고 부호 판단에서 제외
            if angle > 3:
                valid_signs.append(1)
            elif angle < -3:
                valid_signs.append(-1)

        for i in range(len(valid_signs) - 1):
            if valid_signs[i] != valid_signs[i + 1]:
                sign_change_count += 1

        is_zigzag_small_curve = sign_change_count >= 2 and small_curve_count >= 4 and max_curve < 35
        self.is_central_cut_mode = is_zigzag_small_curve

        ###########################################################################
        # 1번 개선: 레이싱 라인 기반 target_middle 계산
        # - 직선에서는 중앙을 목표로 함
        # - 오른쪽 커브(+) 진입 전에는 왼쪽 바깥쪽(-)으로 위치
        # - 왼쪽 커브(-) 진입 전에는 오른쪽 바깥쪽(+)으로 위치
        # - 단, 연속 잔커브에서는 target_middle = 0으로 중앙 관통
        ###########################################################################
        target_middle = 0.0

        if is_zigzag_small_curve:
            # 잔커브가 좌우로 반복되면 차체를 흔들지 않고 중앙을 뚫고 감
            target_middle = 0.0
        elif abs(curve_angle) > 8:
            # 커브가 클수록 바깥쪽으로 더 붙되, 도로 밖으로 나가지 않게 제한
            racing_offset = self.clamp(max_curve / 18, 1.0, min(3.2, half_load_width - 0.5))

            if curve_angle > 0:
                # 오른쪽 커브: 왼쪽 바깥쪽으로 준비
                target_middle = -racing_offset
            else:
                # 왼쪽 커브: 오른쪽 바깥쪽으로 준비
                target_middle = racing_offset

        # 목표 라인과 현재 위치의 차이로 보정값 계산
        middle_error = target_middle - sensing_info.to_middle

        # 중앙 관통 모드에서는 중앙 복귀를 조금 더 적극적으로 적용
        if is_zigzag_small_curve:
            middle_add = middle_error / 32
        else:
            middle_add = middle_error / 40

        ###########################################################################
        # Steering 계산
        ###########################################################################
        steer_factor = sensing_info.speed * 1.5
        if sensing_info.speed > 70:
            steer_factor = sensing_info.speed * 0.85
        if sensing_info.speed > 100:
            steer_factor = sensing_info.speed * 0.7
        if steer_factor < 30:
            steer_factor = 30

        set_steering = (ref_angle - sensing_info.moving_angle) / (steer_factor + 0.001)
        set_steering += middle_add

        # 중앙 관통 모드에서는 잔커브에 과민반응하지 않도록 steering을 살짝 줄임
        if is_zigzag_small_curve:
            set_steering *= 0.75

        ###########################################################################
        # 2번 개선: 목표 속도 기반 throttle/brake 제어
        ###########################################################################
        if max_curve < 10:
            target_speed = 160
        elif max_curve < 25:
            target_speed = 140
        elif max_curve < 40:
            target_speed = 115
        elif max_curve < 60:
            target_speed = 90
        elif max_curve < 80:
            target_speed = 70
        else:
            target_speed = 55

        # 중앙 관통 모드에서는 커브가 작고 연속적이므로 속도를 너무 많이 죽이지 않음
        if is_zigzag_small_curve:
            target_speed = max(target_speed, 135)

        speed_gap = sensing_info.speed - target_speed

        set_brake = 0.0
        if speed_gap > 25:
            set_throttle = 0.25
            set_brake = 0.85
        elif speed_gap > 15:
            set_throttle = 0.35
            set_brake = 0.55
        elif speed_gap > 5:
            set_throttle = 0.55
            set_brake = 0.25
        else:
            set_throttle = 1.0
            set_brake = 0.0

        # 저속에서는 재가속 우선
        if sensing_info.speed < 60 and not self.is_accident:
            set_throttle = max(set_throttle, 0.9)
            set_brake = 0.0

        # 매우 급한 커브에서는 steering을 조금 더 강하게 보조
        if max_curve > 80:
            if set_steering > 0:
                set_steering += 0.25
            else:
                set_steering -= 0.25

        ###########################################################################
        # 장애물 피하기: 기존 로직 유지
        ###########################################################################
        if sensing_info.track_forward_obstacles:
            first_obstacles = sensing_info.track_forward_obstacles[0]
            first_dist = first_obstacles['dist']

            if first_dist < 30:
                first_to_middle = first_obstacles['to_middle']
                car_to_middle = sensing_info.to_middle
                diff_to_middle = first_to_middle - car_to_middle
                steer_coeff = 50

                if self.is_debug:
                    print('diff_to_middle', diff_to_middle)

                if abs(diff_to_middle) < 2.2:
                    need_steering = (2.2 - abs(diff_to_middle)) / 2.2

                    if car_to_middle > 0:
                        if 5 - max(car_to_middle, first_to_middle) > 2.2:
                            set_steering = +need_steering * steer_coeff / steer_factor
                        else:
                            set_steering = -need_steering * steer_coeff / steer_factor

                    elif car_to_middle < 0:
                        if 5 + min(car_to_middle, first_to_middle) > 2.2:
                            set_steering = -need_steering * steer_coeff / steer_factor
                        else:
                            set_steering = +need_steering * steer_coeff / steer_factor

                    else:
                        if first_to_middle < 0:
                            set_steering = +need_steering * steer_coeff / steer_factor
                        elif first_to_middle > 0:
                            set_steering = -need_steering * steer_coeff / steer_factor

                if self.is_debug:
                    print('set_steering', set_steering)

        ###########################################################################
        # 충돌 상황 감지 후 회피 하기
        ###########################################################################
        if sensing_info.speed > 30.0:
            self.is_accident = False
            self.recovery_count = 0
            self.accident_count = 0

        if sensing_info.lap_progress > 0.5 and self.is_accident == False and (-1.0 < sensing_info.speed < 1.0):
            self.accident_count += 1

        if self.accident_count > 6:
            self.is_accident = True

        if self.is_accident == True:
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
            self.prev_steering = 0.0

        ###########################################################################
        # 3번 개선: steering smoothing
        # - 일반 주행: 0.65
        # - 연속 잔커브 중앙 관통 모드: 0.78로 더 부드럽게
        # 사고 복구 중에는 후진 제어가 우선이므로 smoothing을 적용하지 않음
        ###########################################################################
        if not self.is_accident:
            if is_zigzag_small_curve:
                smooth_rate = 0.78
            else:
                smooth_rate = 0.65

            set_steering = self.prev_steering * smooth_rate + set_steering * (1 - smooth_rate)
            self.prev_steering = set_steering

        # 최종값 범위 제한
        set_steering = self.clamp(set_steering, -1.0, 1.0)
        set_throttle = self.clamp(set_throttle, -1.0, 1.0)
        set_brake = self.clamp(set_brake, 0.0, 1.0)

        car_controls.steering = set_steering
        car_controls.throttle = set_throttle
        car_controls.brake = set_brake

        if self.is_debug:
            print("[MyCar] mode:{}, sign_changes:{}, target_middle:{:.2f}, target_speed:{}, max_curve:{:.2f}, steering:{:.3f}, throttle:{:.3f}, brake:{:.3f}".format(
                "CENTRAL_CUT" if is_zigzag_small_curve else "RACING_LINE",
                sign_change_count,
                target_middle,
                target_speed,
                max_curve,
                car_controls.steering,
                car_controls.throttle,
                car_controls.brake
            ))

        #
        # Editing area ends
        # ==========================================================#
        return car_controls

    def set_player_name(self):
        player_name = ""
        return player_name


if __name__ == '__main__':
    print("[MyCar] Start Bot!")
    client = DrivingClient()
    return_code = client.run()
    print("[MyCar] End Bot!")

    exit(return_code)
