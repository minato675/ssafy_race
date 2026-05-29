import math
import os
import time

from DrivingInterface.drive_controller import DrivingController

class DrivingClient(DrivingController):
    def __init__(self):
        # =========================================================== #
        #  Area for member variables =============================== #
        # =========================================================== #
        # Editing area starts from here
        #

        self.is_debug = False
        self.recovery_count = 0
        self.line_target = 0.0
        self.prev_steering = 0.0
        self.log_tick = 0
        self.log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "driving_log.csv")

        with open(self.log_path, "w", encoding="utf-8") as log_file:
            log_file.write(
                "time,mode,x,y,z,speed,gear,to_middle,moving_angle,lap_progress,"
                "line_target,curve_strength,heading_error,steering,throttle,brake,collided\n"
            )

        # api or keyboard
        self.enable_api_control = True # True(Controlled by code) /False(Controlled by keyboard)
        super().set_enable_api_control(self.enable_api_control)

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

            print("[MyCar] track_forward_angles: {}".format(sensing_info.track_forward_angles))
            print("[MyCar] track_forward_obstacles: {}".format(sensing_info.track_forward_obstacles))
            print("[MyCar] opponent_cars_info: {}".format(sensing_info.opponent_cars_info))
            print("[MyCar] distance_to_way_points: {}".format(sensing_info.distance_to_way_points))
            print("=========================================================")

        ###########################################################################

        speed = max(0.0, sensing_info.speed)
        forward_angles = sensing_info.track_forward_angles

        # Do not reverse automatically while tuning; repeated collision signals can
        # otherwise leave the car stuck in R gear.
        if sensing_info.collided and abs(sensing_info.speed) < 15:
            self.recovery_count = 3

        if self.recovery_count > 0:
            self.recovery_count -= 1
            car_controls.steering = 0
            car_controls.throttle = 0.25
            car_controls.brake = 0.15
            self.prev_steering = car_controls.steering
            self.log_driving_state(sensing_info, car_controls, 0, 0, "recovery")
            return car_controls

        def clamp(value, low, high):
            return max(low, min(high, value))

        def average(values):
            return sum(values) / len(values) if values else 0

        def steering_response(speed_kmh):
            # Measured on this simulator: steering 1.0 roughly produces this
            # yaw-rate by speed band. Higher values mean less steering is needed.
            table = [
                (30.0, 66.0),
                (50.0, 63.0),
                (70.0, 86.0),
                (90.0, 92.0),
                (120.0, 100.0),
            ]

            if speed_kmh <= table[0][0]:
                return table[0][1]
            for idx in range(1, len(table)):
                prev_speed, prev_response = table[idx - 1]
                next_speed, next_response = table[idx]
                if speed_kmh <= next_speed:
                    ratio = (speed_kmh - prev_speed) / (next_speed - prev_speed)
                    return prev_response + ((next_response - prev_response) * ratio)
            return table[-1][1]

        # Use a small window rather than one waypoint angle; single points make the
        # steering chase noise and create side-to-side oscillation.
        near_angle = average(forward_angles[:3])
        target_angle = average(forward_angles[4:9]) if len(forward_angles) >= 9 else average(forward_angles)
        road_angle = (near_angle * 0.30) + (target_angle * 0.70)
        heading_error = road_angle - sensing_info.moving_angle

        # Out-in line: start outside before a curve, then gradually clip inside.
        road_half_width = max(1.0, self.half_road_limit - 1.25)
        near_curve = average(forward_angles[:3])
        mid_curve = average(forward_angles[3:8])
        far_curve = average(forward_angles[8:14])
        curve_probe = max([near_curve, mid_curve, far_curve], key=lambda angle: abs(angle))
        curve_sign = 1 if curve_probe > 0 else -1 if curve_probe < 0 else 0

        scan_count = clamp(int(speed / 25) + 3, 3, min(10, len(forward_angles)))
        curve_strength = max([abs(angle) for angle in forward_angles[:scan_count]]) if forward_angles else 0

        raw_line_target = 0.0
        if curve_strength > 18 and curve_sign != 0:
            line_width = road_half_width * clamp(curve_strength / 170, 0.08, 0.18)
            inside_target = curve_sign * line_width
            outside_target = -curve_sign * line_width

            # Out-in line: stay outside while the curve is ahead, then move inside
            # as the near road angle becomes the dominant curve signal.
            inside_ratio = clamp(abs(near_curve) / (abs(curve_probe) + 0.001), 0.0, 1.0)

            raw_line_target = (outside_target * (1 - inside_ratio)) + (inside_target * inside_ratio)

        edge_ratio = abs(sensing_info.to_middle) / road_half_width
        if edge_ratio > 0.55:
            raw_line_target = 0.0

        self.line_target = (self.line_target * 0.97) + (raw_line_target * 0.03)
        lateral_error = self.line_target - sensing_info.to_middle
        lookahead_distance = clamp((speed / 3.6) * 1.25, 18.0, 60.0)

        if edge_ratio < 0.42:
            lateral_gain = 0.30
        elif edge_ratio < 0.62:
            lateral_gain = 0.50
        elif edge_ratio < 0.78:
            lateral_gain = 0.75
        else:
            lateral_gain = 1.80

        lateral_angle = math.degrees(math.atan2(lateral_error * lateral_gain, lookahead_distance))
        desired_angle_limit = 60.0 if edge_ratio > 0.78 else 45.0
        desired_angle = clamp(heading_error + lateral_angle, -desired_angle_limit, desired_angle_limit)
        response = steering_response(speed)
        if edge_ratio > 0.78:
            response_horizon = 0.55
        elif edge_ratio > 0.62:
            response_horizon = 0.78
        else:
            response_horizon = 1.0 if speed > 65 else 1.25
        desired_yaw_rate = desired_angle / response_horizon
        set_steering = clamp(desired_yaw_rate / response, -0.85, 0.85)

        # Smooth and rate-limit steering so the car keeps grip instead of hunting.
        smoothing = 0.52 if edge_ratio > 0.78 else 0.72
        set_steering = (self.prev_steering * smoothing) + (set_steering * (1 - smoothing))
        if edge_ratio > 0.78:
            max_steering_step = 0.110
        else:
            max_steering_step = 0.035 if speed > 60 else 0.070
        steering_delta = clamp(set_steering - self.prev_steering, -max_steering_step, max_steering_step)
        if edge_ratio > 0.78:
            steering_limit = 0.82
        else:
            steering_limit = 0.45 if speed > 70 else 0.62
        set_steering = clamp(self.prev_steering + steering_delta, -steering_limit, steering_limit)
        self.prev_steering = set_steering

        # Keep speed up: lift first, brake only when the curve is too tight for the current speed.
        target_speed = 115
        if curve_strength > 80:
            target_speed = 48
        elif curve_strength > 55:
            target_speed = 58
        elif curve_strength > 35:
            target_speed = 72
        elif curve_strength > 20:
            target_speed = 88

        if edge_ratio > 0.78:
            target_speed = min(target_speed, 30)
        elif edge_ratio > 0.65 or abs(sensing_info.moving_angle) > 28:
            target_speed = min(target_speed, 55)
        elif edge_ratio > 0.45 or abs(sensing_info.moving_angle) > 18:
            target_speed = min(target_speed, 70)

        if speed < target_speed - 8:
            set_throttle = 1.0
            set_brake = 0.0
        elif speed > target_speed + 8:
            set_throttle = 0.20
            set_brake = clamp((speed - target_speed) / 55, 0.12, 0.65)
        else:
            set_throttle = 0.75
            set_brake = 0.0

        if abs(set_steering) > 0.48 and speed > 85:
            set_throttle = min(set_throttle, 0.58)
        if abs(set_steering) > 0.65 and speed > 95:
            set_throttle = min(set_throttle, 0.45)
            set_brake = max(set_brake, 0.08)

        if edge_ratio > 0.78:
            if speed < 20:
                set_throttle = max(set_throttle, 0.65)
                set_brake = 0.0
            else:
                set_throttle = min(set_throttle, 0.25)
                set_brake = max(set_brake, 0.20)

        car_controls.steering = set_steering
        car_controls.throttle = set_throttle
        car_controls.brake = set_brake

        self.log_driving_state(sensing_info, car_controls, curve_strength, desired_angle, "drive")
        
        if self.is_debug:
            print("[MyCar] steering:{}, throttle:{}, brake:{}"\
                  .format(car_controls.steering, car_controls.throttle, car_controls.brake))

        #
        # Editing area ends
        # ==========================================================#
        return car_controls

    def log_driving_state(self, sensing_info, car_controls, curve_strength, heading_error, mode):
        self.log_tick += 1

        # The control loop runs every 0.1s, so log about once per second.
        if self.log_tick % 10 != 0:
            return

        try:
            car_state = self.client.getCarState(self.player_name)
            position = car_state.kinematics_estimated.position

            line = (
                "{:.3f},{},{:.3f},{:.3f},{:.3f},{:.3f},{},{:.3f},{:.3f},{:.3f},"
                "{:.3f},{:.3f},{:.3f},{:.3f},{:.3f},{:.3f},{}\n"
            ).format(
                time.time(),
                mode,
                position.x_val,
                position.y_val,
                position.z_val,
                car_state.speed,
                car_state.gear,
                sensing_info.to_middle,
                sensing_info.moving_angle,
                sensing_info.lap_progress,
                self.line_target,
                curve_strength,
                heading_error,
                car_controls.steering,
                car_controls.throttle,
                car_controls.brake,
                sensing_info.collided,
            )

            with open(self.log_path, "a", encoding="utf-8") as log_file:
                log_file.write(line)
        except Exception:
            pass

    def getPlayerName(self, json_data):
        if "Vehicles" in json_data and "Car1" in json_data["Vehicles"]:
            self.player_name = "Car1"
        else:
            self.player_name = ""
        print("[DrivingController] Player name : {}".format(self.player_name))

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
    print("[MyCar] Start Bot! (PYTHON)")

    client = DrivingClient()
    return_code = client.run()

    print("[MyCar] End Bot! (PYTHON)")

    exit(return_code)
