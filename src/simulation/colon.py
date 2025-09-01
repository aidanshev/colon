class Colon:
    """
    Represents the colon in the simulation.
    For now, it's a simple straight tube along the z-axis.
    """
    def __init__(self, length=100, radius=10):
        """
        Initializes the colon's dimensions.
        """
        self.length = length
        self.radius = radius

    def is_inside(self, x, y, z):
        """
        Checks if a given point is inside the colon.
        """
        # Check if within the radius from the center (0,0)
        in_radius = (x**2 + y**2) < self.radius**2
        # Check if within the length of the colon
        in_length = 0 <= z <= self.length
        return in_radius and in_length

    def get_lumen_center(self, z_position):
        """
        For a straight colon, the lumen center is always at (0,0)
        in the x,y plane.
        """
        if 0 <= z_position <= self.length:
            return (0, 0)
        else:
            return None # Outside the colon
