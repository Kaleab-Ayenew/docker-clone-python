import subprocess
from app import configs
from app.configs import DEFAULT_BRIDGE_IP, DEFAULT_BRIDGE_NAME
import os
from pyroute2 import IPRoute, NetNS
from pyroute2.netlink.exceptions import NetlinkError


class ContainerNetworkingManager:
    """
    Manages container networking using pyroute2 for direct kernel interaction.
    """
    def __init__(self, bridge_name: str = configs.DEFAULT_BRIDGE_NAME, bridge_ip="172.20.0.1/24", container_id: str = None):
        self.bridge_name = bridge_name
        self.bridge_ip = bridge_ip
        self.ipr = IPRoute()
        self.container_id = container_id
    

    
        
    def get_default_interface_pyroute2(self):
        """
        Gets the name of the default network interface using pyroute2.
        """
        with IPRoute() as ipr:
            # Get a list of all default routes, sorted by priority (metric).
            # We only care about IPv4 for this use case (family=2).
            default_routes = ipr.get_default_routes(family=2)
            
            if not default_routes:
                return None # No default route found

            # The best route is the first one in the list.
            best_route = default_routes[0]
            
            # Get the 'RTA_OIF' (Output Interface) attribute, which is the interface index.
            if_index = best_route.get_attr('RTA_OIF')
            
            if if_index:
                # Get the interface name from its index.
                if_name = ipr.get_links(if_index)[0].get_attr('IFLA_IFNAME')
                return if_name
                
        return None
    


    def ensure_nat_masquerading(self, bridge_name: str, bridge_subnet: str, public_iface: str):
        """
        Ensures that NAT masquerading and necessary forwarding rules are in place.
        """
        if os.geteuid() != 0:
            raise PermissionError("iptables operations require root privileges.")

        print("--- Ensuring NAT and forwarding rules ---")
        print(f"Using {public_iface} for NAT masqarading!")
        # Define the rules we need to enforce
        rules = [
            # 1. The main NAT masquerade rule
            {
                "table": "nat",
                "chain": "POSTROUTING",
                "rule": ["-s", bridge_subnet, "-o", public_iface, "-j", "MASQUERADE"],
                "description": "NAT masquerade rule for the container bridge"
            },
            # 2. Forwarding rule: Allow traffic from the bridge out to the public interface
            {
                "table": "filter",
                "chain": "FORWARD",
                "rule": ["-i", bridge_name, "-o", public_iface, "-j", "ACCEPT"],
                "description": "Allow forwarding from bridge to public interface"
            },
            # 3. Forwarding rule: Allow return traffic for established connections
            {
                "table": "filter",
                "chain": "FORWARD",
                "rule": ["-i", public_iface, "-o", bridge_name, "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
                "description": "Allow return traffic to the bridge"
            }
        ]

        for rule_spec in rules:
            table = rule_spec["table"]
            chain = rule_spec["chain"]
            rule = rule_spec["rule"]
            
            # Construct the command to check if the rule exists
            check_cmd = ["iptables", "-t", table, "-C", chain] + rule
            
            # Use subprocess.call which returns the exit code (0 for success)
            # We hide the output because a non-zero exit code is expected and normal.
            rule_exists = subprocess.call(check_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0

            if not rule_exists:
                print(f"[+] Adding rule: {rule_spec['description']}")
                # Construct the command to add the rule
                add_cmd = ["iptables", "-t", table, "-A", chain] + rule
                # Run the command, raising an exception on failure
                subprocess.run(add_cmd, check=True)
            else:
                print(f"[*] Rule already exists: {rule_spec['description']}")

        print("--- NAT and forwarding rules are in place ---")


    # --- Example Usage in your Host Setup ---


    def setup_host_infrastructure(self):
        """
        Sets up the host-level bridge. This is an idempotent operation.
        """
        print("--- Setting up host networking infrastructure ---")
        try:
            # 1. Create the Bridge
            self.ipr.link("add", ifname=self.bridge_name, kind="bridge")
            print(f"[+] Bridge '{self.bridge_name}' created.")
        except NetlinkError as e:
            if e.code == 17: # EEXIST - File exists
                print(f"[*] Bridge '{self.bridge_name}' already exists.")
            else:
                raise

        # Get the interface index for the bridge
        bridge_idx = self.ipr.link_lookup(ifname=self.bridge_name)[0]

        # 2. Assign an IP to the Bridge
        try:
            # Note: The IP is passed as two args: address and mask
            addr, mask = self.bridge_ip.split('/')
            self.ipr.addr("add", index=bridge_idx, address=addr, mask=int(mask))
            print(f"[+] IP {self.bridge_ip} assigned to bridge.")
        except NetlinkError as e:
            if e.code == 17: # EEXIST
                print(f"[*] IP {self.bridge_ip} already assigned to bridge.")
            else:
                raise
        
        # 3. Activate the Bridge
        self.ipr.link("set", index=bridge_idx, state="up")
        print(f"[+] Bridge '{self.bridge_name}' is up.")

        self.ensure_nat_masquerading(self.bridge_name, DEFAULT_BRIDGE_IP, self.get_default_interface_pyroute2())
        print("--- Host infrastructure setup complete ---")

    def wire_container(self, child_pid: int, container_ip: str, veth_suffix: str):
        """
        Wires up a specific container by creating a veth pair and configuring it.

        Args:
            child_pid (int): The PID of the child process in its new namespace.
            container_ip (str): The IP address to assign to the container (e.g., "172.20.0.2/24").
            veth_suffix (str): A unique suffix for the veth pair (e.g., the container ID).
        """
        print(f"\n--- Wiring up container with PID {child_pid} ---")
        bridge_idx = self.ipr.link_lookup(ifname=self.bridge_name)[0]
        veth_host = f"vh-{veth_suffix}"
        veth_container = f"vc-{veth_suffix}"

        # 1. Create the veth Pair
        self.ipr.link("add", ifname=veth_host, kind="veth", peer=veth_container)
        print(f"[+] Created veth pair: {veth_host} <--> {veth_container}")

        # 2. Connect the Host End to the Bridge
        veth_host_idx = self.ipr.link_lookup(ifname=veth_host)[0]
        self.ipr.link("set", index=veth_host_idx, master=bridge_idx)
        self.ipr.link("set", index=veth_host_idx, state="up")
        print(f"[+] Attached '{veth_host}' to bridge '{self.bridge_name}'.")

        # 3. Move the Container End into the Namespace
        veth_container_idx = self.ipr.link_lookup(ifname=veth_container)[0]
        self.ipr.link("set", index=veth_container_idx, net_ns_pid=child_pid)
        print(f"[+] Moved '{veth_container}' into namespace of PID {child_pid}.")

        # 4. Configure the Interface *Inside* the Namespace
        #    We use the NetNS object to run commands within the child's namespace.
        with NetNS(f"/proc/{child_pid}/ns/net") as ns:
            print(f"[+] Switched to namespace of PID {child_pid} for configuration.")
            
            # Get the index of the interface *inside* the new namespace
            cont_idx = ns.link_lookup(ifname=veth_container)[0]
            
            # a. Rename the interface to 'eth0'
            ns.link("set", index=cont_idx, ifname="eth0")
            print("    - Renamed interface to 'eth0'.")
            
            # b. Assign the IP address
            addr, mask = container_ip.split('/')
            ns.addr("add", index=cont_idx, address=addr, mask=int(mask))
            print(f"    - Assigned IP {container_ip} to 'eth0'.")

            # c. Activate the interface
            ns.link("set", index=cont_idx, state="up")
            print("    - Set 'eth0' state to 'up'.")

            # d. Set the default gateway
            gateway_ip = self.bridge_ip.split('/')[0]
            ns.route("add", gateway=gateway_ip)
            print(f"    - Set default gateway to {gateway_ip}.")
        
        print("--- Container wiring complete ---")

    def cleanup(self):
        """Closes the IPRoute socket."""
        self.ipr.close()

# --- Example Usage in your Parent Process ---
if __name__ == "__main__":
    # This would be in your parent's `else` block after forking.
    # We'll simulate it here.
    
    # Assume a child process has been forked and is waiting.
    # We'll create a dummy namespace to simulate the child.
    DUMMY_NS = "my-test-ns"
    os.system(f"sudo ip netns add {DUMMY_NS}")
    # Get the PID of a process inside the namespace to use as a handle
    os.system(f"sudo ip netns exec {DUMMY_NS} sleep 10 &")
    time.sleep(0.1)
    child_pid_str = os.popen(f"sudo ip netns pids {DUMMY_NS}").read().strip()
    if not child_pid_str:
        raise RuntimeError("Could not create dummy namespace process.")
    CHILD_PID = int(child_pid_str)

    try:
        # The parent process would instantiate this manager
        net_manager = ContainerNetworkingManager(DEFAULT_BRIDGE_NAME, DEFAULT_BRIDGE_IP)
        
        # 1. Set up the host bridge (only needs to be done once)
        net_manager.setup_host_infrastructure()
        
        # 2. Wire the specific container
        net_manager.wire_container(
            child_pid=CHILD_PID,
            container_ip="172.16.7.10/24",
            veth_suffix="tst-1"
        )
        
        # 3. Verify the setup from the host
        print("\n--- Verifying setup ---")
        os.system("ip addr show cbr0")
        os.system(f"sudo ip netns exec {DUMMY_NS} ip addr")
        os.system(f"sudo ip netns exec {DUMMY_NS} ip route")

    finally:
        # Clean up the manager and the dummy namespace
        net_manager.cleanup()
        os.system(f"sudo ip netns del {DUMMY_NS}")
        print("\n--- Cleanup complete ---")





    
    

    
