import subprocess
from pyroute2 import IPRoute, IPDB
from pyroute2.netlink.exceptions import NetlinkError
from app.configs import DEFAULT_BRIDGE_IP, DEFAULT_BRIDGE_NAME

def run_cmd(cmd):
    """Helper to run shell commands."""
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

def get_default_interface():
    with IPRoute() as ipr:
        routes = ipr.get_default_routes(family=2) # IPv4
        if routes:
            if_index = routes[0].get_attr('RTA_OIF')
            if_name = ipr.get_links(if_index)[0].get_attr('IFLA_IFNAME')
            print(f"Found default interface '{if_name}' via pyroute2.")
            return if_name


def setup_host_networking():
    with open('/proc/sys/net/ipv4/ip_forward', 'w') as f:
        f.write('1')
    with IPRoute() as ipr:
        try:
            idx = ipr.link_lookup(ifname=DEFAULT_BRIDGE_NAME)[0]
        except IndexError:
            print(f"Creating bridge '{DEFAULT_BRIDGE_NAME}'...")
            ipr.link('add', ifname=DEFAULT_BRIDGE_NAME, kind='bridge')
            idx = ipr.link_lookup(ifname=DEFAULT_BRIDGE_NAME)[0]
        current_addrs = ipr.get_addr(index=idx)
        print(current_addrs)
        ip_assigned = any(
            addr.get_attr('IFA_ADDRESS') == DEFAULT_BRIDGE_IP.split("/")[0] for addr in current_addrs
        )
        if not ip_assigned:
            try:
                ipr.addr('add', index=idx, address=DEFAULT_BRIDGE_IP.split("/")[0], mask=int(DEFAULT_BRIDGE_IP.split("/")[1]))
            except NetlinkError as e:
                if e.code == 17: # File exists
                    print(f"IP address {DEFAULT_BRIDGE_IP} was already assigned.")
                raise e
        else:
            print(f"IP address {DEFAULT_BRIDGE_IP} is already assigned.")
        
        current_state = ipr.get_links(idx)[0].get_attr('IFLA_OPERSTATE')
        if current_state != 'UP':
            print(f"Activating bridge '{DEFAULT_BRIDGE_NAME}' (setting state to 'up')...")
            ipr.link('set', index=idx, state='up')
        else:
            print(f"Bridge '{DEFAULT_BRIDGE_NAME}' is already up.")
        

def remove_bridge_network(bridge_name=DEFAULT_BRIDGE_NAME):
    """
    Removes a virtual bridge network.

    Args:
        bridge_name (str): The name of the bridge device to remove.
    """
    with IPRoute() as ipr:
        print(f"\n--- Tearing down bridge '{bridge_name}' ---")
        try:
            idx = ipr.link_lookup(ifname=bridge_name)[0]
            print(f"Removing bridge '{bridge_name}' (index: {idx})...")
            ipr.link('del', index=idx)
            print("Teardown complete.")
        except IndexError:
            print(f"Bridge '{bridge_name}' does not exist, nothing to do.")
        except Exception as e:
            print(f"An error occurred during teardown: {e}")

def verify_bridge(bridge_name=DEFAULT_BRIDGE_NAME):
    """Checks the system to see if the bridge is configured correctly."""
    with IPRoute() as ipr:
        try:
            idx = ipr.link_lookup(ifname=bridge_name)[0]
            link = ipr.get_links(idx)[0]
            addrs = ipr.get_addr(index=idx)
            print(f"\n--- Verification for '{bridge_name}' ---")
            print(f"  Index: {link.get('index')}")
            print(f"  State: {link.get_attr('IFLA_OPERSTATE')}")
            for addr in addrs:
                print(f"  IP Address: {addr.get_attr('IFA_ADDRESS')}/{addr.get('prefixlen')}")
            print("------------------------------------")
        except IndexError:
            print(f"\n--- Verification for '{bridge_name}' ---")
            print("  Bridge does not exist.")
            print("------------------------------------")
       

def setup_veth_cables(container_id):
    """
    Create a veth pair
    Move the container end to the container's network namespace
    Assign an IP to the container's veth end and rename it to a convinient name
    Attach the host veth to the bridge
    Add default routes to the container's namespace to route via the bridge's IP
    """
    veth_base_name = f"dcvth{container_id[:3]}"
    with IPDB() as ip:
        with ip.create(ifname=veth_base_name+"host", kind='veth', peer=veth_base_name+"cont") as veth_pair:
            veth_pair.up.commit()
            veth_pair.peer.up().commit()
        print(f"Veth with base name '{veth_base_name}' has been brought up for both host and container.")




def setup_nat_masquarading():
    """
    Apply NAT MASQUARADING to any request coming from the bridge and trying to leave via the
    default phyisical interface.
    """
    pass










    
    

    
