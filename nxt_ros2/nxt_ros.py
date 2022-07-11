import rclpy
import rclpy.executors
import rclpy.node
import rclpy.action
import rclpy.time
import rclpy.duration
import rclpy.clock
import rclpy.callback_groups
import rcl_interfaces.msg

import nxt_msgs2.msg
import nxt_msgs2.action
import nxt_msgs2.srv
import sensor_msgs.msg
import std_msgs.msg

import nxt
import nxt.locator
import nxt.brick
import nxt.sensor
import nxt.sensor.generic
import nxt.motor

from typing import Dict, List, Union
import math
import threading
import enum


class MotorType(enum.Enum):
    wheel_motor_r = "wheel_motor_r"
    wheel_motor_l = "wheel_motor_l"
    other = "other"


class SensorConfigs:
    def __init__(self):
        self.sensor_names: List[str] = []
        self.sensor_types: List[str] = []
        self.sensor_ports: List[str] = []


class MotorConfigs:
    def __init__(self):
        self.motor_ports: List[str] = []
        self.motor_names: List[str] = []
        self.motor_types: List[str] = []
        self.motor_mimic_names: List[str] = []
        self.motor_mimic_gear_ratios: List[int] = []
        self.invert_efforts: List[bool] = []


class TouchSensor(rclpy.node.Node):
    def __init__(self, brick: nxt.brick.Brick, name: str, port: nxt.sensor.Port):
        super().__init__(name)

        self._sensor = brick.get_sensor(port, nxt.sensor.generic.Touch)

        self._publisher = self.create_publisher(
            nxt_msgs2.msg.Touch, name, 10)

        timer_period = 0.3  # seconds
        self._timer = self.create_timer(timer_period, self.measure)

    def measure(self):
        msg = nxt_msgs2.msg.Touch()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.touch = self._sensor.get_sample()
        self._publisher.publish(msg)

    def destroy_node(self):
        return super().destroy_node()


class UltraSonicSensor(rclpy.node.Node):
    def __init__(self, brick: nxt.brick.Brick, name: str, port: nxt.sensor.Port):
        super().__init__(name)

        # Default values for LEGO Mindstorms NXT ultrasonic sensor
        self.declare_parameters(namespace="", parameters=[
            ('field_of_view', 0.5235988),  # 30 degrees
            ('min_range', 0.07),  # meters
            ('max_range', 2.54)])  # meters

        self._sensor = brick.get_sensor(port, nxt.sensor.generic.Ultrasonic)

        self._publisher = self.create_publisher(
            sensor_msgs.msg.Range, name, 10)

        timer_period = 0.3  # seconds
        self._timer = self.create_timer(timer_period, self.measure)

    def measure(self):
        field_of_view = self.get_parameter(
            'field_of_view').get_parameter_value().double_value
        min_range = self.get_parameter(
            'min_range').get_parameter_value().double_value
        max_range = self.get_parameter(
            'max_range').get_parameter_value().double_value

        msg = sensor_msgs.msg.Range()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.radiation_type = 0  # ultrasound
        msg.field_of_view = field_of_view
        msg.min_range = min_range
        msg.max_range = max_range
        msg.range = self._sensor.get_sample() / 100  # meters

        self._publisher.publish(msg)

    def destroy_node(self):
        return super().destroy_node()


