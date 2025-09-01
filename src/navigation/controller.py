from ..simulation.scope import Scope
from ..utils.camera import Camera

class Controller:
    """
    The controller for the colonoscope.
    It uses data from the camera to decide where to move.
    This version uses a PD (Proportional-Derivative) controller.
    """
    def __init__(self, scope: Scope, camera: Camera, kp=0.1, kd=0.0):
        """
        Initializes the controller with the scope and camera.

        :param scope: The scope object to control.
        :param camera: The camera providing images.
        :param kp: The proportional gain for the centering controller.
        :param kd: The derivative gain for the centering controller.
        """
        self.scope = scope
        self.camera = camera
        self.kp = kp
        self.kd = kd
        self.last_err_x = 0
        self.last_err_y = 0
        self.initialized = False

    def step(self):
        """
        Performs one step of the control loop.
        """
        image_data = self.camera.capture_image()

        if image_data is None:
            print("Controller: Scope is outside the colon, stopping.")
            return False

        err_x = image_data['lumen_center_x']
        err_y = image_data['lumen_center_y']

        # On the first step, derivative is zero.
        if not self.initialized:
            self.last_err_x = err_x
            self.last_err_y = err_y
            self.initialized = True

        # Calculate derivative of error (change in error since last step)
        deriv_err_x = err_x - self.last_err_x
        deriv_err_y = err_y - self.last_err_y

        # PD control law with corrected signs for negative feedback.
        # If error is positive, we want a positive adjustment.
        yaw_adjustment = self.kp * err_x + self.kd * deriv_err_x
        pitch_adjustment = self.kp * err_y + self.kd * deriv_err_y

        self.scope.rotate(pitch_adjustment, yaw_adjustment)
        self.scope.move_forward(1.0)

        # Update last error for the next iteration
        self.last_err_x = err_x
        self.last_err_y = err_y

        print(f"Scope at ({self.scope.x:.2f}, {self.scope.y:.2f}, {self.scope.z:.2f}), "
              f"Error (x,y): ({err_x:.2f}, {err_y:.2f}), "
              f"End dist: {image_data['distance_to_end']:.2f}")

        if image_data['distance_to_end'] <= 1.0:
            print("Controller: Reached the end of the colon.")
            return False

        return True
