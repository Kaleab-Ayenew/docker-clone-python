import requests, tarfile
from pathlib import Path
import os
from app.configs import LOCAL_IMAGE_REGISTRY, SESSION_DATA_PATH
import  json


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
    print(manifest_data)
    layer_list = []
    for m in manifest_data["manifests"]:
        if m['platform']['os'] != 'linux' or m['platform']['architecture'] != 'amd64':
            continue
        manifest_url = f"https://registry-1.docker.io/v2/library/{image_name}/blobs/{m['digest']}"
        digest_data = requests.get(manifest_url, headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json", "Authorization": f"{token_scheme} {token}"}).json()
        for l in digest_data['layers']:
            blob_url = f"https://registry-1.docker.io/v2/library/{image_name}/blobs/{l['digest']}"
            layer_list.append(download_layer(blob_url, m['digest'], {"Authorization": f"{token_scheme} {token}"}, f"{dest_dir}/{image_name}/layers"))

    return Path(f"{dest_dir}/{image_name}/layers")


def docker_run(dest_dir: str, image_dir: Path):
    print("Image dir: ", image_dir)
    extract_dir = Path(dest_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    layer_list = os.listdir(image_dir)
    for l in layer_list:
        extract_layer(image_dir/l, extract_dir)

if __name__ == "__main__":
    docker_pull("alpine:latest")