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

        # 조향 smoothing을 위한 이전 steering 값 저장
        self.prev_steering = 0.0

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

        # 도로의 실제 폭의 1/2 로 계산됨
        half_load_width = self.half_road_limit - 1.25

        # 차량 핸들 조정을 위해 참고할 전방의 커브 값 가져오기
        angle_num = int(sensing_info.speed / 45)

        # 속도가 너무 빨라져도 리스트 범위를 벗어나지 않도록 보정
        if angle_num >= len(sensing_info.track_forward_angles):
            angle_num = len(sensing_info.track_forward_angles) - 1

        ref_angle = sensing_info.track_forward_angles[angle_num]

        # 차량의 차선 중앙 정렬을 위한 미세 조정 값 계산
        middle_add = (sensing_info.to_middle / 80) * -1

        # 전방의 커브 각도에 따라 throttle 값을 조절하여 속도를 제어함
        throttle_factor = 0.6 / (abs(ref_angle) + 0.1)

        if throttle_factor > 0.11:
            throttle_factor = 0.11

        set_throttle = 0.7 + throttle_factor

        if sensing_info.speed < 60:
            set_throttle = 0.9

        # 차량의 Speed 에 따라서 핸들을 돌리는 값을 조정함
        steer_factor = sensing_info.speed * 1.5

        if sensing_info.speed > 70:
            steer_factor = sensing_info.speed * 0.85

        if sensing_info.speed > 100:
            steer_factor = sensing_info.speed * 0.7

        # 기본 steering 계산
        set_steering = (ref_angle - sensing_info.moving_angle) / (steer_factor + 0.001)

        # 차선 중앙정렬 값을 추가로 고려함
        set_steering += middle_add

        # 긴급 및 예외 상황 처리 초기화
        full_throttle = True
        emergency_brake = False

        # 전방 커브의 각도가 큰 경우 속도를 제어함
        road_range = int(sensing_info.speed / 30)

        # road_range가 리스트 길이를 넘지 않도록 보정
        if road_range >= len(sensing_info.track_forward_angles):
            road_range = len(sensing_info.track_forward_angles) - 1

        for i in range(0, road_range):
            fwd_angle = abs(sensing_info.track_forward_angles[i])

            if fwd_angle > 45:
                full_throttle = False

            if fwd_angle > 80:
                emergency_brake = True
                break

        # brake, throttle 제어
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

        # 급커브에서는 steering 추가 보정
        if emergency_brake:
            if set_steering > 0:
                set_steering += 0.3
            else:
                set_steering -= 0.3

        # 장애물 피하기
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

                if abs(diff_to_middle) < 2.2:
                    need_steering = (2.2 - abs(diff_to_middle)) / 2.2

                    if car_to_middle > 0:
                        # 차가 오른쪽에 있을 때 오른쪽 공간이 충분하면 오른쪽, 아니면 왼쪽
                        if 5 - max(car_to_middle, first_to_middle) > 2.2:
                            set_steering = (
                                +need_steering * steer_coeff / (steer_factor + 0.001)
                            )
                        else:
                            set_steering = (
                                -need_steering * steer_coeff / (steer_factor + 0.001)
                            )

                    elif car_to_middle < 0:
                        # 차가 왼쪽에 있을 때 왼쪽 공간이 충분하면 왼쪽, 아니면 오른쪽
                        if 5 + min(car_to_middle, first_to_middle) > 2.2:
                            set_steering = (
                                -need_steering * steer_coeff / (steer_factor + 0.001)
                            )
                        else:
                            set_steering = (
                                +need_steering * steer_coeff / (steer_factor + 0.001)
                            )

                    else:
                        # 차량이 중앙에 있는 경우 장애물 반대 방향으로 회피
                        if first_to_middle < 0:
                            set_steering = (
                                +need_steering * steer_coeff / (steer_factor + 0.001)
                            )

                        if first_to_middle > 0:
                            set_steering = (
                                -need_steering * steer_coeff / (steer_factor + 0.001)
                            )

                if self.is_debug:
                    print("set_steering before smoothing", set_steering)

        # steering 값 제한
        if set_steering > 1:
            set_steering = 1

        if set_steering < -1:
            set_steering = -1

        ###########################################################################
        # 조향 smoothing 적용
        #
        # 기존 방식:
        #   매 프레임 계산된 set_steering을 바로 적용
        #
        # 개선 방식:
        #   이전 steering과 현재 steering을 섞어서 부드럽게 적용
        #
        # smooth_rate가 클수록 이전 steering을 더 많이 유지함
        # 0.6 ~ 0.75 정도가 무난함
        ###########################################################################

        smooth_rate = 0.65
        set_steering = self.prev_steering * smooth_rate + set_steering * (
            1 - smooth_rate
        )

        # smoothing 후에도 steering 범위 제한
        if set_steering > 1:
            set_steering = 1

        if set_steering < -1:
            set_steering = -1

        ###########################################################################
        # 충돌 상황 감지 후 회피 하기
        ###########################################################################

        # 1. 30Km/h 이상의 속도로 달리는 경우 정상적인 상황으로 간주
        if sensing_info.speed > 30.0:
            self.is_accident = False
            self.recovery_count = 0
            self.accident_count = 0

        # 2. 레이싱 시작 후 Speed 1km/h 이하가 된 경우 사고 상황 체크
        if (
            sensing_info.lap_progress > 0.5
            and self.is_accident == False
            and sensing_info.speed < 1.0
            and sensing_info.speed > -1.0
        ):
            self.accident_count += 1

        # 3. Speed 1km/h 이하인 상태가 지속된 경우 충돌로 판단
        if self.accident_count > 6:
            self.is_accident = True

        # 4. 충돌로 멈춘 경우 후진 시작
        if self.is_accident == True:
            set_steering = 0.02
            set_brake = 0.0
            set_throttle = -1
            self.recovery_count += 1

            # 사고 복구 중에는 smoothing 값도 초기화에 가깝게 유지
            self.prev_steering = set_steering

        # 5. 어느 정도 후진이 되었을 때 정상 주행 상태로 복귀
        if self.recovery_count > 20:
            self.is_accident = False
            self.recovery_count = 0
            self.accident_count = 0
            set_steering = 0
            set_brake = 0
            set_throttle = 0

            # 복구 완료 후 이전 steering도 초기화
            self.prev_steering = 0.0

        ###########################################################################

        # 최종 steering 값을 다음 프레임 smoothing에 사용하기 위해 저장
        self.prev_steering = set_steering

        # 최종 제어값 적용
        car_controls.steering = set_steering
        car_controls.throttle = set_throttle
        car_controls.brake = set_brake

        if self.is_debug:
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
