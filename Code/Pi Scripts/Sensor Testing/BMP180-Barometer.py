import board
import busio
from bmp180 import BMP180

i2c = busio.I2C(board.SCL, board.SDA)
sensor = BMP180(i2c)

print(f"Temp = {sensor.temperature:.2f} C")
print(f"Pressure = {sensor.pressure:.2f} hPa")
print(f"Altitude = {sensor.altitude:.2f} m")
