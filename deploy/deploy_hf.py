"""Upload deploy/hf-space/ to a Hugging Face Docker Space (creates the Space if needed).

Log in first, once, in a terminal:  hf auth login   (paste a *write* token from
https://huggingface.co/settings/tokens; it is stored by Hugging Face on this PC, not in this project).

Usage: python deploy/deploy_hf.py [--space kpsterra]
"""
import argparse
from pathlib import Path

from huggingface_hub import HfApi

OUT = Path(__file__).resolve().parent / "hf-space"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default="kpsterra")
    a = ap.parse_args()
    api = HfApi()
    user = api.whoami()["name"]
    repo = f"{user}/{a.space}"
    api.create_repo(repo, repo_type="space", space_sdk="docker", exist_ok=True)
    api.upload_folder(folder_path=str(OUT), repo_id=repo, repo_type="space",
                      commit_message="Deploy KPSTerra", ignore_patterns=["**/__pycache__/**", "*.pyc"])
    print(f"uploaded -> https://huggingface.co/spaces/{repo}")
    print(f"app will be live at https://{user}-{a.space}.hf.space once the build finishes (~5-10 min)")
    print("Next: add the secret FIRMS_MAP_KEY in the Space settings (Settings -> Variables and secrets).")


if __name__ == "__main__":
    main()