class ColorSensor(rclpy.node.Node):
    def __init__(self, brick: nxt.brick.Brick, name: str, port: nxt.sensor.Port):
        super().__init__(name)

        self._sensor = brick.get_sensor(port, nxt.sensor.generic.Color)

        self._publisher = self.create_publisher(
            nxt_msgs2.msg.Color, name, 10)

        timer_period = 0.3  # seconds
        self._timer = self.create_timer(timer_period, self.measure)

    def measure(self):
        msg = nxt_msgs2.msg.Color()
        msg.header.stamp = self.get_clock().now().to_msg()
        sample = self._sensor.get_color()
        msg.color = self.color_code_to_rgba(sample)

        self._publisher.publish(msg)

    def destroy_node(self):
        self._sensor.set_light_color(nxt.sensor.Type.COLOR_EXIT)
        return super().destroy_node()

    def color_code_to_rgba(self, color_code: int) -> std_msgs.msg.ColorRGBA:
        """Converts nxt_python's color code to std_msgs.msg.ColorRGBA"""
        color = std_msgs.msg.ColorRGBA()
        if color_code == 1:  # black
            color.r = 0.0
            color.g = 0.0
            color.b = 0.0
        elif color_code == 2:  # blue
            color.r = 0.0
            color.g = 0.0
            color.b = 255.0
        elif color_code == 3:  # green
            color.r = 0.0
            color.g = 255.0
            color.b = 0.0
        elif color_code == 4:  # yellow
            color.r = 255.0
            color.g = 255.0
            color.b = 0.0
        elif color_code == 5:  # red
            color.r = 255.0
            color.g = 0.0
            color.b = 0.0
        elif color_code == 6:  # white
            color.r = 255.0
            color.g = 255.0
            color.b = 255.0
        color.a = 1.0
        return color


class ReflectedLightSensor(rclpy.node.Node):
    def __init__(self, brick: nxt.brick.Brick, name: str, port: nxt.sensor.Port):
        super().__init__(name)

        self._sensor = brick.get_sensor(port, nxt.sensor.generic.Color)

        self._publisher = self.create_publisher(
            nxt_msgs2.msg.Color, name, 10)

        self.declare_parameter('rgb_color', [0.0, 0.0, 0.0])
        self.add_on_set_parameters_callback(self.set_rgb_color_param)

        timer_period = 0.3
        self._timer = self.create_timer(timer_period, self.measure)

    def set_rgb_color_param(self, params: List[rclpy.Parameter]):
        updated_param = False
        for param in params:
            if param.name == "rgb_color" and param.type_ == rclpy.Parameter.Type.DOUBLE_ARRAY:
                rgb: List[float] = param.value
                color = self.rgb_to_color_type(rgb)
                param_is_valid = color != nxt.sensor.Type.COLOR_EXIT
                updated_param = param_is_valid

        return rcl_interfaces.msg.SetParametersResult(successful=updated_param)

    def measure(self):
        rgb = self.get_parameter(
            'rgb_color').get_parameter_value().double_array_value
        color = self.rgb_to_color_type(rgb)

        reflected_light = nxt_msgs2.msg.Color()
        reflected_light.header.stamp = self.get_clock().now().to_msg()
        reflected_light.color.a = float(
            self._sensor.get_reflected_light(color))
        reflected_light.color.r = rgb[0]
        reflected_light.color.g = rgb[1]
        reflected_light.color.b = rgb[2]

        self._publisher.publish(reflected_light)

    def rgb_to_color_type(self, rgb: List[float]):
        """Converts List [r: float, g: float, b: float] to nxt_python's color code."""
        if rgb[0] == 1.0 and rgb[1] == 0.0 and rgb[2] == 0.0:
            return nxt.sensor.Type.COLOR_RED
        elif rgb[0] == 0.0 and rgb[1] == 1.0 and rgb[2] == 0.0:
            return nxt.sensor.Type.COLOR_GREEN
        elif rgb[0] == 0.0 and rgb[1] == 0.0 and rgb[2] == 1.0:
            return nxt.sensor.Type.COLOR_BLUE
        elif rgb[0] == 1.0 and rgb[1] == 1.0 and rgb[2] == 1.0:
            return nxt.sensor.Type.COLOR_FULL
        elif rgb[0] == 0.0 and rgb[1] == 0.0 and rgb[2] == 0.0:
            return nxt.sensor.Type.COLOR_NONE
        else:
            return nxt.sensor.Type.COLOR_EXIT

    def destroy_node(self):
        self._sensor.set_light_color(nxt.sensor.Type.COLOR_EXIT)
        return super().destroy_node()


