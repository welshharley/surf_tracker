import board, busio
from bmp180 import BMP180
i2c = busio.I2C(board.SCL, board.SDA)
sensor = BMP180(i2c)
print([x for x in dir(sensor) if not x.startswith('_')])

