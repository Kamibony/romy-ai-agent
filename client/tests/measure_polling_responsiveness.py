import time
import threading
import sys
import os

# Simplified polling loop similar to agent.py
def baseline_poll_loop(state, results):
    while not state['stop']:
        if not state['token'] or state['paused']:
            time.sleep(3)
            continue

        results['last_poll'] = time.time()
        time.sleep(3)

def optimized_poll_loop(state, results, wake_event):
    while not state['stop']:
        if not state['token'] or state['paused']:
            wake_event.wait(3)
            wake_event.clear()
            continue

        results['last_poll'] = time.time()
        if wake_event.wait(3):
            wake_event.clear()

def run_benchmark(is_optimized=False):
    state = {'token': False, 'paused': False, 'stop': False}
    results = {'last_poll': 0}
    wake_event = threading.Event()

    if is_optimized:
        t = threading.Thread(target=optimized_poll_loop, args=(state, results, wake_event))
    else:
        t = threading.Thread(target=baseline_poll_loop, args=(state, results))

    t.start()

    # Wait for loop to start and hit the sleep
    time.sleep(1)

    # Trigger "Wake up"
    start_time = time.time()
    state['token'] = True
    if is_optimized:
        wake_event.set()

    # Wait for the poll to happen
    while results['last_poll'] == 0:
        time.sleep(0.01)
        if time.time() - start_time > 5:
            print("  Timeout waiting for poll")
            break

    delay = results['last_poll'] - start_time

    state['stop'] = True
    if is_optimized:
        wake_event.set()
    t.join()

    return delay

if __name__ == "__main__":
    print("Measuring baseline responsiveness (current code pattern)...")
    # Run multiple times to get an average or representative sample
    delays = []
    for _ in range(3):
        d = run_benchmark(is_optimized=False)
        print(f"  Attempt: {d:.4f}s")
        delays.append(d)
    print(f"Average Baseline Delay: {sum(delays)/len(delays):.4f}s")

    print("\nMeasuring optimized responsiveness (Event-based)...")
    delays_opt = []
    for _ in range(3):
        d = run_benchmark(is_optimized=True)
        print(f"  Attempt: {d:.4f}s")
        delays_opt.append(d)
    print(f"Average Optimized Delay: {sum(delays_opt)/len(delays_opt):.4f}s")