class Motor(rclpy.node.Node):
    def __init__(self, brick: nxt.brick.Brick, name: str, port: nxt.motor.Port):
        super().__init__(name)

        self._port = port
        self._motor = brick.get_motor(port)
        self._last_js = None
        self._effort = 0
        self._POWER_TO_NM = 0.01

        self._action_start_rad = 0
        self._goal_handle = None
        self._goal_lock = threading.Lock()
        self._turning_lock = threading.Lock()

        self._motor.reset_position(False)

        self._jc_subscriber = self.create_subscription(
            nxt_msgs2.msg.JointEffort, "joint_effort", self.joint_effort_cb, 10)

        self._js_publisher = self.create_publisher(
            sensor_msgs.msg.JointState, "joint_state", 10)

        timer_period = 0.1  # seconds
        self.create_timer(timer_period, self.motor_cb)

        self._action_server = rclpy.action.ActionServer(
            self,
            nxt_msgs2.action.TurnMotor,
            self.get_name() + '_turn',
            goal_callback=self.goal_callback,
            handle_accepted_callback=self.handle_accepted_callback,
            execute_callback=self.execute_callback,
            cancel_callback=self.cancel_callback)

    def joint_effort_cb(self, msg: nxt_msgs2.msg.JointEffort):
        if msg.joint_name == self.get_name():
            self._effort = msg.effort

    def motor_cb(self):
        now = self.get_clock().now()
        position_rad = self.get_motor_position()
        joint_name = self.get_name()
        joint_effort = self._effort * self._POWER_TO_NM
        velocity = 0

        if self._last_js:
            last_stamp = self._last_js.header.stamp
            last_js_now = rclpy.time.Time(seconds=last_stamp.sec,
                                          nanoseconds=last_stamp.nanosec,
                                          clock_type=rclpy.clock.ClockType.ROS_TIME)

            deltaSeconds = (now - last_js_now).nanoseconds/1000000000
            deltaPosition = position_rad - self._last_js.position[0]

            velocity = (deltaPosition / deltaSeconds)

        js = sensor_msgs.msg.JointState()
        js.header.stamp = now.to_msg()
        js.name.append(joint_name)
        js.effort.append(joint_effort)
        js.position.append(position_rad)
        js.velocity.append(velocity)

        self._js_publisher.publish(js)
        self._last_js = js

        if not self._turning_lock.locked():
            self._motor.run(int(self._effort), True)
        elif self._goal_handle is not None and self._goal_handle.is_active:
            feedback_msg = nxt_msgs2.action.TurnMotor.Feedback()
            feedback_msg.header.stamp = self.get_clock().now().to_msg()
            feedback_msg.start_position = self._action_start_rad
            feedback_msg.current_position = position_rad
            self._goal_handle.publish_feedback(feedback_msg)

    def get_motor_position(self):
        return math.radians(self._motor.get_tacho().rotation_count)

    def goal_callback(self, goal_request):
        return rclpy.action.GoalResponse.ACCEPT

    def handle_accepted_callback(self, goal_handle):
        with self._goal_lock:
            if self._goal_handle is not None and self._goal_handle.is_active:
                self._goal_handle.abort()
                self.get_logger().info(
                    "Motor.turn action: cancelling previous and accepting new goal (motor port: %s)" % self._port)
            else:
                self.get_logger().info("Motor.turn: action goal accepted (motor port: %s)" % self._port)

            self._goal_handle = goal_handle

        goal_handle.execute()

    def execute_callback(self, goal_handle):
        with self._turning_lock:
            req = goal_handle.request
            self._action_start_rad = self.get_motor_position()

            def stop_turn(): return goal_handle.is_cancel_requested and goal_handle.is_active
            motor_turn_thread = threading.Thread(target=self._motor.turn, kwargs={'power': req.power,
                                                                                  'tacho_units': math.degrees(req.tacho_units),
                                                                                  'brake': req.brake,
                                                                                  'timeout': req.timeout,
                                                                                  'emulate': req.emulate,
                                                                                  'stop_turn': stop_turn})

            motor_turn_thread.start()
            motor_turn_thread.join()

            end_rad = self.get_motor_position()

            if not goal_handle.is_active:
                self.get_logger().info("Motor.turn action: goal aborted (motor port: %s)" % self._port)
                return nxt_msgs2.action.TurnMotor.Result()

            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                self.get_logger().info("Motor.turn: action: goal canceled (motor port: %s)" % self._port)
                return nxt_msgs2.action.TurnMotor.Result()

            goal_handle.succeed()

            result = nxt_msgs2.action.TurnMotor.Result()
            result.header.stamp = self.get_clock().now().to_msg()
            result.start_position = self._action_start_rad
            result.end_position = end_rad
            return result

    def cancel_callback(self, cancel_request):
        return rclpy.action.CancelResponse.ACCEPT

    def destroy_node(self):
        self._motor.idle()
        self._action_server.destroy()
        return super().destroy_node()


