#!/usr/bin/env python3

import sys
import os
import subprocess
import re
import fcntl

def run_cmd_with_input(cmd, stdin_data=None):
    """Execute command with optional stdin, return stdout stripped"""
    result = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"ERROR: Command failed: {' '.join(cmd)}")
        print(result.stderr)
        sys.exit(1)
    return result.stdout.strip()

def main():
    if len(sys.argv) != 2:
        print("Usage: add-client.py <client-name>")
        sys.exit(1)

    client_name = sys.argv[1]
    config_dir = "./config"
    server_config = f"{config_dir}/server.conf"
    server_keys = f"{config_dir}/server.keys"
    clients_dir = f"{config_dir}/clients"
    client_dir = f"{clients_dir}/{client_name}"

    # Check if server is initialized
    if not os.path.exists(server_config):
        print("ERROR: Server not initialized!")
        print("Please start the server first: docker-compose up -d")
        sys.exit(1)

    # Check if client already exists
    if os.path.exists(client_dir):
        print(f"ERROR: Client '{client_name}' already exists!")
        sys.exit(1)

    # Lock file to prevent race conditions
    lock_file = f"{config_dir}/.add-client.lock"
    lock_fd = open(lock_file, 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        # Create client directory
        os.makedirs(client_dir, mode=0o700)

        # Read server config
        with open(server_config, 'r') as f:
            server_conf = f.read()

        # Extract VPN network from Address line (e.g., "10.201.0.1/24" -> "10.201.0")
        address_match = re.search(r'Address\s*=\s*(\d+\.\d+\.\d+)\.\d+/\d+', server_conf)
        if not address_match:
            print("ERROR: Cannot parse VPN network from server config")
            sys.exit(1)

        vpn_network = address_match.group(1)

        # Find next available IP
        print("Finding next available IP...")
        existing_ips = re.findall(rf'AllowedIPs\s*=\s*{re.escape(vpn_network)}\.(\d+)/32', server_conf)
        if existing_ips:
            last_ip = max(int(ip) for ip in existing_ips)
            client_ip_num = max(last_ip + 1, 2)
        else:
            client_ip_num = 2

        client_ip = f"{vpn_network}.{client_ip_num}"
        print(f"Assigned IP: {client_ip}")

        # Generate keys using proper subprocess (no echo!)
        print("Generating client keys...")

        # Generate private key
        client_private = run_cmd_with_input(['docker', 'exec', 'amneziawg-server', 'awg', 'genkey'])

        # Generate public key from private (pass via stdin, no echo!)
        client_public = run_cmd_with_input(
            ['docker', 'exec', '-i', 'amneziawg-server', 'awg', 'pubkey'],
            stdin_data=client_private
        )

        # Generate preshared key
        preshared = run_cmd_with_input(['docker', 'exec', 'amneziawg-server', 'awg', 'genpsk'])

        # Validate key lengths (base64 keys should be 44 chars for WireGuard)
        if len(client_private) != 44:
            print(f"ERROR: Invalid private key length: {len(client_private)} (expected 44)")
            sys.exit(1)
        if len(client_public) != 44:
            print(f"ERROR: Invalid public key length: {len(client_public)} (expected 44)")
            sys.exit(1)
        if len(preshared) != 44:
            print(f"ERROR: Invalid preshared key length: {len(preshared)} (expected 44)")
            sys.exit(1)

        print(f"✓ Keys generated successfully (lengths: {len(client_private)}, {len(client_public)}, {len(preshared)})")

        # Save keys
        with open(f"{client_dir}/privatekey", 'w') as f:
            f.write(client_private)
        with open(f"{client_dir}/publickey", 'w') as f:
            f.write(client_public)
        with open(f"{client_dir}/presharedkey", 'w') as f:
            f.write(preshared)

        os.chmod(f"{client_dir}/privatekey", 0o600)
        os.chmod(f"{client_dir}/publickey", 0o600)
        os.chmod(f"{client_dir}/presharedkey", 0o600)

        # Get server public key
        if os.path.exists(server_keys):
            with open(server_keys, 'r') as f:
                keys_content = f.read()

            # Parse PUBLIC_KEY line
            for line in keys_content.split('\n'):
                line = line.strip()
                if line.startswith('PUBLIC_KEY='):
                    server_public = line.split('=', 1)[1].strip()
                    break
            else:
                print("ERROR: PUBLIC_KEY not found in server.keys")
                sys.exit(1)

            # Debug: check what we got
            if len(server_public) != 44:
                print(f"WARNING: server.keys contains invalid public key!")
                print(f"  Expected length: 44")
                print(f"  Actual length: {len(server_public)}")
                print(f"  Key value: '{server_public}'")
                print()
                print("Attempting to regenerate from private key...")

                # Try to regenerate from private key in config
                private_match = re.search(r'PrivateKey\s*=\s*(\S+)', server_conf)
                if not private_match:
                    print("ERROR: Cannot find server private key in config")
                    sys.exit(1)

                server_private = private_match.group(1).strip()
                server_public = run_cmd_with_input(
                    ['docker', 'exec', '-i', 'amneziawg-server', 'awg', 'pubkey'],
                    stdin_data=server_private
                )

                if len(server_public) != 44:
                    print(f"ERROR: Even regenerated key is invalid: {len(server_public)} chars")
                    sys.exit(1)

                print(f"✓ Regenerated valid key: {len(server_public)} chars")

                # Update server.keys file
                with open(server_keys, 'r') as f:
                    keys_lines = f.readlines()

                with open(server_keys, 'w') as f:
                    for line in keys_lines:
                        if line.strip().startswith('PUBLIC_KEY='):
                            f.write(f"PUBLIC_KEY={server_public}\n")
                        else:
                            f.write(line)

                print("✓ Updated server.keys with correct key")
        else:
            # Fallback: derive from private key in config
            private_match = re.search(r'PrivateKey\s*=\s*(\S+)', server_conf)
            if not private_match:
                print("ERROR: Cannot find server private key")
                sys.exit(1)

            server_private = private_match.group(1).strip()

            # Generate public key from private (pass via stdin, no echo!)
            server_public = run_cmd_with_input(
                ['docker', 'exec', '-i', 'amneziawg-server', 'awg', 'pubkey'],
                stdin_data=server_private
            )

        # Validate server public key
        if len(server_public) != 44:
            print(f"ERROR: Invalid server public key length: {len(server_public)} (expected 44)")
            print(f"Server public key: '{server_public}'")
            sys.exit(1)

        # Get server settings from environment
        try:
            server_ip = run_cmd_with_input(['docker', 'exec', 'amneziawg-server', 'printenv', 'SERVER_IP'])
            listen_port = run_cmd_with_input(['docker', 'exec', 'amneziawg-server', 'printenv', 'LISTEN_PORT'])
            dns = run_cmd_with_input(['docker', 'exec', 'amneziawg-server', 'printenv', 'DNS'])
        except Exception as e:
            print(f"ERROR: Failed to get server settings: {e}")
            sys.exit(1)

        # Extract obfuscation parameters from server config
        obf_params = {}
        for param in ['Jc', 'Jmin', 'Jmax', 'S1', 'S2', 'H1', 'H2', 'H3', 'H4']:
            match = re.search(rf'^{param}\s*=\s*(\d+)', server_conf, re.MULTILINE)
            obf_params[param] = match.group(1) if match else '0'

        # Create client config (AmneziaWG format)
        client_config = f"""[Interface]
PrivateKey = {client_private}
Address = {client_ip}/32
DNS = {dns}
Jc = {obf_params['Jc']}
Jmin = {obf_params['Jmin']}
Jmax = {obf_params['Jmax']}
S1 = {obf_params['S1']}
S2 = {obf_params['S2']}
H1 = {obf_params['H1']}
H2 = {obf_params['H2']}
H3 = {obf_params['H3']}
H4 = {obf_params['H4']}

[Peer]
PublicKey = {server_public}
PresharedKey = {preshared}
Endpoint = {server_ip}:{listen_port}
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""

        with open(f"{client_dir}/{client_name}.conf", 'w') as f:
            f.write(client_config)

        os.chmod(f"{client_dir}/{client_name}.conf", 0o600)

        # Add peer to server config
        peer_config = f"""
[Peer]
# Client: {client_name}
PublicKey = {client_public}
PresharedKey = {preshared}
AllowedIPs = {client_ip}/32
"""

        with open(server_config, 'a') as f:
            f.write(peer_config)

        print()
        print(f"✓ Client '{client_name}' created successfully!")
        print()
        print("Client configuration:")
        print(f"  - Config file: {client_dir}/{client_name}.conf")
        print(f"  - IP address: {client_ip}")
        print(f"  - Public key: {client_public}")
        print(f"  - Server public key: {server_public}")
        print()

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

if __name__ == "__main__":
    main()
