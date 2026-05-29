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
        half_load_width = self.half_road_limit - 1.25
        forward_angles = sensing_info.track_forward_angles

        # 속도에 따라 참고할 전방 각도 선택. 인덱스 초과 방지.
        angle_num = int(sensing_info.speed / 45)
        angle_num = min(angle_num, len(forward_angles) - 1)
        ref_angle = forward_angles[angle_num]

        # 중앙 복귀 보정
        middle_add = (sensing_info.to_middle / 80) * -1

        # 차량 속도에 따른 steering 민감도 조절
        steer_factor = sensing_info.speed * 1.5
        if sensing_info.speed > 70:
            steer_factor = sensing_info.speed * 0.85
        if sensing_info.speed > 100:
            steer_factor = sensing_info.speed * 0.7
        if steer_factor < 30:
            steer_factor = 30

        # 기본 steering 계산
        set_steering = (ref_angle - sensing_info.moving_angle) / (steer_factor + 0.001)
        set_steering += middle_add

        ###########################################################################
        # 2번 개선: 커브 각도 기반이 아니라 목표 속도 기반으로 throttle/brake 제어
        ###########################################################################

        # 속도가 빠를수록 더 먼 구간까지 확인해서 미리 감속
        look_ahead = int(sensing_info.speed / 30) + 1
        look_ahead = self.clamp(look_ahead, 1, min(6, len(forward_angles)))

        checked_angles = forward_angles[:look_ahead]
        max_curve = max(abs(angle) for angle in checked_angles)

        # 전방 커브 강도에 따라 목표 속도 설정
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

        speed_gap = sensing_info.speed - target_speed

        # 목표 속도보다 빠르면 감속, 느리면 가속
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

        # 너무 저속이면 복구 가속
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
        # 사고 복구 중에는 후진 제어가 우선이므로 smoothing을 적용하지 않음
        ###########################################################################
        if not self.is_accident:
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
            print("[MyCar] target_speed:{}, max_curve:{}, steering:{}, throttle:{}, brake:{}".format(
                target_speed, max_curve, car_controls.steering, car_controls.throttle, car_controls.brake
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