class NxtRos2Setup(rclpy.node.Node):
    """Helper node to read ros2 parameters required for setting up the device-nodes"""

    def __init__(self, brick: nxt.brick.Brick):
        self._brick = brick

        super().__init__("nxt_ros_setup", allow_undeclared_parameters=True,
                         automatically_declare_parameters_from_overrides=True)

        service_name = self.get_name() + '/get_available_motor_configs'
        self._motor_names_service = self.create_service(
            nxt_msgs2.srv.MotorConfigs, service_name, self.get_available_motor_configs)

    # Sensors
    def get_sensor_configs_from_parameters(self) -> SensorConfigs:
        valid_sensor_ports = ["1", "2", "3", "4"]
        required_sensor_params = {"sensor_type", "sensor_name"}

        sensor_configs = SensorConfigs()

        for port_str in valid_sensor_ports:
            sensor_params: Dict[str, rclpy.Parameter] = self.get_parameters_by_prefix(
                port_str)

            if sensor_params == {}:
                # No sensor defined for this port
                continue

            if not sensor_params.keys() >= required_sensor_params:
                raise Exception(
                    "Missing or invalid sensor config parameters for sensor '%s', required: %s" % (port_str, required_sensor_params))

            sensor_configs.sensor_ports.append(port_str)
            sensor_configs.sensor_types.append(
                sensor_params['sensor_type'].value)
            sensor_configs.sensor_names.append(
                sensor_params['sensor_name'].value)

        return sensor_configs

    def check_sensor_configs(self, sensor_configs: SensorConfigs):
        valid_sensor_types = [
            "touch", "ultrasonic", "color", "reflected_light"]

        for i in range(len(sensor_configs.sensor_names)):
            sensor_name = sensor_configs.sensor_names[i]
            sensor_port = sensor_configs.sensor_ports[i]
            sensor_type = sensor_configs.sensor_types[i]

            if sensor_configs.sensor_ports.count(sensor_port) > 1:
                raise Exception(
                    "Duplicate sensor_port '%s' in config parameters" % sensor_port)
            if sensor_configs.sensor_names.count(sensor_name) > 1:
                raise Exception(
                    "Duplicate sensor_name '%s' in config parameters" % sensor_name)
            if sensor_type not in valid_sensor_types:
                raise Exception(
                    "Invalid sensor_type '%s' config for sensor on port: '%s'. Valid sensor_type's: %s" % (sensor_type, sensor_port, valid_sensor_types))

    # TODO Refactor sensors to extend a Sensor class
    def create_sensor_nodes(self, brick: nxt.brick.Brick, sensor_configs: SensorConfigs) -> List[Union[TouchSensor, UltraSonicSensor,
                                                                                                       ColorSensor, ReflectedLightSensor]]:
        sensor_nodes: List[Union[TouchSensor, UltraSonicSensor,
                                 ColorSensor, ReflectedLightSensor]] = []

        for i in range(len(sensor_configs.sensor_names)):
            sensor_name = sensor_configs.sensor_names[i]
            sensor_port_str = sensor_configs.sensor_ports[i]
            sensor_port_enum = self.str_to_sensor_port_enum(sensor_port_str)
            sensor_type = sensor_configs.sensor_types[i]

            if sensor_type == "touch":
                sensor_nodes.append(TouchSensor(
                    brick, sensor_name, sensor_port_enum))
            elif sensor_type == "ultrasonic":
                sensor_nodes.append(UltraSonicSensor(
                    brick, sensor_name, sensor_port_enum))
            elif sensor_type == "color":
                sensor_nodes.append(ColorSensor(
                    brick, sensor_name, sensor_port_enum))
            elif sensor_type == "reflected_light":
                sensor_nodes.append(ReflectedLightSensor(
                    brick, sensor_name, sensor_port_enum))

            self.get_logger().info("Created sensor of type '%s' with node name '%s' on port '%s'" %
                                   (sensor_type, sensor_name, sensor_port_enum))

        return sensor_nodes

    def create_and_get_sensor_nodes(self) -> List[Union[TouchSensor, UltraSonicSensor,
                                                        ColorSensor, ReflectedLightSensor]]:
        sensor_configs = self.get_sensor_configs_from_parameters()
        self.check_sensor_configs(sensor_configs)
        sensor_nodes = self.create_sensor_nodes(self._brick, sensor_configs)
        return sensor_nodes

    def str_to_sensor_port_enum(self, port: int) -> nxt.sensor.Port:
        if port == "1":
            return nxt.sensor.Port.S1
        elif port == "2":
            return nxt.sensor.Port.S2
        elif port == "3":
            return nxt.sensor.Port.S3
        elif port == "4":
            return nxt.sensor.Port.S4
        else:
            raise Exception("Invalid sensor port in config parameters")

    # Motors

    def get_motor_configs_from_parameters(self) -> MotorConfigs:
        valid_motor_ports = ["A", "B", "C"]
        required_motor_params = {'motor_name', 'motor_type',
                                 'motor_mimic_name', 'motor_mimic_gear_ratio'}

        motor_configs = MotorConfigs()

        for port_str in valid_motor_ports:
            motor_params: Dict[str, rclpy.Parameter] = self.get_parameters_by_prefix(
                port_str)

            if motor_params == {}:
                # No motor defined for this port
                continue

            if not motor_params.keys() >= required_motor_params:
                raise Exception(
                    "Missing or invalid motor config parameters for motor '%s', required: %s" % (port_str, required_motor_params))

            motor_type = motor_params['motor_type'].value

            motor_configs.motor_ports.append(port_str)
            motor_configs.motor_types.append(motor_type)
            motor_configs.motor_names.append(
                motor_params['motor_name'].value)
            motor_configs.motor_mimic_names.append(
                motor_params['motor_mimic_name'].value)
            motor_configs.motor_mimic_gear_ratios.append(
                motor_params['motor_mimic_gear_ratio'].value)

            if motor_type == MotorType.wheel_motor_r.value or motor_type == MotorType.wheel_motor_l.value:
                if "invert_effort" not in motor_params.keys() or not isinstance(motor_params['invert_effort'].value, bool):
                    raise Exception(
                        "Missing or invalid motor config parameter 'invert_effort: bool' for motor: '%s'" % port_str)
                else:
                    motor_configs.invert_efforts.append(
                        motor_params['invert_effort'].value)
            else:
                motor_configs.invert_efforts.append(False)

        return motor_configs

    def check_motor_configs(self, motor_configs: MotorConfigs):
        valid_motor_types = ['wheel_motor_r', 'wheel_motor_l', 'other']

        for i in range(len(motor_configs.motor_names)):
            motor_port = motor_configs.motor_ports[i]
            motor_name = motor_configs.motor_names[i]
            motor_mimic_name = motor_configs.motor_mimic_names[i]
            motor_type = motor_configs.motor_types[i]

            if motor_configs.motor_names.count(motor_name) > 1:
                raise Exception(
                    "Duplicate motor_name '%s' in config parameters" % motor_name)

            if motor_configs.motor_mimic_names.count(motor_mimic_name) > 1:
                raise Exception(
                    "Duplicate motor_mimic_name '%s' in config parameters" % motor_mimic_name)

            if motor_configs.motor_ports.count(motor_port) > 1:
                raise Exception(
                    "Duplicate motor_port '%s' in config parameters" % motor_port)

            if motor_type not in valid_motor_types:
                raise Exception(
                    "Invalid config motor_type: '%s' for motor on port: '%s'. Valid motor_type's: %s" % (motor_type, motor_port, valid_motor_types))

        if 'wheel_motor_r' in motor_configs.motor_types and 'wheel_motor_l' not in motor_configs.motor_types:
            raise Exception(
                "If you define a motor with motor_type 'wheel_motor_r', please also define one with motor_type: 'wheel_motor_l'. Otherwise config all motor_types as 'other'")
        if 'wheel_motor_l' in motor_configs.motor_types and 'wheel_motor_r' not in motor_configs.motor_types:
            raise Exception(
                "If you define a motor with motor_type 'wheel_motor_l', please also define one with motor_type: 'wheel_motor_r'. Otherwise config all motor_types as 'other'")

    def create_motor_nodes(self, brick: nxt.brick.Brick, motor_configs: MotorConfigs) -> List[Motor]:
        motor_nodes: List[Motor] = []
        for i in range(len(motor_configs.motor_names)):
            motor_name = motor_configs.motor_names[i]
            motor_port_str = motor_configs.motor_ports[i]
            motor_port_enum = self.string_to_motor_port_enum(
                motor_port_str)
            motor_type = motor_configs.motor_types[i]

            motor_nodes.append(Motor(brick, motor_name, motor_port_enum))

            self.get_logger().info("Created motor of type '%s' with node name '%s' on port '%s'" %
                                   (motor_type, motor_name, motor_port_enum))

        return motor_nodes

    def create_and_get_motor_nodes(self) -> List[Motor]:
        motor_configs = self.get_motor_configs_from_parameters()
        self.check_motor_configs(motor_configs)
        motor_nodes = self.create_motor_nodes(self._brick, motor_configs)
        return motor_nodes

    def get_available_motor_configs(self, request, response):
        motor_configs = self.get_motor_configs_from_parameters()
        response.header.stamp = self.get_clock().now().to_msg()
        response.motor_names = motor_configs.motor_names
        response.motor_mimic_names = motor_configs.motor_mimic_names
        response.motor_mimic_gear_ratios = motor_configs.motor_mimic_gear_ratios
        response.motor_ports = motor_configs.motor_ports
        response.motor_types = motor_configs.motor_types
        response.invert_efforts = motor_configs.invert_efforts
        return response

    def string_to_motor_port_enum(self, port: str) -> nxt.motor.Port:
        if port == "A":
            return nxt.motor.Port.A
        elif port == "B":
            return nxt.motor.Port.B
        elif port == "C":
            return nxt.motor.Port.C
        else:
            raise Exception("Invalid motor port in config parameters")

    # General
    def check_ports_config_parameters(self) -> bool:
        valid_motor_ports: List[str] = ["A", "B", "C"]
        valid_sensor_ports: List[str] = ["1", "2", "3", "4"]

        params = self.get_parameters_by_prefix("")
        params = list(map(lambda param: param.split(".")[0], params))
        ports = list(
            set(filter(lambda port: port != 'use_sim_time', params)))

        for port in ports:
            if port not in valid_motor_ports and port not in valid_sensor_ports:
                raise Exception(
                    "Invalid port '%s' in config! (Valid motor ports: %s. Valid sensor ports: %s)" % (port, valid_motor_ports, valid_sensor_ports))


def main(args=None):
    rclpy.init(args=args)

    try:
        with nxt.locator.find() as brick:
            setup_node = NxtRos2Setup(brick)
            executor = rclpy.executors.MultiThreadedExecutor()

            nodes: List[Union[TouchSensor, UltraSonicSensor,
                              ColorSensor, ReflectedLightSensor, Motor]] = []

            try:
                setup_node.check_ports_config_parameters()
                nodes.extend(setup_node.create_and_get_sensor_nodes())
                nodes.extend(setup_node.create_and_get_motor_nodes())

                for node in nodes:
                    executor.add_node(node)
                executor.add_node(setup_node)

                executor.spin()
            finally:
                for node in nodes:
                    node.destroy_node()

                executor.shutdown()

    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    main()