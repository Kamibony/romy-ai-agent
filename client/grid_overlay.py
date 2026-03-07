import tkinter as tk

def create_grid_overlay(step: int = 100) -> tk.Tk:
    """
    Creates a full-screen, borderless, semi-transparent Tkinter window
    with a coordinate grid overlaid. Returns the Tk instance so it can
    be updated/destroyed by the caller.
    """
    root = tk.Tk()

    # Make it borderless and full screen
    root.overrideredirect(True)
    root.attributes('-topmost', True)

    # On Windows, we can use a transparent color key, or alpha.
    # Alpha makes the whole window transparent (including lines).
    # Wait, we want the background to be transparent but lines visible.
    # In Tkinter on Windows, we can use '-transparentcolor'.

    # We will use a specific color for background and make it transparent.
    bg_color = '#000001' # Almost black
    root.config(bg=bg_color)

    try:
        root.attributes('-transparentcolor', bg_color)
    except Exception:
        # Fallback for non-Windows: just make it semi-transparent
        root.attributes('-alpha', 0.5)

    # Get screen width and height
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()

    # Position at top-left
    root.geometry(f"{screen_width}x{screen_height}+0+0")

    # Create a canvas to draw the grid
    canvas = tk.Canvas(root, width=screen_width, height=screen_height, bg=bg_color, highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=True)

    # Draw vertical lines and labels
    for x in range(0, screen_width, step):
        canvas.create_line(x, 0, x, screen_height, fill='red', dash=(2, 2))
        if x > 0:
            canvas.create_text(x + 2, 10, text=str(x), fill='red', anchor=tk.NW, font=("Arial", 12))

    # Draw horizontal lines and labels
    for y in range(0, screen_height, step):
        canvas.create_line(0, y, screen_width, y, fill='blue', dash=(2, 2))
        if y > 0:
            canvas.create_text(10, y + 2, text=str(y), fill='blue', anchor=tk.NW, font=("Arial", 12))

    # Draw intersection labels (optional, but requested "or intersections")
    # Doing just axes might be cleaner, but intersections make it precise locally.
    # Let's add intersections every `step` pixels.
    for x in range(0, screen_width, step):
        for y in range(0, screen_height, step):
            if x > 0 and y > 0:
                canvas.create_text(x + 2, y + 2, text=f"{x},{y}", fill='green', anchor=tk.NW, font=("Arial", 12))

    # Ensure window displays immediately
    root.update()

    return root
