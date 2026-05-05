import cv2
import numpy as np

# Load an image
image = cv2.imread('image.jpg')

# Define a sharpening kernel
sharpen_kernel = np.array([[-1, -1, -1],
                           [-1,  9, -1],
                           [-1, -1, -1]])

# Apply the kernel using filter2D
sharpened_image = cv2.filter2D(image, -1, sharpen_kernel)

# Display the original and sharpened images (optional)
# cv2.imshow('Original Image', image)
# cv2.imshow('Sharpened Image', sharpened_image)
# cv2.waitKey(0)
# cv2.destroyAllWindows()