from .simulation.colon import Colon
from .simulation.scope import Scope
from .utils.camera import Camera
from .navigation.controller import Controller
import time

def run_simulation():
    """
    Sets up and runs the colonoscopy simulation.
    """
    print("Starting simulation...")

    # Initialize the simulation components
    colon = Colon(length=100, radius=10)

    # Start the scope slightly off-center to test the controller
    scope = Scope(x=1, y=-2, z=0)

    # Using a PD controller now. kp is the proportional gain, kd is the derivative gain.
    camera = Camera(scope, colon)
    controller = Controller(scope, camera, kp=0.05, kd=0.1)

    # Main simulation loop
    running = True
    max_steps = 200 # Add a max step to prevent infinite loops
    step_count = 0
    while running and step_count < max_steps:
        running = controller.step()

        # A small delay to make the simulation easier to follow
        time.sleep(0.1)

        # Check if the scope has perforated the colon wall
        if not colon.is_inside(scope.x, scope.y, scope.z):
            # Allow for being at the very start
            if scope.z > 0:
                print("Error: Scope has perforated the colon wall!")
                running = False

        step_count += 1

    if step_count >= max_steps:
        print("Simulation stopped after reaching max steps.")

    print("Simulation finished.")

if __name__ == "__main__":
    run_simulation()
