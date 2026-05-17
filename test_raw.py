from ai_edge_litert.interpreter import Interpreter, load_delegate
import numpy as np

print("Loading delegate...")
delegate = load_delegate('libedgetpu.so.1')
print("Loading model...")
interpreter = Interpreter(
    model_path='/home/pi/surf_tracker/best_full_integer_quant_edgetpu.tflite',
    experimental_delegates=[delegate])
interpreter.allocate_tensors()

inp = interpreter.get_input_details()[0]
print("Input:", inp['shape'], inp['dtype'])

dummy = np.zeros(inp['shape'], dtype=inp['dtype'])
interpreter.set_tensor(inp['index'], dummy)
print("Invoking...")
interpreter.invoke()
print("OK — Coral works.")
