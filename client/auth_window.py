import tkinter as tk
import requests

def login_window() -> str | None:
    """
    Displays a tkinter GUI login window for Firebase Authentication.
    Returns the retrieved idToken if successful, or None if the window is closed.
    """
    try:
        root = tk.Tk()
        root.title("ROMY AI - Login")
        root.geometry("300x250")
        root.resizable(False, False)

        # Center the window
        root.eval('tk::PlaceWindow . center')

        token_result = [None]

        def attempt_login():
            email = email_entry.get()
            password = password_entry.get()

            if not email or not password:
                status_label.config(text="Email and password required", fg="red")
                return

            status_label.config(text="Logging in...", fg="blue")
            root.update()

            try:
                api_key = "AIzaSyBF2KBDgfYOzMbdSjFgCrGUygQbFaSfSxI"
                url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
                payload = {
                    "email": email,
                    "password": password,
                    "returnSecureToken": True
                }
                response = requests.post(url, json=payload)
                data = response.json()

                if response.status_code == 200:
                    token_result[0] = data.get("idToken")
                    root.destroy()
                else:
                    error_msg = data.get("error", {}).get("message", "Login failed")
                    status_label.config(text=error_msg, fg="red")
            except requests.exceptions.RequestException as e:
                status_label.config(text="Network error", fg="red")

        # UI Elements
        tk.Label(root, text="Email:").pack(pady=(20, 0))
        email_entry = tk.Entry(root, width=30)
        email_entry.pack()

        tk.Label(root, text="Password:").pack(pady=(10, 0))
        password_entry = tk.Entry(root, width=30, show="*")
        password_entry.pack()

        login_btn = tk.Button(root, text="Login", command=attempt_login, width=15)
        login_btn.pack(pady=20)

        status_label = tk.Label(root, text="", fg="red", wraplength=280)
        status_label.pack()

        # Bind Enter key to login
        root.bind('<Return>', lambda event: attempt_login())

        root.mainloop()

        return token_result[0]
    except Exception as e:
        print(f"Error creating login window: {e}")
        return None
