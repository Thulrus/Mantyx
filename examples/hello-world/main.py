#!/usr/bin/env python3
"""
Example Mantyx Application - Hello World

This is a simple perpetual application that prints a message every 10 seconds.
It demonstrates the basic structure of a Mantyx-managed app.
"""

import sys
import time
from datetime import datetime


def main():
    """Main application loop."""
    print("Hello World App starting...")
    print(f"Started at: {datetime.now()}")
    
    counter = 0
    
    try:
        while True:
            counter += 1
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp}] Hello from Mantyx! (iteration {counter})")
            
            # Sleep for 10 seconds
            time.sleep(10)
            
    except KeyboardInterrupt:
        print("\nReceived shutdown signal...")
        print(f"Ran for {counter} iterations")
        print("Goodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"Error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
