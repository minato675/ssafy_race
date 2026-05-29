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

        #
        # Editing area ends
        # ==========================================================#
        super().__init__()

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
        # 기본 도로 정보
        ###########################################################################

        # 도로의 실제 폭의 1/2로 계산됨
        # 도로폭에서 차량 폭과 여유 공간을 뺀 값
        half_load_width = self.half_road_limit - 1.25

        # 속도에 따라 참고할 전방 각도 index 결정
        angle_num = int(sensing_info.speed / 45)

        # index 초과 방지
        if angle_num >= len(sensing_info.track_forward_angles):
            angle_num = len(sensing_info.track_forward_angles) - 1

        ref_angle = sensing_info.track_forward_angles[angle_num]

        ###########################################################################
        # 1. 레이싱 라인 기반 목표 위치 계산
        ###########################################################################
        # 기존 방식:
        # middle_add = (sensing_info.to_middle / 80) * -1
        #
        # 개선 방식:
        # 도로 중앙을 무조건 따라가지 않고,
        # 커브 방향에 따라 바깥쪽 라인을 목표로 잡음.
        #
        # 오른쪽 커브: 왼쪽 바깥쪽으로 이동
        # 왼쪽 커브: 오른쪽 바깥쪽으로 이동
        # 직선: 중앙 유지

        # 속도가 빠를수록 조금 더 먼 커브까지 보고 판단
        look_ahead = int(sensing_info.speed / 40) + 3
        if look_ahead > len(sensing_info.track_forward_angles):
            look_ahead = len(sensing_info.track_forward_angles)

        # 전방 커브 평균값 계산
        forward_angles = sensing_info.track_forward_angles[:look_ahead]
        curve_angle = sum(forward_angles) / len(forward_angles)

        # 기본 목표 위치는 중앙
        target_middle = 0.0

        # 커브 강도에 따라 바깥쪽으로 얼마나 붙을지 결정
        curve_strength = abs(curve_angle)

        if curve_strength > 8:
            # 최대 이동 목표값
            # 도로 밖으로 너무 붙지 않도록 제한
            racing_line_offset = min(half_load_width * 0.65, 3.0)

            if curve_strength > 35:
                racing_line_offset = min(half_load_width * 0.75, 3.5)

            # 오른쪽 커브이면 왼쪽 바깥쪽으로
            if curve_angle > 0:
                target_middle = -racing_line_offset

            # 왼쪽 커브이면 오른쪽 바깥쪽으로
            else:
                target_middle = racing_line_offset

        # 목표 위치와 현재 위치 차이
        middle_error = target_middle - sensing_info.to_middle

        # 목표 위치로 가기 위한 조향 보정값
        # 값이 너무 커지면 흔들릴 수 있으므로 제한
        middle_add = middle_error / 40

        if middle_add > 0.12:
            middle_add = 0.12
        elif middle_add < -0.12:
            middle_add = -0.12

        ###########################################################################
        # throttle 제어
        ###########################################################################

        # 커브 각도가 클수록 엑셀을 줄임
        throttle_factor = 0.6 / (abs(ref_angle) + 0.1)

        if throttle_factor > 0.11:
            throttle_factor = 0.11

        set_throttle = 0.7 + throttle_factor

        # 저속에서는 빠르게 속도 회복
        if sensing_info.speed < 60:
            set_throttle = 0.9

        ###########################################################################
        # steering 제어
        ###########################################################################

        # 속도에 따라 조향 민감도 조절
        steer_factor = sensing_info.speed * 1.5

        if sensing_info.speed > 70:
            steer_factor = sensing_info.speed * 0.85

        if sensing_info.speed > 100:
            steer_factor = sensing_info.speed * 0.7

        # 정지 상태에서 steer_factor가 너무 작아지는 것 방지
        if steer_factor < 40:
            steer_factor = 40

        # 전방 커브 각도와 현재 차량 진행 각도 차이를 기반으로 조향 계산
        set_steering = (ref_angle - sensing_info.moving_angle) / (steer_factor + 0.001)

        # 레이싱 라인 목표 위치 보정 추가
        set_steering += middle_add

        ###########################################################################
        # 급커브 대응
        ###########################################################################

        full_throttle = True
        emergency_brake = False

        # 속도가 빠를수록 더 먼 구간까지 확인
        road_range = int(sensing_info.speed / 30)

        if road_range > len(sensing_info.track_forward_angles):
            road_range = len(sensing_info.track_forward_angles)

        for i in range(0, road_range):
            fwd_angle = abs(sensing_info.track_forward_angles[i])

            if fwd_angle > 45:
                full_throttle = False

            if fwd_angle > 80:
                emergency_brake = True
                break

        set_brake = 0.0

        if full_throttle == False:
            if sensing_info.speed > 100:
                set_brake = 0.3

            if sensing_info.speed > 120:
                set_throttle = 0.7
                set_brake = 0.7

            if sensing_info.speed > 130:
                set_throttle = 0.5
                set_brake = 1.0

        # 매우 급한 커브에서는 조향을 조금 더 강하게 보정
        if emergency_brake:
            if set_steering > 0:
                set_steering += 0.3
            else:
                set_steering -= 0.3

        ###########################################################################
        # 장애물 회피
        ###########################################################################

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

                # 차량 폭 + 여유 거리
                safe_space = 2.2

                if abs(diff_to_middle) < safe_space:
                    need_steering = (safe_space - abs(diff_to_middle)) / safe_space

                    # 차량이 오른쪽에 있는 경우
                    if car_to_middle > 0:
                        # 오른쪽에 여유가 있으면 오른쪽으로 회피
                        if (
                            half_load_width - max(car_to_middle, first_to_middle)
                            > safe_space
                        ):
                            set_steering = +need_steering * steer_coeff / steer_factor
                        # 아니면 왼쪽으로 회피
                        else:
                            set_steering = -need_steering * steer_coeff / steer_factor

                    # 차량이 왼쪽에 있는 경우
                    elif car_to_middle < 0:
                        # 왼쪽에 여유가 있으면 왼쪽으로 회피
                        if (
                            half_load_width + min(car_to_middle, first_to_middle)
                            > safe_space
                        ):
                            set_steering = -need_steering * steer_coeff / steer_factor
                        # 아니면 오른쪽으로 회피
                        else:
                            set_steering = +need_steering * steer_coeff / steer_factor

                    # 차량이 중앙 근처에 있는 경우
                    else:
                        # 장애물이 왼쪽에 있으면 오른쪽으로 회피
                        if first_to_middle < 0:
                            set_steering = +need_steering * steer_coeff / steer_factor

                        # 장애물이 오른쪽에 있으면 왼쪽으로 회피
                        elif first_to_middle > 0:
                            set_steering = -need_steering * steer_coeff / steer_factor

                if self.is_debug:
                    print("set_steering", set_steering)

        ###########################################################################
        # steering 값 제한
        ###########################################################################

        if set_steering > 1:
            set_steering = 1
        elif set_steering < -1:
            set_steering = -1

        ###########################################################################
        # 충돌 상황 감지 및 복구
        ###########################################################################

        # 1. 30km/h 이상의 속도로 달리는 경우 정상 상황으로 간주
        if sensing_info.speed > 30.0:
            self.is_accident = False
            self.recovery_count = 0
            self.accident_count = 0

        # 2. 레이싱 시작 후 속도가 거의 0이면 사고 가능성 체크
        if (
            sensing_info.lap_progress > 0.5
            and self.is_accident == False
            and sensing_info.speed < 1.0
            and sensing_info.speed > -1.0
        ):
            self.accident_count += 1

        # 3. 정지 상태가 지속되면 사고로 판단
        if self.accident_count > 6:
            self.is_accident = True

        # 4. 사고 상태이면 후진
        if self.is_accident == True:
            set_steering = 0.02
            set_brake = 0.0
            set_throttle = -1
            self.recovery_count += 1

        # 5. 일정 시간 후진 후 정상 주행 상태로 복귀
        if self.recovery_count > 20:
            self.is_accident = False
            self.recovery_count = 0
            self.accident_count = 0
            set_steering = 0
            set_brake = 0
            set_throttle = 0

        ###########################################################################
        # 최종 제어값 적용
        ###########################################################################

        car_controls.steering = set_steering
        car_controls.throttle = set_throttle
        car_controls.brake = set_brake

        if self.is_debug:
            print(
                "[MyCar] target_middle:{}, curve_angle:{}".format(
                    target_middle, curve_angle
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


if __name__ == "__main__":
    print("[MyCar] Start Bot!")
    client = DrivingClient()
    return_code = client.run()
    print("[MyCar] End Bot!")

    exit(return_code)
