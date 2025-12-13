import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.run import main_with_crash_protection

if __name__ == "__main__":
    main_with_crash_protection()
