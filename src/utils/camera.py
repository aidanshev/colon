class Camera:
    """
    Simulates the camera at the tip of the colonoscope.
    """
    def __init__(self, scope, colon):
        """
        Initializes the camera with a reference to the scope and colon.
        """
        self.scope = scope
        self.colon = colon

    def capture_image(self):
        """
        Generates a simulated image from the scope's perspective.

        For this basic simulation, the "image" will be a dictionary
        containing the coordinates of the lumen center relative to the
        scope's current position.
        """
        scope_x, scope_y, scope_z = self.scope.get_position()

        lumen_center = self.colon.get_lumen_center(scope_z)

        if lumen_center is None:
            # Scope is outside the colon
            return None

        lumen_x, lumen_y = lumen_center

        # For a simple straight colon, the lumen center is at (0,0).
        # The "image" is just the vector from the scope to the lumen center.
        # A real implementation would involve rendering a 3D scene.
        image_data = {
            'lumen_center_x': lumen_x - scope_x,
            'lumen_center_y': lumen_y - scope_y,
            'distance_to_end': self.colon.length - scope_z
        }
        return image_data
