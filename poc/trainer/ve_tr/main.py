# main.py
import frida
import sys
import os
import time
import threading

class TargetTrainController:
    def __init__(self, process_name="GrilsFrontLine.exe"):
        self.process_name = process_name
        self.session = None
        self.script = None
        self.exit_event = threading.Event()

    def on_message(self, message, data):
        if message['type'] == 'send':
            payload = message.get('payload', {})
            msg_type = payload.get('type')
            msg_text = payload.get('payload')
            
            if msg_type == 'error':
                print(f"\n[!] ERROR: {msg_text}")
            elif msg_type == 'info':
                print(f"[*] {msg_text}")
            elif msg_type == 'hook':
                print(f"[+] {msg_text}")
        else:
            print(f"\n[System] {message}")

    def attach_and_load(self, js_path="hook.js"):
        print(f"[*] Locating Process: {self.process_name} ...")
        try:
            self.session = frida.attach(self.process_name)
        except Exception as e:
            print(f"[Error] Could not attach: {e}")
            return False

        with open(js_path, "r", encoding="utf-8") as f:
            script_code = f.read()

        self.script = self.session.create_script(script_code)
        self.script.on('message', self.on_message)
        self.script.load()
        time.sleep(1)
        return True

    def interactive_loop(self):
        print("\n" + "="*50)
        print("Vehicle Pointer Stealer & Injector")
        print("Commands:")
        print("  q - Quit and safely detach")
        print("  s - ENABLE Injection (Replace TargetTrain team with Stolen Vehicle)")
        print("  r - DISABLE Injection (Normal TargetTrain behavior)")
        print("="*50)
        
        while not self.exit_event.is_set():
            try:
                user_input = input("\nCmd (q/s/r)> ").strip().lower()
                
                if user_input == 'q':
                    self.script.exports_sync.setspoof(False)
                    self.exit_event.set()
                    break
                elif user_input == 's':
                    if self.script.exports_sync.setspoof(True):
                        print("-> INJECTION ENABLED: The next TargetTrain battle will use the stolen pointer!")
                elif user_input == 'r':
                    if self.script.exports_sync.setspoof(False):
                        print("-> INJECTION DISABLED: Normal behavior restored.")
                        
            except (EOFError, KeyboardInterrupt):
                self.script.exports_sync.setspoof(False)
                self.exit_event.set()
                break

    def cleanup(self):
        if self.session:
            self.session.detach()
        print("Detached safely.")

def main():
    controller = TargetTrainController("GrilsFrontLine.exe")
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook.js")
    if controller.attach_and_load(js_path=script_path):
        controller.interactive_loop()
        controller.cleanup()

if __name__ == "__main__":
    main()