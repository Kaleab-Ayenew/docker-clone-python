import os
import ctypes
from pathlib import Path
from app import configs
import json
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







if __name__ == "__main__":
    setup_filesystem(sys.argv[1])