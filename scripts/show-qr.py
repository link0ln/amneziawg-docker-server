#!/usr/bin/env python3

import sys
import os
import subprocess

def main():
    if len(sys.argv) != 2:
        print("Usage: show-qr.py <client-name>")
        sys.exit(1)

    client_name = sys.argv[1]
    config_dir = "./config"
    clients_dir = f"{config_dir}/clients"
    client_config = f"{clients_dir}/{client_name}/{client_name}.conf"

    # Check if client exists
    if not os.path.exists(client_config):
        print(f"ERROR: Client '{client_name}' not found!")
        print(f"Config file does not exist: {client_config}")
        sys.exit(1)

    # Read config
    try:
        with open(client_config, 'r') as f:
            config_content = f.read()
    except Exception as e:
        print(f"ERROR: Failed to read config: {e}")
        sys.exit(1)

    print(f"=== QR Code for client: {client_name} ===")
    print()

    # Try to use qrencode if available (best quality)
    try:
        result = subprocess.run(
            ['qrencode', '-t', 'ansiutf8'],
            input=config_content,
            text=True,
            capture_output=True
        )
        if result.returncode == 0:
            print(result.stdout)
            print()
            print("Scan this QR code with AmneziaWG mobile app")
            return
    except FileNotFoundError:
        pass

    # Fallback: try Python qrcode library
    try:
        import qrcode

        qr = qrcode.QRCode()
        qr.add_data(config_content)
        qr.make()

        # Print to terminal
        qr.print_ascii(invert=True)
        print()
        print("Scan this QR code with AmneziaWG mobile app")
        print()
        print("TIP: For better quality, install qrencode:")
        print("  apt install qrencode  # Debian/Ubuntu")
        print("  yum install qrencode  # CentOS/RHEL")
        return
    except ImportError:
        pass

    # If nothing works, show instructions
    print("ERROR: No QR code generator found!")
    print()
    print("Please install one of:")
    print("  1. qrencode (recommended):")
    print("     apt install qrencode")
    print()
    print("  2. Python qrcode library:")
    print("     pip3 install qrcode")
    print()
    print(f"Or manually show the config file:")
    print(f"  cat {client_config}")
    sys.exit(1)

if __name__ == "__main__":
    main()
