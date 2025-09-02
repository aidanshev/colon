import cv2
import numpy as np
import base64
import argparse

def find_lumen(image):
    """
    Finds the lumen in a given video frame.

    This function currently uses a simple color thresholding method, which
    was originally designed for synthetic images. It will likely need to be
    tuned or replaced with a more robust method (e.g., a deep learning model)
    to work reliably on real colonoscopy videos.
    """
    # Convert to HSV color space, which is good for color filtering
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # Define a color range for the dark lumen.
    # NOTE: These values are placeholders and will need tuning for real videos.
    lower_bound = np.array([0, 0, 0])
    upper_bound = np.array([180, 255, 100])

    # Create a mask for the lumen color
    mask = cv2.inRange(hsv, lower_bound, upper_bound)

    # Clean up the mask with morphological operations
    kernel = np.ones((15, 15), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    # Find the largest contour
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None, None

    largest_contour = max(contours, key=cv2.contourArea)

    M = cv2.moments(largest_contour)
    if M["m00"] == 0:
        return None, None

    center_x = int(M["m10"] / M["m00"])
    center_y = int(M["m01"] / M["m00"])

    return (center_x, center_y), largest_contour

def draw_navigation_ui(image, lumen_center, contour, frame_num):
    """Draws the navigation UI elements on the image."""
    # Add a black border to simulate the endoscope view
    height, width, _ = image.shape
    cv2.circle(image, (width // 2, height // 2), min(width, height) // 2 - 5, (0, 0, 0), 20)

    if contour is not None:
        cv2.drawContours(image, [contour], -1, (0, 255, 0), 2)
    if lumen_center is not None:
        cv2.circle(image, lumen_center, 7, (0, 0, 255), -1)
        # Draw navigation arrow
        img_center_x, img_center_y = width // 2, height // 2
        cv2.arrowedLine(image, (img_center_x, img_center_y), lumen_center, (255, 255, 0), 4)

    cv2.putText(image, "Lumen Navigation Demo", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    target_text = f"Target Lock: {lumen_center}" if lumen_center else "Target: Not Found"
    cv2.putText(image, target_text, (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(image, f"Frame: {frame_num}", (width - 160, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    return image

def process_video(video_path):
    """
    Processes a colonoscopy video to identify the lumen and display navigation.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video file at {video_path}")
        return

    frame_num = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        # 1. Find the lumen in the current frame
        detected_center, detected_contour = find_lumen(frame)

        # 2. Draw the UI
        output_image = draw_navigation_ui(frame.copy(), detected_center, detected_contour, frame_num)

        # 3. Encode and print the frame as a base64 string
        # This allows for displaying the video in environments without a GUI.
        _, buffer = cv2.imencode('.png', output_image)
        b64_string = base64.b64encode(buffer).decode('utf-8')
        print(f"\n---BEGIN-BASE64-IMAGE-FRAME-{frame_num}---")
        print(b64_string)
        print(f"---END-BASE64-IMAGE-FRAME-{frame_num}---")

        frame_num += 1

    cap.release()
    print(f"\nSuccessfully processed all {frame_num} frames from the video.")

def main():
    parser = argparse.ArgumentParser(description="Process a colonoscopy video to demonstrate lumen navigation.")
    parser.add_argument("video_file", type=str, help="Path to the colonoscopy video file.")
    args = parser.parse_args()

    process_video(args.video_file)

if __name__ == "__main__":
    # To run this script, you would use the command:
    # python demo.py /path/to/your/video.mp4
    main()
