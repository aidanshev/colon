class Scope:
    """
    Represents the colonoscope in the simulation.
    """
    def __init__(self, x=0, y=0, z=0, pitch=0, yaw=0):
        """
        Initializes the scope's position and orientation.
        Angles are in radians.
        """
        self.x = x
        self.y = y
        self.z = z
        self.pitch = pitch  # Up/down angle
        self.yaw = yaw      # Left/right angle

    def move_forward(self, distance):
        """
        Moves the scope forward along its current direction.
        Uses a simplified model where dx/dz = yaw and dy/dz = pitch.
        This is a reasonable approximation for small angles.
        """
        # We move a distance of `distance` mostly along the z-axis.
        # The change in x and y depends on the orientation.
        self.x += distance * self.yaw
        self.y += distance * self.pitch
        self.z += distance

    def rotate(self, pitch_change, yaw_change):
        """
        Changes the scope's orientation.
        """
        self.pitch += pitch_change
        self.yaw += yaw_change

    def get_position(self):
        """Returns the current position of the scope."""
        return (self.x, self.y, self.z)

    def get_orientation(self):
        """Returns the current orientation of the scope."""
        return (self.pitch, self.yaw)
