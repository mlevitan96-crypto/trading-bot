#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.intelligence_gate import intelligence_gate

# Test with valid signal
result = intelligence_gate({"symbol": "BTCUSDT", "action": "OPEN_LONG"})
print(f"Valid signal result: {result}")
print(f"Type: {type(result)}")

# Test with empty dict
result2 = intelligence_gate({})
print(f"Empty dict result: {result2}")
print(f"Type: {type(result2)}")

# Test with None
try:
    result3 = intelligence_gate(None)
    print(f"None result: {result3}")
except Exception as e:
    print(f"None raised exception: {e}")

