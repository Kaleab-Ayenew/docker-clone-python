import os
import ctypes
import sys

try:
    libc = ctypes.CDLL('libc.so.6', use_errno=True)
except OSError:
    print("FATAL: libc.so.6 not found. This is required for sethostname.", file=sys.stderr)
    sys.exit(1)

def set_container_hostname(hostname: str):
    """
    Sets the hostname for the current process, typically within a new UTS namespace.

    """
    print(f"[Child] Setting hostname to '{hostname}'...")
    try:
        # 1. Encode the Python string into bytes, as required by C functions.
        hostname_bytes = hostname.encode('utf-8')
        
        # 2. Get the length of the byte string.
        hostname_len = len(hostname_bytes)

        # 3. Call the sethostname function from libc.
        if libc.sethostname(hostname_bytes, hostname_len) != 0:
            # If the call returns non-zero, an error occurred.
            errno = ctypes.get_errno()
            error_message = os.strerror(errno)
            
            # Raise the appropriate Python exception.
            if errno == 1: # EPERM (Operation not permitted)
                raise PermissionError(errno, f"sethostname failed: {error_message}. Insufficient privileges.")
            else:
                raise OSError(errno, f"sethostname failed: {error_message}")
        
        print("[+] Hostname set successfully.")

    except Exception as e:
        print(f"[-] FATAL: Failed to set hostname: {e}", file=sys.stderr)
        raise
