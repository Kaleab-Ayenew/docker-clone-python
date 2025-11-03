import os
import ctypes
from pathlib import Path
from app import configs
import json
import shutil
import sys


libc = ctypes.CDLL('libc.so.6', use_errno=True)

def create_overlay_filesystem(lowerdirs: list, upperdir: str, workdir: str, mountpoint: str):
    """
    Creates an overlay filesystem mount using ctypes to call the mount syscall.

    Args:
        lowerdir: The read-only base directory.
        upperdir: The directory where changes will be written.
        workdir: A working directory, must be on the same filesystem as upperdir.
        mountpoint: The destination where the overlay filesystem will be mounted.
    """
    print(lowerdirs, upperdir, workdir, mountpoint)
    libc.mount.argtypes = (
        ctypes.c_char_p,  # source
        ctypes.c_char_p,  # target
        ctypes.c_char_p,  # filesystemtype
        ctypes.c_ulong,   # mountflags
        ctypes.c_char_p   # data
    )

    # Prepare the mount options for overlayfs
    options = f"lowerdir={':'.join(lowerdirs)},upperdir={upperdir},workdir={workdir}"
    print(options)
    # Encode strings to bytes
    source = b"overlay"
    target = mountpoint.encode('utf-8')
    filesystemtype = b"overlay"
    data = options.encode('utf-8')

    # The mountflags argument is not used for overlayfs, so it can be 0
    mountflags = 0

    # Call the mount function
    ret = libc.mount(source, target, filesystemtype, mountflags, data)
    if ret != 0:
        errno = ctypes.get_errno()
        raise OSError(errno or 1, f"Error mounting overlay filesystem: {os.strerror(errno) if errno else 'Mount failed'}")
        
def setup_filesystem(container_id):
    image_name = container_id.split(':')[0]
    safe_id = container_id.replace(':', '_').replace('/', '_')

    crnt_base = Path(configs.CONTAINER_RUNTIME_ROOT_DIR)/safe_id
    overlay_dir = crnt_base/"overlay"
    upper_dir = overlay_dir/"upperdir"
    workdir = overlay_dir/"workdir"
    runt_dir = crnt_base/"runtime_dir"

    Path(configs.CONTAINER_RUNTIME_ROOT_DIR).mkdir(parents=True, exist_ok=True)

    for d in (overlay_dir, upper_dir, workdir, runt_dir):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception as e:
            print(f"❌ Failed to create {d}: {e}")
            raise
        else:
            print(f"✅ Ensured dir: {d} (exists={os.path.isdir(d)})")

    manifest_path = Path(configs.LOCAL_IMAGE_REGISTRY)/image_name/"manifests"/"config_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}. Pull the image first.")

    with open(manifest_path, "r") as f:
        config_manifest = json.load(f)

    try:
        layers_hashes = [h.split(":")[-1] for h in config_manifest["rootfs"]["diff_ids"]]
    except Exception as e:
        raise KeyError(f"config manifest missing rootfs.diff_ids: {e}")

    lowerdirs = [os.path.join(configs.EXTRACTED_LAYERS_PATH, layer_hash) for layer_hash in layers_hashes]
    print(lowerdirs)
    create_overlay_filesystem(lowerdirs, str(upper_dir), str(workdir), str(runt_dir))
    print("Succesfully created overlay filesystem.")
    prepare_container_resolv_conf(configs.CONTAINER_RUNTIME_ROOT_DIR)
    print("Succesfully copied DNS files.")


def prepare_container_resolv_conf(container_workdir: str):
    """
    Intelligently prepares a resolv.conf for the container.

    On systemd-resolved systems, it reads the real upstream DNS servers.
    Otherwise, it falls back to the standard /etc/resolv.conf.

    Args:
        container_workdir (str): A directory to store the new file.

    Returns:
        str: The path to the newly created, container-ready resolv.conf file.
    """
    # Path to the real DNS servers on systemd-resolved systems
    SYSTEMD_RESOLV_PATH = "/run/systemd/resolve/resolv.conf"
    # The traditional fallback
    TRADITIONAL_RESOLV_PATH = "/etc/resolv.conf"

    source_path = ""
    if os.path.exists(SYSTEMD_RESOLV_PATH):
        print(f"[*] Found systemd-resolved config, using '{SYSTEMD_RESOLV_PATH}' as source.")
        source_path = SYSTEMD_RESOLV_PATH
    else:
        print(f"[*] Using traditional DNS config at '{TRADITIONAL_RESOLV_PATH}'.")
        source_path = TRADITIONAL_RESOLV_PATH

    destination_dir = os.path.join(container_workdir, "temp")
    os.makedirs(destination_dir, exist_ok=True)
    
    container_resolv_path = os.path.join(destination_dir, "resolv.conf")

    try:
        # We use copy, not copyfile, as it handles permissions better.
        shutil.copy(source_path, container_resolv_path)
        print(f"[+] DNS config copied to '{container_resolv_path}' successfully.")
        return container_resolv_path
    except Exception as e:
        print(f"[!] Warning: Could not copy DNS config: {e}. Creating a fallback.")
        # If all else fails, create a file with a public DNS server.
        with open(container_resolv_path, 'w') as f:
            f.write("nameserver 8.8.8.8\n")
        return container_resolv_path





if __name__ == "__main__":
    
    setup_filesystem(sys.argv[1])
