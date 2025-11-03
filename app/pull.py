import sys
import requests, tarfile
from pathlib import Path
import os
from app.configs import LOCAL_IMAGE_REGISTRY, SESSION_DATA_PATH, LAYER_BLOB_PATH, EXTRACTED_LAYERS_PATH
import  json
import gzip
import hashlib

import shutil

def sha256_of_tgz_stream(filepath):
    sha256_hash = hashlib.sha256()
    block_size = 65536  # You can adjust this value for performance
    try:
        with gzip.open(filepath, 'rb') as f:
            while True:
                chunk = f.read(block_size)
                if not chunk:
                    break
                sha256_hash.update(chunk)
    except FileNotFoundError:
        print(f"Error: The file '{filepath}' was not found.")
        return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

    return sha256_hash.hexdigest()


def download_layer(download_url, digest: str, auth_data, dir):
    download_path = Path(dir)
    download_path.mkdir(parents=True, exist_ok=True)
    if (download_path/digest).exists():
        print(f"Image {download_url} exists locally.")
        return download_path/digest
    
    with requests.get(download_url, headers=auth_data, stream=True) as rsp:
        rsp.raise_for_status()

        with open(download_path/digest, "wb") as f:
            for chunk in rsp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return download_path/digest

def extract_layer(layer_path, dest_path):
    os.makedirs(dest_path, exist_ok=True)
    with tarfile.open(layer_path, mode="r:*") as tar:
        tar.extractall(dest_path)


def parse_auth_data(data: str):
    data_list = data.split(",")
    data_pairs = [(l.split('=')[0], l.split('=')[1].replace('"', "")) for l in data_list]
    data_map = {a:b for a,b in data_pairs}
    return data_map

def auth_docker(pull_url):
    rsp = requests.get(pull_url)
    print("Status code: ", rsp.status_code)
    print(rsp.text)
    print(rsp.headers)
    token_scheme, auth_data = rsp.headers.get("www-authenticate").split(" ")
    auth_data_map = parse_auth_data(auth_data)
    auth_params = {
        "service": auth_data_map["service"],
        "scope"  : auth_data_map["scope"],
    }
    token_data = requests.get(auth_data_map.get("realm"), params=auth_params)
    token = token_data.json().get("token")
    session_data = dict()
    with open(SESSION_DATA_PATH, "w") as f:
        session_data["token"] = token
        session_data["scheme"] = token_scheme
        json.dump(session_data, f)
    return token, token_scheme

def docker_pull(image, dest_dir):
    image_name = image.split(':')[0]
    image_tag = image.split(':')[1]
    print(image_name, image_tag)
    with open(SESSION_DATA_PATH, "r") as f:
        session_data = json.load(f)
    pull_url = f"https://registry-1.docker.io/v2/library/{image_name}/manifests/{image_tag}"
    if not session_data.get("token"):
        auth_docker(pull_url)
    else:
        token, token_scheme = session_data["token"], session_data["scheme"]

    manifest_rsp = requests.get(pull_url, headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json", "Authorization": f"{token_scheme} {token}"})
    if not manifest_rsp.ok and manifest_rsp.status_code == 401:
        print(manifest_rsp.text)
        token, token_scheme = auth_docker(pull_url)
        manifest_rsp = requests.get(pull_url, headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json", "Authorization": f"{token_scheme} {token}"})
        
    manifest_data = manifest_rsp.json()
    manifests_dir = f"{LOCAL_IMAGE_REGISTRY}/{image_name}/manifests"
    os.makedirs(manifests_dir, exist_ok=True)
    if not (Path(manifests_dir)/"base_manifest.json").exists():
        with open(Path(manifests_dir)/"base_manifest.json", "w") as f:
            json.dump(manifest_data, f)

    print(manifest_data)
    layer_list = []
    for m in manifest_data["manifests"]:
        if m['platform']['os'] != 'linux' or m['platform']['architecture'] != 'amd64':
            continue
        manifest_url = f"https://registry-1.docker.io/v2/library/{image_name}/blobs/{m['digest']}"
        digest_data = requests.get(manifest_url, headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json", "Authorization": f"{token_scheme} {token}"}).json()
        if not (Path(manifests_dir)/"arch_manifest.json").exists():
            with open(Path(manifests_dir)/"arch_manifest.json", "w") as f:
                json.dump(digest_data, f)

        for l in digest_data['layers']:
            blob_path = Path(LAYER_BLOB_PATH) / l['digest']
            if not blob_path.exists():
                blob_url = f"https://registry-1.docker.io/v2/library/{image_name}/blobs/{l['digest']}"
                blob_path = download_layer(blob_url, l['digest'], {"Authorization": f"{token_scheme} {token}"}, LAYER_BLOB_PATH)

            decompressed_hash = sha256_of_tgz_stream(blob_path)
            dest_dir = Path(EXTRACTED_LAYERS_PATH) / decompressed_hash
            extract_layer(blob_path, dest_dir)
            print(f"Extracted layer to: {dest_dir}")
            
        config_manifest_url = f"https://registry-1.docker.io/v2/library/{image_name}/blobs/{digest_data['config']['digest']}"
        config_manifest_data = requests.get(config_manifest_url, headers={"Authorization": f"{token_scheme} {token}"}).json()
        
        if not (Path(manifests_dir)/"config_manifest.json").exists():
            print("[*] Creating the config manifest data...")
            with open(Path(manifests_dir)/"config_manifest.json","w") as f:
                json.dump(config_manifest_data, f)
        
        

    return Path(f"{dest_dir}/{image_name}/layers")


def docker_run(dest_dir: str, image_dir: Path):
    extract_dir = Path(dest_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    layer_list = os.listdir(image_dir)
    for l in layer_list:
        print(image_dir, extract_dir)





if __name__ == "__main__":
    image_with_tag = sys.argv[1]
    docker_pull(image_with_tag, LOCAL_IMAGE_REGISTRY)